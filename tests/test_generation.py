import asyncio
import io
import json

import httpx
import pytest
from PIL import Image

from backend.comfyui import ComfyUIClient, ComfyUIError
from backend.config import Settings
from backend.generation import generate_images


def run(count=2, width=64, height=96, failure=None, **kwargs):
    workflows = []
    buffer = io.BytesIO()
    Image.new("RGB", (width + 8 if failure == "dimensions" else width, height)).save(
        buffer, format="PNG"
    )

    def handler(request):
        if request.url.path == "/prompt":
            workflows.append(json.loads(request.content)["prompt"])
            return httpx.Response(200, json={"prompt_id": str(len(workflows))})
        if request.url.path.startswith("/history/"):
            descriptors = [{"filename": "preview.png", "subfolder": "", "type": "temp"}]
            if failure == "missing":
                descriptors = []
            if failure == "extra":
                descriptors *= 2
            return httpx.Response(
                200,
                json={
                    str(len(workflows)): {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {"9": {"images": descriptors}},
                    }
                },
            )
        assert request.url.path == "/view"
        assert request.url.params["filename"] == "preview.png"
        if failure == "http" or (failure == "second" and len(workflows) == 2):
            return httpx.Response(404)
        return httpx.Response(200, content=b"bad" if failure == "corrupt" else buffer.getvalue())

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await generate_images(
                ComfyUIClient(http, "http://comfy"),
                Settings(width=width, height=height).model_copy(update={"image_count": count}),
                checkpoint="model.safetensors",
                positive="sky",
                **kwargs,
            )

    return asyncio.run(execute()), workflows


@pytest.mark.parametrize("count,width,height", [(1, 64, 96), (3, 96, 64), (11, 64, 64)])
def test_variable_generation_and_exact_snapshots(count, width, height):
    result, workflows = run(count, width, height)
    assert len(result.images) == count
    assert result.parameters["image_count"] == count
    assert result.parameters["width"] == width
    assert result.parameters["height"] == height
    assert len(set(result.parameters["seeds"])) == count
    for position, (image, workflow) in enumerate(zip(result.images, workflows, strict=True)):
        assert image.position == position
        assert image.workflow == workflow
        assert image.seed == workflow["3"]["inputs"]["seed"]
        assert 0 <= image.seed < 2**63
        assert workflow["5"]["inputs"] == {"width": width, "height": height, "batch_size": 1}
        assert workflow["6"]["inputs"]["text"] == "sky"
        assert image.data
    json.dumps(result.parameters, allow_nan=False)


def test_new_execution_updates_seeds():
    first, _ = run()
    second, _ = run()
    assert set(first.parameters["seeds"]).isdisjoint(second.parameters["seeds"])


@pytest.mark.parametrize("failure", ["missing", "extra", "http", "corrupt", "dimensions", "second"])
def test_invalid_outputs_never_return_partial_result(failure):
    with pytest.raises(ComfyUIError) as error:
        run(failure=failure)
    assert error.value.prompt_id == ("2" if failure == "second" else "1")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"steps": 0},
        {"steps": True},
        {"cfg": float("nan")},
        {"timeout": 0},
        {"sampler": ""},
        {"negative": None},
    ],
)
def test_invalid_parameters(kwargs):
    with pytest.raises(ValueError):
        run(**kwargs)


def test_per_image_prompts_match_workflows_and_snapshots():
    prompts = ["sky", "tree"]
    result, workflows = run(positive_prompts=prompts, negative="rain")
    assert result.parameters["positive"] == "sky"
    for position, workflow in enumerate(workflows):
        saved = result.parameters["image_prompts"][position]
        assert saved == {"position": position, "positive": prompts[position], "negative": "rain"}
        assert workflow["6"]["inputs"]["text"] == saved["positive"]
        assert workflow["7"]["inputs"]["text"] == saved["negative"]


def test_progress_counts_only_validated_images():
    completed = []
    run(count=3, on_progress=completed.append)
    assert completed == [1, 2, 3]
    completed.clear()
    with pytest.raises(ComfyUIError):
        run(count=3, failure="second", on_progress=completed.append)
    assert completed == [1]


def test_generation_awaits_each_tag_before_next_image():
    events = []

    async def tagged(image):
        events.append(("tagged", image.position + 1))

    result, _ = run(
        count=3, on_progress=lambda count: events.append(("generated", count)), on_image=tagged
    )
    assert events == [
        ("generated", 1),
        ("tagged", 1),
        ("generated", 2),
        ("tagged", 2),
        ("generated", 3),
        ("tagged", 3),
    ]
    assert len(result.images) == 3


def test_tag_failure_stops_generating_later_images():
    generated = []

    async def tagged(image):
        if image.position == 1:
            raise ComfyUIError("tag failed")

    with pytest.raises(ComfyUIError, match="tag failed"):
        run(count=3, on_progress=generated.append, on_image=tagged)
    assert generated == [1, 2]


@pytest.mark.parametrize("prompts", [[], ["sky"], ["sky", None], "sky"])
def test_invalid_per_image_prompts_rejected(prompts):
    with pytest.raises(ValueError, match="one positive prompt"):
        run(positive_prompts=prompts)


def test_unaligned_dimensions_rejected():
    with pytest.raises(ValueError):
        run(width=65)


def test_download_size_limit(monkeypatch):
    monkeypatch.setattr("backend.generation.MAX_BYTES", 8)
    with pytest.raises(ComfyUIError, match="exceeds"):
        run()
