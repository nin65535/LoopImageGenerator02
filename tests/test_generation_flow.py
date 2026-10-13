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
from backend.generation_flow import initial_prompts, prompt
from backend.main import create_app
from backend.tagging import TaggingResult


@pytest.fixture
def flow(tmp_path, monkeypatch, request):
    # Small in-memory fixtures bypass configuration validation to keep API tests focused.
    settings = Settings(storage_dir=tmp_path, width=64, height=96).model_copy(
        update={"image_count": getattr(request, "param", 2)}
    )
    app = create_app(settings=settings)
    stream = io.BytesIO()
    Image.new("RGB", (64, 96)).save(stream, "PNG")
    data = stream.getvalue()
    calls = []

    async def tagging(*args):
        return TaggingResult("tag", {"sky": None, "tree": None})

    async def generating(client, settings, **kwargs):
        on_progress = kwargs.pop("on_progress", None)
        on_image = kwargs.pop("on_image", None)
        calls.append({**kwargs, "width": settings.width, "height": settings.height})
        seeds = [len(calls) * 100 + i for i in range(settings.image_count)]
        result = GenerationResult(
            {
                **kwargs,
                "image_count": settings.image_count,
                "width": 64,
                "height": 96,
                "seeds": seeds,
            },
            tuple(GeneratedImage(i, seed, "prompt", data, {}) for i, seed in enumerate(seeds)),
        )
        for image in result.images:
            if on_progress:
                on_progress(image.position + 1)
            if on_image:
                await on_image(image)
        return result

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
    assert len(calls[0]["positive_prompts"]) == 2
    assert calls[0]["positive_prompts"][0] == "(sky:1), (tree:1)"
    assert calls[0]["positive_prompts"][1] in {"(sky:1)", "(tree:1)"}
    assert calls[1]["positive_prompts"] == ["", ""]
    assert calls[2]["positive_prompts"][0] == calls[2]["positive"]
    assert calls[2]["positive_prompts"][1] in {"(sky:0.5)", "(tree:0.5)"}


@pytest.mark.parametrize("count", [6, 10, 13])
def test_initial_dropout_retains_only_reference_tags(count):
    weights = {f"tag_{index}": 1.0 for index in range(100)}
    original = dict(weights)
    candidates = initial_prompts(weights, count)
    allowed = set(prompt(weights, True).split(", "))
    assert len(candidates) == count
    sizes = []
    for candidate in candidates:
        retained = set(candidate.split(", "))
        assert retained <= allowed
        sizes.append(len(retained))
    assert candidates[0] == prompt(weights, True)
    assert sizes[0] == 100
    assert sizes[1] == 80
    assert sizes[-1] == 40
    assert weights == original


def test_initial_dropout_empty_and_single_tag():
    assert initial_prompts({}, 2) == ["", ""]
    assert initial_prompts({"solo": 1.0}, 2) == ["(solo:1)", "(solo:1)"]


@pytest.mark.parametrize("flow", [6], indirect=True)
def test_six_initial_candidates_include_all_tags(flow):
    client, database, project, calls = flow
    url = f"/api/projects/{project}/generations"
    assert client.post(url, json={"checkpoint": "model"}).status_code == 201
    generation = client.get(url).json()[0]
    assert len(generation["images"]) == generation["parameters"]["image_count"] == 6
    assert calls[0]["positive_prompts"][0] == calls[0]["positive"]
    assert all(value in {"(sky:1)", "(tree:1)"} for value in calls[0]["positive_prompts"][1:])


@pytest.mark.parametrize("flow", [6], indirect=True)
def test_liked_images_carried_with_new_ids_and_can_be_selected_again(flow):
    client, database, project, calls = flow
    url = f"/api/projects/{project}/generations"
    assert client.post(url, json={"checkpoint": "model"}).status_code == 201
    root = client.get(url).json()[0]
    liked = root["images"][:2]
    selection = {"liked": [image["id"] for image in reversed(liked)], "disliked": []}
    response = client.post(url, json={"parent_id": root["id"], "selection": selection})
    assert response.status_code == 201
    child = client.get(url).json()[-1]
    assert child["parameters"]["image_count"] == len(child["images"]) == 8
    assert child["parameters"]["new_image_count"] == 6
    assert len(calls[1]["positive_prompts"]) == 6
    assert calls[1]["positive_prompts"][0] == calls[1]["positive"]
    assert calls[1]["positive_prompts"][1] != calls[1]["positive"]
    for source, copied in zip(liked, child["images"][6:], strict=True):
        assert copied["id"] != source["id"]
        assert (copied["seed"], copied["tags"]) == (source["seed"], source["tags"])
        assert client.get(copied["url"]).content == client.get(source["url"]).content
    assert child["parameters"]["carried_images"] == [
        {"position": 6 + index, "source_image_id": source["id"], "source_generation_id": root["id"]}
        for index, source in enumerate(liked)
    ]
    assert client.get(url).json()[0] == root
    copied = child["images"][-1]
    assert (
        client.post(
            url,
            json={"parent_id": child["id"], "selection": {"liked": [copied["id"]], "disliked": []}},
        ).status_code
        == 201
    )
    grandchild = client.get(url).json()[-1]
    assert len(grandchild["images"]) == 7
    assert client.get(grandchild["images"][-1]["url"]).content == client.get(copied["url"]).content


def test_dropout_keeps_negative_conditions_out_of_positive_candidates():
    weights = {"sky": 0.5, "tree": 0.25, "rain": -1.0}
    candidates = initial_prompts(weights, 6)
    assert candidates[0] == "(sky:0.5), (tree:0.25)"
    assert all("rain" not in value for value in candidates)
    assert all(value in {"(sky:0.5)", "(tree:0.25)"} for value in candidates[1:])


def test_missing_carried_image_rejects_without_creating_a_child(flow):
    client, database, project, calls = flow
    url = f"/api/projects/{project}/generations"
    assert client.post(url, json={"checkpoint": "model"}).status_code == 201
    root = client.get(url).json()[0]
    source = root["images"][0]
    with database.connect() as connection:
        relative = connection.execute(
            "SELECT file_path FROM images WHERE id = ?", (source["id"],)
        ).fetchone()[0]
    (database.path.parent / relative).unlink()
    response = client.post(
        url, json={"parent_id": root["id"], "selection": {"liked": [source["id"]], "disliked": []}}
    )
    assert response.status_code == 409
    assert len(calls) == 1
    assert client.get(url).json() == [root]
    assert client.get(f"/api/projects/{project}/generation-status").json() == {"running": False}


def test_invalid_selection_and_tag_failure_do_not_save(flow, monkeypatch):
    client, database, project, calls = flow
    url = f"/api/projects/{project}/generations"
    assert client.post(url, json={"selection": {"liked": [1], "disliked": []}}).status_code == 422
    assert not calls

    async def fail(*args):
        raise ComfyUIError("Tagger failed")

    monkeypatch.setattr("backend.generation_flow.tag_image", fail)
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
        kwargs["on_progress"](1)
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
            status = client.get(f"/api/projects/{project}/generation-status").json()
            assert status.pop("elapsed_seconds") >= 0
            assert status == {
                "running": True,
                "percent": 0,
                "completed": 0,
                "total": 2,
                "stage": "tagging",
                "generated": 1,
                "tagged": 0,
                "image_count": 2,
            }
            assert client.post(url, json={"checkpoint": "model"}).status_code == 409
        finally:
            release.set()
        assert future.result().status_code == 201
    assert len(client.get(url).json()) == 1
    assert client.get(url).headers["X-Generation-Running"] == "false"


def test_configured_project_uses_saved_model_and_size_for_root_and_child(flow, monkeypatch):
    client, database, project, calls = flow
    config = {"checkpoint": "chosen-model", "width": 768, "height": 1344}
    with database.transaction() as connection:
        connection.execute(
            "UPDATE projects SET generation_config_json = ? WHERE id = ?",
            (json.dumps(config), project),
        )

    async def models(*args):
        return ["chosen-model"]

    monkeypatch.setattr("backend.generation_flow.installed_models", models)
    url = f"/api/projects/{project}/generations"
    assert client.post(url, json={"checkpoint": "another-model"}).status_code == 422
    assert not calls
    root = client.post(url, json={})
    assert root.status_code == 201, root.text
    image = client.get(url).json()[0]["images"][0]["id"]
    child = client.post(
        url, json={"parent_id": root.json()["id"], "selection": {"liked": [image], "disliked": []}}
    )
    assert child.status_code == 201, child.text
    assert all(
        (call["checkpoint"], call["width"], call["height"]) == ("chosen-model", 768, 1344)
        for call in calls
    )


def test_pair_progress_and_elapsed_during_second_tag_without_partial_save(flow, monkeypatch):
    client, database, project, calls = flow
    entered, release = threading.Event(), threading.Event()
    tag_calls = []

    async def tagging(*args):
        tag_calls.append(1)
        if len(tag_calls) == 3:  # Reference, first candidate, second candidate.
            entered.set()
            await asyncio.to_thread(release.wait, 5)
            raise ComfyUIError("second tag failed")
        return TaggingResult("tag", {"sky": None})

    monkeypatch.setattr("backend.generation_flow.tag_image", tagging)
    url = f"/api/projects/{project}/generations"
    with ThreadPoolExecutor() as pool:
        future = pool.submit(client.post, url, json={"checkpoint": "model"})
        try:
            assert entered.wait(5)
            status = client.get(f"/api/projects/{project}/generation-status").json()
            assert status["percent"] == 50
            assert status["completed"] == status["tagged"] == 1
            assert status["generated"] == status["total"] == 2
            assert status["stage"] == "tagging"
            assert isinstance(status["elapsed_seconds"], int)
            assert status["elapsed_seconds"] >= 0
            assert client.get(url).json() == []
        finally:
            release.set()
        assert future.result().status_code == 502
    assert client.get(url).json() == []
    assert client.get(f"/api/projects/{project}/generation-status").json() == {"running": False}
