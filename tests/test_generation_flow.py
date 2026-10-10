import asyncio
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.comfyui import ComfyUIError, ComfyUITimeout
from backend.config import Settings
from backend.generation import GeneratedImage, GenerationResult
from backend.main import create_app
from backend.tagging import TaggingResult


@pytest.fixture
def flow(tmp_path, monkeypatch):
    settings = Settings(storage_dir=tmp_path, image_count=2, width=64, height=96)
    app = create_app(settings=settings)
    stream = io.BytesIO()
    Image.new("RGB", (64, 96)).save(stream, "PNG")
    data = stream.getvalue()
    calls = []

    async def tagging(*args):
        return TaggingResult("tag", {"sky": None, "tree": None})

    async def generating(client, settings, **kwargs):
        calls.append(kwargs)
        seeds = [len(calls) * 10 + i for i in range(2)]
        return GenerationResult(
            {**kwargs, "image_count": 2, "width": 64, "height": 96, "seeds": seeds},
            tuple(GeneratedImage(i, seed, "prompt", data, {}) for i, seed in enumerate(seeds)),
        )

    monkeypatch.setattr("backend.generation_flow.tag_image", tagging)
    monkeypatch.setattr("backend.generation_storage.tag_image", tagging)
    monkeypatch.setattr("backend.generation_flow.generate_images", generating)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "flow"}).json()["id"]
        assert client.put(f"/api/projects/{project}/initial-image", content=data).status_code == 200
        yield client, app.state.database, project, calls


def test_reference_to_two_children_and_immutable_selection(flow):
    client, database, project, calls = flow
    url = f"/api/projects/{project}/generations"
    root = client.post(url, json={"checkpoint": "test-model"})
    assert root.status_code == 201, root.text
    snapshots = client.get(url).json()
    parent = snapshots[0]
    selection = {"liked": [], "disliked": [parent["images"][0]["id"]]}
    child = client.post(url, json={"parent_id": parent["id"], "selection": selection})
    assert child.status_code == 201, child.text
    child_snapshot = client.get(url).json()[-1]
    assert child_snapshot["parameters"]["tag_weights"] == {}
    selection2 = {"liked": [child_snapshot["images"][0]["id"]], "disliked": []}
    grandchild = client.post(url, json={"parent_id": child.json()["id"], "selection": selection2})
    assert grandchild.status_code == 201, grandchild.text
    assert client.get(url).json()[0] == parent
    with database.connect() as connection:
        rows = connection.execute("SELECT * FROM generations ORDER BY id").fetchall()
        assert len(rows) == 3
        assert json.loads(rows[1]["selection_json"]) == selection
        assert json.loads(rows[2]["selection_json"]) == selection2
        parameters = [json.loads(row["parameters_json"]) for row in rows]
        assert parameters[2]["tag_weights"] == {"sky": 0.5, "tree": 0.5}
        assert parameters[2]["inheritance_rate"] == 0.5
        assert len({tuple(p["seeds"]) for p in parameters}) == 3
    assert calls[2]["positive"] == "(sky:0.5), (tree:0.5)"


def test_invalid_selection_and_tag_failure_do_not_save(flow, monkeypatch):
    client, database, project, calls = flow
    url = f"/api/projects/{project}/generations"
    assert client.post(url, json={"selection": {"liked": [1], "disliked": []}}).status_code == 422
    assert not calls

    async def fail(*args):
        raise ComfyUIError("Tagger failed")

    monkeypatch.setattr("backend.generation_storage.tag_image", fail)
    assert client.post(url, json={"checkpoint": "model"}).status_code == 502
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM generations").fetchone()[0] == 0
    monkeypatch.undo()


@pytest.mark.parametrize(
    "error,code",
    [(ComfyUIError("stopped"), 502), (ComfyUITimeout("timeout"), 504), (OSError("disk full"), 500)],
)
def test_failures_preserve_history_and_allow_retry(flow, monkeypatch, error, code):
    client, database, project, calls = flow
    url = f"/api/projects/{project}/generations"
    root = client.post(url, json={"checkpoint": "model"}).json()["id"]
    before = client.get(url).json()
    original = __import__("backend.generation_flow", fromlist=["generate_images"]).generate_images

    async def fail(*args, **kwargs):
        raise error

    body = {
        "parent_id": root,
        "selection": {"liked": [before[0]["images"][0]["id"]], "disliked": []},
    }
    monkeypatch.setattr("backend.generation_flow.generate_images", fail)
    assert client.post(url, json=body).status_code == code
    assert client.get(url).json() == before
    assert client.get(f"/api/projects/{project}/generation-status").json() == {"running": False}
    monkeypatch.setattr("backend.generation_flow.generate_images", original)
    assert client.post(url, json=body).status_code == 201


def test_reload_and_concurrent_submission_observe_one_running_generation(flow, monkeypatch):
    client, database, project, calls = flow
    entered, release = threading.Event(), threading.Event()
    from backend import generation_flow

    original = generation_flow.generate_images

    async def pending(*args, **kwargs):
        entered.set()
        await asyncio.to_thread(release.wait, 5)
        return await original(*args, **kwargs)

    monkeypatch.setattr(generation_flow, "generate_images", pending)
    url = f"/api/projects/{project}/generations"
    with ThreadPoolExecutor() as pool:
        future = pool.submit(client.post, url, json={"checkpoint": "model"})
        try:
            assert entered.wait(5)
            assert client.get(url).json() == []
            assert client.get(url).headers["X-Generation-Running"] == "true"
            assert client.get(f"/api/projects/{project}/generation-status").json()["running"]
            assert client.post(url, json={"checkpoint": "model"}).status_code == 409
        finally:
            release.set()
        assert future.result().status_code == 201
    assert len(client.get(url).json()) == 1
    assert client.get(url).headers["X-Generation-Running"] == "false"
