"""Project API isolation and persistence across application restarts."""

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.database import Database
from backend.main import create_app


def test_projects_persist_without_unfinished_generations(tmp_path):
    settings = Settings(storage_dir=tmp_path / "data")
    with TestClient(create_app(tmp_path / "missing", settings=settings)) as client:
        assert client.get("/api/projects").json() == []
        first = client.post("/api/projects", json={"name": "  海  "})
        assert first.status_code == 201
        first = first.json()
        second = client.post("/api/projects", json={"name": "山"}).json()
        assert first["name"] == "海"
        assert first["initial_image_path"] is None
        assert first["generation_count"] == 0
        assert first["id"] != second["id"]
        assert first["created_at"] and first["updated_at"]
        with Database(settings.database_path).connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 0
        # Simulate an existing complete generation from a later stage.
        with Database(settings.database_path).transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO generations(project_id, parameters_json) VALUES (?, ?)",
                (first["id"], '{"image_count":1}'),
            )
            connection.execute(
                "INSERT INTO images(generation_id, position, file_path, seed, tags_json) "
                "VALUES (?, 0, 'completed.png', 1, '{}')",
                (cursor.lastrowid,),
            )
    with TestClient(create_app(tmp_path / "missing", settings=settings)) as client:
        projects = client.get("/api/projects").json()
        assert {p["id"] for p in projects} == {first["id"], second["id"]}
        resumed = client.get(f"/api/projects/{first['id']}").json()
        assert resumed["name"] == "海"
        assert resumed["generation_count"] == 1
        assert client.get(f"/api/projects/{second['id']}").json()["generation_count"] == 0
        assert client.get("/api/projects/999999").status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": ""},
        {"name": " \t\n "},
        {"name": "a" * 201},
        {"name": None},
        {"name": 123},
        {"name": "ok", "initial_image_path": "fake"},
    ],
)
def test_invalid_project_does_not_write(tmp_path, payload):
    with TestClient(
        create_app(tmp_path / "missing", settings=Settings(storage_dir=tmp_path))
    ) as client:
        assert client.post("/api/projects", json=payload).status_code == 422
        assert client.get("/api/projects").json() == []
