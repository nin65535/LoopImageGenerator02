import asyncio
import io
import json

import httpx
import pytest
from fastapi import HTTPException
from PIL import Image

from backend.comfyui import ComfyUIClient, ComfyUIError, ComfyUITimeout
from backend.tagging import parse_tags, tag_image


def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.parametrize(
    "text,expected",
    [
        ("solo, red_hair, solo, ", {"solo": None, "red_hair": None}),
        ("  , ", {}),
        ("character\\(name\\)", {"character\\(name\\)": None}),
    ],
)
def test_parse_tags(text, expected):
    assert parse_tags({"2": {"tags": [text]}}) == expected
    assert json.loads(json.dumps(expected)) == expected


@pytest.mark.parametrize(
    "outputs",
    [
        {},
        {"3": {"tags": ["solo"]}},
        {"2": {}},
        {"2": {"tags": None}},
        {"2": {"tags": "solo"}},
        {"2": {"tags": []}},
        {"2": {"tags": ["solo", "cat"]}},
        {"2": {"tags": [12]}},
    ],
)
def test_missing_or_invalid_tags(outputs):
    with pytest.raises(ComfyUIError):
        parse_tags(outputs)


def run(handler, data=None, **kwargs):
    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await tag_image(
                ComfyUIClient(http, "http://comfy"),
                image_bytes() if data is None else data,
                **kwargs,
            )

    return asyncio.run(execute())


@pytest.mark.parametrize("tags", [["solo, red_hair"], [""], None])
def test_upload_execute_and_read_history(tags):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/upload/image":
            assert "multipart/form-data" in request.headers["content-type"]
            assert image_bytes() in request.content
            return httpx.Response(
                200, json={"name": "unique.png", "subfolder": "", "type": "input"}
            )
        if request.url.path == "/prompt":
            workflow = json.loads(request.content)["prompt"]
            assert workflow["1"]["inputs"]["image"] == "unique.png"
            assert workflow["2"]["class_type"] == "WD14Tagger|pysssss"
            assert workflow["2"]["inputs"]["model"] == "installed-model"
            assert all("Save" not in node["class_type"] for node in workflow.values())
            return httpx.Response(200, json={"prompt_id": "tag-id"})
        return httpx.Response(
            200,
            json={
                "tag-id": {
                    "status": {"completed": True, "status_str": "success"},
                    "outputs": {"2": {"tags": tags}},
                }
            },
        )

    if tags is None:
        with pytest.raises(ComfyUIError) as error:
            run(handler, model="installed-model")
        assert error.value.prompt_id == "tag-id"
    else:
        result = run(handler, model="installed-model")
        assert result.tags == ({"solo": None, "red_hair": None} if tags[0] else {})
        assert result.prompt_id == "tag-id"
    assert calls == ["/upload/image", "/prompt", "/history/tag-id"]


@pytest.mark.parametrize("payload", [{}, {"name": "../bad", "subfolder": "", "type": "input"}])
def test_invalid_upload_does_not_submit(payload):
    def handler(request):
        assert request.url.path == "/upload/image"
        return httpx.Response(200, json=payload)

    with pytest.raises(ComfyUIError):
        run(handler)


def test_corrupt_image_never_uploaded():
    def handler(request):
        pytest.fail("Invalid image was uploaded")

    with pytest.raises(HTTPException):
        run(handler, data=b"broken")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"threshold": -1},
        {"threshold": float("nan")},
        {"character_threshold": 2},
        {"model": ""},
        {"timeout": 0},
    ],
)
def test_invalid_options(kwargs):
    with pytest.raises(ValueError):
        run(lambda request: pytest.fail("Unexpected upload"), **kwargs)


def test_upload_error():
    with pytest.raises(ComfyUIError):
        run(lambda request: httpx.Response(500, json={"error": "upload failed"}))


def test_upload_timeout():
    async def handler(request):
        await asyncio.sleep(1)

    with pytest.raises(ComfyUITimeout):
        run(handler, timeout=0.01)


def test_execution_timeout_keeps_prompt_id():
    def handler(request):
        if request.url.path == "/upload/image":
            return httpx.Response(200, json={"name": "x.png", "subfolder": "", "type": "input"})
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "waiting"})
        return httpx.Response(200, json={})

    with pytest.raises(ComfyUITimeout) as error:
        run(handler, timeout=0.02)
    assert error.value.prompt_id == "waiting"
