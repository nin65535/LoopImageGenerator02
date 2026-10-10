import io
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.config import Settings
from backend.main import create_app


def image_bytes(format="PNG"):
    stream = io.BytesIO()
    Image.new("RGB", (12, 8), "red").save(stream, format=format)
    return stream.getvalue()


@pytest.mark.parametrize("format", ["PNG", "JPEG", "WEBP"])
def test_upload_persists_and_isolated(tmp_path, format):
    settings = Settings(storage_dir=tmp_path)
    app = create_app(tmp_path / "missing", settings=settings)
    with TestClient(app) as client:
        first = client.post("/api/projects", json={"name": "first"}).json()["id"]
        second = client.post("/api/projects", json={"name": "second"}).json()["id"]
        url = f"/api/projects/{first}/initial-image"
        data = image_bytes(format)
        result = client.put(url, content=data, headers={"Content-Type": "text/plain"})
        assert result.status_code == 200
        path = result.json()["initial_image_path"]
        assert path.startswith("references/")
        assert (tmp_path / path).read_bytes() == data
        assert client.put(url, content=data).status_code == 409
        assert client.get(f"/api/projects/{second}").json()["initial_image_path"] is None
        assert client.get(f"/api/projects/{second}/initial-image").status_code == 404
        with app.state.database.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 0
    with TestClient(create_app(tmp_path / "missing", settings=settings)) as client:
        assert client.get(url).content == data
        assert client.get(f"/api/projects/{first}").json()["initial_image_path"] == path


@pytest.mark.parametrize(
    "data,status",
    [(b"", 422), (b"fake.png", 422), (image_bytes("GIF"), 415), (image_bytes()[:-20], 422)],
)
def test_invalid_upload_leaves_no_records_or_files(tmp_path, data, status):
    app = create_app(tmp_path / "missing", settings=Settings(storage_dir=tmp_path))
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"name": "test"}).json()["id"]
        assert (
            client.put(f"/api/projects/{project_id}/initial-image", content=data).status_code
            == status
        )
        assert client.get(f"/api/projects/{project_id}").json()["initial_image_path"] is None
        assert not list((tmp_path / "references").glob("*"))


def test_limits_missing_project_and_storage_failure(tmp_path):
    app = create_app(tmp_path / "missing", settings=Settings(storage_dir=tmp_path))
    with TestClient(app) as client:
        project_id = client.post("/api/projects", json={"name": "test"}).json()["id"]
        url = f"/api/projects/{project_id}/initial-image"
        assert (
            client.put("/api/projects/999/initial-image", content=image_bytes()).status_code == 404
        )
        with patch("backend.reference_images.MAX_BYTES", 10):
            assert client.put(url, content=image_bytes()).status_code == 413
        with patch("backend.reference_images.MAX_PIXELS", 10):
            assert client.put(url, content=image_bytes()).status_code == 413
        with patch("pathlib.Path.replace", side_effect=OSError("disk failure")):
            assert client.put(url, content=image_bytes()).status_code == 500
        assert client.get(f"/api/projects/{project_id}").json()["initial_image_path"] is None
        assert not list((tmp_path / "references").glob("*"))
        assert client.put(url, content=image_bytes()).status_code == 200
