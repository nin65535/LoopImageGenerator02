"""Single-image WD14 tagging directly from ComfyUI history; no TXT or DB writes."""

import asyncio
import math
from dataclasses import dataclass
from uuid import uuid4

from backend.comfyui import ComfyUIClient, ComfyUIError, ComfyUITimeout
from backend.reference_images import MAX_BYTES, validate_image

TAG_NODE = "2"


def parse_tags(outputs: dict, node_id: str = TAG_NODE) -> dict[str, None]:
    node = outputs.get(node_id)
    if not isinstance(node, dict) or "tags" not in node:
        raise ComfyUIError("Tagging output is missing", details={"node_id": node_id})
    values = node["tags"]
    # WD14 UI output is one string per image. Never merge an accidental batch.
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str):
        raise ComfyUIError("Expected tags for exactly one image", details={"node_id": node_id})
    return dict.fromkeys(tag.strip() for tag in values[0].split(",") if tag.strip())


@dataclass(frozen=True)
class TaggingResult:
    prompt_id: str
    tags: dict[str, None]


async def tag_image(
    client: ComfyUIClient,
    data: bytes,
    *,
    model: str = "wd-v1-4-moat-tagger-v2",
    threshold: float = 0.35,
    character_threshold: float = 0.85,
    timeout: float = 300,
) -> TaggingResult:
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Tagger model must be non-empty")
    for value in (threshold, character_threshold):
        if isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Tagger thresholds must be between 0 and 1")
    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be finite and positive")
    if len(data) > MAX_BYTES:
        raise ComfyUIError("Tagging image exceeds 20MiB")
    extension = await asyncio.to_thread(validate_image, data)
    started = asyncio.get_running_loop().time()
    try:
        async with asyncio.timeout(timeout):
            uploaded = await client._request(
                "POST",
                "/upload/image",
                min(timeout, 30),
                files={"image": (f"{uuid4().hex}.{extension}", data)},
                data={"type": "input", "overwrite": "false"},
            )
    except TimeoutError as exc:
        raise ComfyUITimeout("ComfyUI image tagging timed out") from exc

    name = uploaded.get("name")
    subfolder = uploaded.get("subfolder")
    if (
        not isinstance(name, str)
        or not name
        or "/" in name
        or "\\" in name
        or name in {".", ".."}
        or subfolder != ""
        or uploaded.get("type") != "input"
    ):
        raise ComfyUIError("Invalid image upload response", details=uploaded)
    workflow = {
        "1": {"class_type": "LoadImage", "inputs": {"image": name}},
        TAG_NODE: {
            "class_type": "WD14Tagger|pysssss",
            "inputs": {
                "image": ["1", 0],
                "model": model,
                "threshold": threshold,
                "character_threshold": character_threshold,
                "replace_underscore": False,
                "trailing_comma": False,
                "exclude_tags": "",
            },
        },
    }
    remaining = timeout - (asyncio.get_running_loop().time() - started)
    if remaining <= 0:
        raise ComfyUITimeout("ComfyUI image tagging timed out before submission")
    result = await client.execute(workflow, timeout=remaining)
    try:
        tags = parse_tags(result.outputs)
    except ComfyUIError as exc:
        exc.prompt_id = result.prompt_id
        raise
    return TaggingResult(result.prompt_id, tags)
