import io

from fastapi.testclient import TestClient
from PIL import Image

from backend.config import Settings
from backend.generation import GeneratedImage, GenerationResult
from backend.generation_storage import save_generation
from backend.main import create_app


def test_generation_listing_images_and_isolation(tmp_path):
    app = create_app(tmp_path / "missing", settings=Settings(storage_dir=tmp_path))
    with TestClient(app) as client:
        first = client.post("/api/projects", json={"name": "one"}).json()["id"]
        second = client.post("/api/projects", json={"name": "two"}).json()["id"]
        assert client.get(f"/api/projects/{first}/generations").json() == []
        assert client.get("/api/projects/999/generations").status_code == 404
        buffer = io.BytesIO()
        Image.new("RGB", (64, 96)).save(buffer, "PNG")
        result = GenerationResult(
            {"image_count": 11, "width": 64, "height": 96, "seeds": list(range(11))},
            tuple(GeneratedImage(i, i, str(i), buffer.getvalue(), {}) for i in range(11)),
        )
        generation = save_generation(app.state.database, tmp_path, first, result, ({},) * 11)
        rows = client.get(f"/api/projects/{first}/generations").json()
        assert len(rows) == 1 and rows[0]["id"] == generation
        assert rows[0]["parameters"] == result.parameters
        assert rows[0]["selection"] is None
        assert [image["position"] for image in rows[0]["images"]] == list(range(11))
        image = rows[0]["images"][0]
        response = client.get(image["url"])
        assert response.content == buffer.getvalue()
        assert response.headers["content-type"] == "image/png"
        assert client.get(f"/api/projects/{second}/generations").json() == []
        assert client.get(f"/api/projects/{second}/images/{image['id']}").status_code == 404
        assert client.get(f"/api/projects/{first}/images/999").status_code == 404
        with app.state.database.transaction() as connection:
            connection.execute(
                "UPDATE images SET file_path = '../outside.png' WHERE id = ?", (image["id"],)
            )
        assert client.get(image["url"]).status_code == 404

        with app.state.database.transaction() as connection:
            connection.execute(
                "UPDATE images SET file_path = 'generations/missing.png' WHERE id = ?",
                (image["id"],),
            )
        assert client.get(image["url"]).status_code == 404


def test_both_branch_snapshots_survive_restart(tmp_path):
    settings = Settings(storage_dir=tmp_path)
    app = create_app(settings=settings)
    buffer = io.BytesIO()
    Image.new("RGB", (64, 96)).save(buffer, "PNG")
    result = GenerationResult(
        {"image_count": 1, "width": 64, "height": 96, "seeds": [1]},
        (GeneratedImage(0, 1, "prompt", buffer.getvalue(), {}),),
    )
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "tree"}).json()["id"]
        root = save_generation(app.state.database, tmp_path, project, result, ({"sky": None},))
        url = f"/api/projects/{project}/generations"
        initial = client.get(url).json()[0]
        image_id = initial["images"][0]["id"]
        for choice in ("liked", "disliked"):
            selection = {"liked": [], "disliked": []}
            selection[choice] = [image_id]
            save_generation(
                app.state.database,
                tmp_path,
                project,
                result,
                ({},),
                parent_id=root,
                selection=selection,
            )
        before = client.get(url).json()
        assert before[0] == initial
        assert before[1]["selection"] == {"liked": [image_id], "disliked": []}
        assert before[2]["selection"] == {"liked": [], "disliked": [image_id]}
        assert before[1]["parent_id"] == before[2]["parent_id"] == root
    with TestClient(create_app(settings=settings)) as restarted:
        assert restarted.get(url).json() == before
