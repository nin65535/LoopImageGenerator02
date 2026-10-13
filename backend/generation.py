"""Generate candidates in memory for tagging and completed Generation persistence."""

import asyncio
import io
import math
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from PIL import Image

from backend.comfyui import ComfyUIClient, ComfyUIError, ComfyUITimeout
from backend.config import Settings
from backend.reference_images import MAX_BYTES, validate_image


@dataclass(frozen=True)
class GeneratedImage:
    position: int
    seed: int
    prompt_id: str
    data: bytes
    workflow: dict


@dataclass(frozen=True)
class GenerationResult:
    parameters: dict
    images: tuple[GeneratedImage, ...]


def build_workflow(parameters: dict, seed: int) -> dict:
    return {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": parameters["checkpoint"]},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "batch_size": 1,
                "width": parameters["width"],
                "height": parameters["height"],
            },
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["4", 1], "text": parameters["positive"]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["4", 1], "text": parameters["negative"]},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
                "seed": seed,
                "steps": parameters["steps"],
                "cfg": parameters["cfg"],
                "sampler_name": parameters["sampler"],
                "scheduler": parameters["scheduler"],
                "denoise": 1.0,
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "PreviewImage", "inputs": {"images": ["8", 0]}},
    }


async def generate_images(
    client: ComfyUIClient,
    settings: Settings,
    *,
    checkpoint: str,
    positive: str,
    negative: str = "",
    positive_prompts: list[str] | None = None,
    on_progress: Callable[[int], None] | None = None,
    on_image: Callable[[GeneratedImage], Awaitable[None]] | None = None,
    steps: int = 20,
    cfg: float = 8.0,
    sampler: str = "euler",
    scheduler: str = "normal",
    timeout: float = 300,
) -> GenerationResult:
    for value in (checkpoint, sampler, scheduler):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Model and sampling identifiers must be non-empty strings")
    if not isinstance(positive, str) or not isinstance(negative, str):
        raise ValueError("Prompts must be strings")
    if positive_prompts is not None:
        if (
            not isinstance(positive_prompts, list)
            or len(positive_prompts) != settings.image_count
            or any(not isinstance(value, str) for value in positive_prompts)
        ):
            raise ValueError("Provide exactly one positive prompt string per image")
        positive_prompts = list(positive_prompts)
    if type(steps) is not int or not 1 <= steps <= 10000:
        raise ValueError("Steps must be an integer between 1 and 10000")
    if isinstance(cfg, bool) or not math.isfinite(cfg) or not 0 <= cfg <= 100:
        raise ValueError("CFG must be finite and between 0 and 100")
    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be finite and positive")
    if any(size < 16 or size > 16384 or size % 8 for size in (settings.width, settings.height)):
        raise ValueError("Generation dimensions must be multiples of 8 between 16 and 16384")
    parameters = {
        "workflow": "standard-txt2img-v1",
        "checkpoint": checkpoint,
        "positive": positive,
        "negative": negative,
        "steps": steps,
        "cfg": cfg,
        "sampler": sampler,
        "scheduler": scheduler,
        "denoise": 1.0,
        "image_count": settings.image_count,
        "width": settings.width,
        "height": settings.height,
    }
    images = []
    if positive_prompts is not None:
        parameters["image_prompts"] = [
            {"position": position, "positive": value, "negative": negative}
            for position, value in enumerate(positive_prompts)
        ]
    seeds = set()
    prompt_id = None
    try:
        async with asyncio.timeout(timeout):
            for position in range(settings.image_count):
                # Stay within SQLite's signed INTEGER and avoid duplicates in this run.
                seed = secrets.randbelow(2**63)
                while seed in seeds:
                    seed = secrets.randbelow(2**63)
                seeds.add(seed)
                effective = parameters
                if positive_prompts is not None:
                    effective = {**parameters, "positive": positive_prompts[position]}
                workflow = build_workflow(effective, seed)
                result = await client.execute(workflow, timeout=timeout)
                prompt_id = result.prompt_id
                node = result.outputs.get("9", {})
                descriptors = node.get("images") if isinstance(node, dict) else None
                if not isinstance(descriptors, list) or len(descriptors) != 1:
                    raise ComfyUIError("Expected exactly one generated image", prompt_id=prompt_id)
                descriptor = descriptors[0]
                if (
                    not isinstance(descriptor, dict)
                    or not isinstance(descriptor.get("filename"), str)
                    or not descriptor["filename"]
                    or not isinstance(descriptor.get("subfolder"), str)
                    or descriptor.get("type") != "temp"
                ):
                    raise ComfyUIError("Invalid generated image descriptor", prompt_id=prompt_id)
                try:
                    async with client.client.stream(
                        "GET", client.url + "/view", params=descriptor, timeout=min(timeout, 30)
                    ) as response:
                        response.raise_for_status()
                        downloaded = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(downloaded) + len(chunk) > MAX_BYTES:
                                raise ComfyUIError(
                                    "Generated image exceeds 20MiB", prompt_id=prompt_id
                                )
                            downloaded.extend(chunk)
                except httpx.TimeoutException as exc:
                    raise ComfyUITimeout("Image download timed out", prompt_id=prompt_id) from exc
                except httpx.HTTPError as exc:
                    raise ComfyUIError("Image download failed", prompt_id=prompt_id) from exc
                data = bytes(downloaded)
                try:
                    await asyncio.to_thread(validate_image, data)
                    with Image.open(io.BytesIO(data)) as image:
                        if image.size != (settings.width, settings.height):
                            raise ValueError("Generated image dimensions differ from request")
                except Exception as exc:
                    raise ComfyUIError("Invalid generated image", prompt_id=prompt_id) from exc
                images.append(GeneratedImage(position, seed, prompt_id, data, workflow))
                if on_progress:
                    on_progress(position + 1)
                if on_image:
                    await on_image(images[-1])
    except TimeoutError as exc:
        raise ComfyUITimeout("Image generation timed out", prompt_id=prompt_id) from exc
    parameters["seeds"] = [image.seed for image in images]
    return GenerationResult(parameters, tuple(images))
