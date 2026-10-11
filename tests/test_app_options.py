"""Settings persistence, project snapshots and generation configuration boundaries."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app_options import MODEL_CATALOG, OptionsStore
from backend.config import Settings
from backend.database import Database
from backend.main import create_app


@pytest.fixture
def configured(tmp_path, monkeypatch):
    settings = Settings(storage_dir=tmp_path)

    async def models(*args):
        return list(MODEL_CATALOG)

    monkeypatch.setattr("backend.app_options.installed_models", models)
    monkeypatch.setattr("backend.projects.installed_models", models)
    monkeypatch.setattr("backend.generation_flow.installed_models", models)
    with TestClient(create_app(tmp_path / "missing", settings=settings)) as client:
        yield client, settings


def test_settings_persist_and_project_choices_are_snapshotted(configured):
    client, settings = configured
    defaults = client.get("/api/settings").json()
    assert [(s["width"], s["height"]) for s in defaults["fixed_sizes"]] == [
        (1024, 1024),
        (768, 1344),
        (1344, 768),
    ]
    assert len(defaults["model_whitelist"]) == 3
    assert client.get("/api/settings/models").json()["models"] == list(MODEL_CATALOG)
    saved = {"model_whitelist": [MODEL_CATALOG[1]], "extra_sizes": [{"width": 640, "height": 960}]}
    assert client.put("/api/settings", json=saved).status_code == 200
    assert OptionsStore(settings.storage_dir).read().model_whitelist == saved["model_whitelist"]
    config = {"checkpoint": MODEL_CATALOG[1], "width": 640, "height": 960}
    created = client.post("/api/projects", json={"name": "custom", "generation_config": config})
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    assert client.get(f"/api/projects/{project_id}").json()["generation_config"] == config
    # Removing an option affects future choices, not the stored project.
    assert (
        client.put("/api/settings", json={"model_whitelist": [], "extra_sizes": []}).status_code
        == 200
    )
    assert client.get(f"/api/projects/{project_id}").json()["generation_config"] == config
    assert (
        client.post("/api/projects", json={"name": "bad", "generation_config": config}).status_code
        == 422
    )
    with Database(settings.database_path).connect() as connection:
        assert connection.execute("SELECT count(*) FROM generations").fetchone()[0] == 0


@pytest.mark.parametrize(
    "body",
    [
        {"model_whitelist": ["video.safetensors"], "extra_sizes": []},
        {"model_whitelist": [MODEL_CATALOG[0], MODEL_CATALOG[0]], "extra_sizes": []},
        {"model_whitelist": [], "extra_sizes": [{"width": 786, "height": 1344}]},
        {"model_whitelist": [], "extra_sizes": [{"width": True, "height": 1024}]},
        {"model_whitelist": [], "extra_sizes": [{"width": 1024, "height": 1024}]},
        {"model_whitelist": [], "extra_sizes": [{"width": 640, "height": 960}] * 2},
    ],
)
def test_invalid_settings_are_not_written(configured, body):
    client, settings = configured
    before = client.get("/api/settings").json()
    assert client.put("/api/settings", json=body).status_code == 422
    assert client.get("/api/settings").json() == before
    assert not OptionsStore(settings.storage_dir).path.exists()


def test_models_missing_or_offline_do_not_create_projects(configured, monkeypatch):
    from fastapi import HTTPException

    client, settings = configured
    config = {"checkpoint": MODEL_CATALOG[0], "width": 1024, "height": 1024}

    async def missing(*args):
        return []

    monkeypatch.setattr("backend.projects.installed_models", missing)
    assert (
        client.post("/api/projects", json={"name": "bad", "generation_config": config}).status_code
        == 422
    )

    async def offline(*args):
        raise HTTPException(502, "offline")

    monkeypatch.setattr("backend.projects.installed_models", offline)
    assert (
        client.post("/api/projects", json={"name": "bad", "generation_config": config}).status_code
        == 502
    )
    assert client.get("/api/projects").json() == []
    assert not OptionsStore(settings.storage_dir).path.exists()


def test_existing_database_migrates_without_losing_history(tmp_path):
    database = Database(tmp_path / "legacy.sqlite3")
    schema = (__import__("backend.database", fromlist=["SCHEMA"]).SCHEMA).read_text(
        encoding="utf-8"
    )
    start = schema.index("    generation_config_json TEXT CHECK (")
    end = schema.index("    created_at", start)
    legacy = schema[:start] + schema[end:]
    with sqlite3.connect(database.path) as connection:
        connection.executescript(legacy)
        connection.execute("INSERT INTO projects(name, initial_image_path) VALUES ('legacy', '')")
        connection.execute(
            "INSERT INTO generations(project_id, parameters_json) VALUES (1, ?)",
            (json.dumps({"image_count": 1}),),
        )
    database.initialize()
    database.initialize()
    with database.connect() as connection:
        row = connection.execute("SELECT * FROM projects").fetchone()
        assert row["name"] == "legacy" and row["generation_config_json"] is None
        assert connection.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 1
