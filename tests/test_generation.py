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
                Settings(image_count=count, width=width, height=height),
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


def test_unaligned_dimensions_rejected():
    with pytest.raises(ValueError):
        run(width=65)


def test_download_size_limit(monkeypatch):
    monkeypatch.setattr("backend.generation.MAX_BYTES", 8)
    with pytest.raises(ComfyUIError, match="exceeds"):
        run()
