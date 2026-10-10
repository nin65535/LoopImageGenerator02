import asyncio
import json

import httpx
import pytest

from backend.comfyui import ComfyUIClient, ComfyUIError, ComfyUITimeout, load_workflow

WORKFLOW = {"1": {"class_type": "PreviewImage", "inputs": {"images": ["2", 0]}}}


def execute(handler, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await ComfyUIClient(http, "http://comfy/base").execute(
                WORKFLOW, poll_interval=0.001, **kwargs
            )

    return asyncio.run(run())


def test_submit_poll_and_preserve_outputs():
    requests = []
    outputs = {"1": {"images": [{"filename": "preview.png", "type": "temp"}]}}

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            assert json.loads(request.content)["prompt"] == WORKFLOW
            assert json.loads(request.content)["client_id"]
            return httpx.Response(200, json={"prompt_id": "id"})
        assert request.url.path == "/base/history/id"
        if len(requests) == 2:
            return httpx.Response(200, json={"another-id": {}})
        return httpx.Response(
            200,
            json={
                "id": {
                    "status": {"completed": True, "status_str": "success"},
                    "outputs": outputs,
                }
            },
        )

    result = execute(handler)
    assert result.prompt_id == "id"
    assert result.outputs == outputs
    assert len(requests) == 3


@pytest.mark.parametrize("message", ["execution_error", "execution_interrupted"])
def test_execution_failure_even_with_partial_outputs(message):
    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"prompt_id": "id"})
        return httpx.Response(
            200,
            json={
                "id": {
                    "status": {
                        "completed": False,
                        "status_str": "error",
                        "messages": [[message, {"node_id": "1"}]],
                    },
                    "outputs": {"partial": {}},
                }
            },
        )

    with pytest.raises(ComfyUIError) as error:
        execute(handler)
    assert error.value.prompt_id == "id"
    assert error.value.details["outputs"] == {"partial": {}}


@pytest.mark.parametrize("payload", [{}, [], {"prompt_id": ""}])
def test_invalid_submission(payload):
    with pytest.raises(ComfyUIError):
        execute(lambda request: httpx.Response(200, json=payload))


def test_rejected_prompt_keeps_node_errors_and_does_not_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"error": "invalid", "node_errors": {"1": {}}})

    with pytest.raises(ComfyUIError) as error:
        execute(handler)
    assert error.value.details["node_errors"] == {"1": {}}
    assert len(calls) == 1


@pytest.mark.parametrize("exception", [httpx.ConnectError, httpx.ReadTimeout])
def test_transport_failure(exception):
    def handler(request):
        raise exception("offline", request=request)

    with pytest.raises(ComfyUIError):
        execute(handler)


def test_invalid_json():
    with pytest.raises(ComfyUIError, match="invalid JSON"):
        execute(lambda request: httpx.Response(502, text="bad gateway"))


def test_total_timeout_preserves_prompt_id():
    def handler(request):
        return httpx.Response(200, json={"prompt_id": "id"} if request.method == "POST" else {})

    with pytest.raises(ComfyUITimeout) as error:
        execute(handler, timeout=0.02)
    assert error.value.prompt_id == "id"


@pytest.mark.parametrize(
    "record",
    [
        None,
        {},
        {"status": {"completed": True}},
        {"status": {"completed": True, "status_str": "success"}, "outputs": []},
    ],
)
def test_malformed_history(record):
    def handler(request):
        return httpx.Response(
            200, json={"prompt_id": "id"} if request.method == "POST" else {"id": record}
        )

    with pytest.raises(ComfyUIError):
        execute(handler)


def test_workflow_loading(tmp_path):
    path = tmp_path / "api.json"
    path.write_text(json.dumps(WORKFLOW), encoding="utf-8-sig")
    assert load_workflow(path) == WORKFLOW
    for content in ["bad json", "{}", '{"nodes":[]}', '{"1":{"class_type":"X"}}']:
        path.write_text(content, encoding="utf-8")
        with pytest.raises(ComfyUIError):
            load_workflow(path)
    with pytest.raises(ComfyUIError):
        load_workflow(tmp_path / "missing")


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True])
def test_invalid_timeouts(timeout):
    with pytest.raises(ValueError):
        execute(lambda request: pytest.fail("Must not submit"), timeout=timeout)


def test_pending_status_does_not_return_partial_outputs():
    polls = 0

    def handler(request):
        nonlocal polls
        if request.method == "POST":
            return httpx.Response(200, json={"prompt_id": "id"})
        polls += 1
        return httpx.Response(
            200,
            json={
                "id": {
                    "status": {"completed": polls > 1, "status_str": "success"},
                    "outputs": {},
                }
            },
        )

    assert execute(handler).outputs == {}
    assert polls == 2


def test_cancelled_caller_stops_polling():
    async def run():
        entered = asyncio.Event()

        async def handler(request):
            if request.method == "POST":
                return httpx.Response(200, json={"prompt_id": "id"})
            entered.set()
            await asyncio.Event().wait()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            task = asyncio.create_task(ComfyUIClient(http, "http://comfy").execute(WORKFLOW))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run())
