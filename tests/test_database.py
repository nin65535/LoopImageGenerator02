import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.config import Settings, load_settings
from backend.database import Database
from backend.main import create_app


def test_config_defaults_and_relative_paths(tmp_path):
    config = tmp_path / "settings.toml"
    config.write_text(
        'storage_dir = "custom"\nimage_count = 17\nwidth = 768\nheight = 1024\n', encoding="utf-8"
    )
    settings = load_settings(config)
    assert settings.storage_dir == tmp_path / "custom"
    assert (settings.image_count, settings.width, settings.height) == (17, 768, 1024)
    assert settings.comfyui_url == "http://127.0.0.1:8188"


@pytest.mark.parametrize(
    "content",
    [
        "image_count = 0",
        "image_count = 1",
        "image_count = 5",
        "width = -1",
        "height = 0",
        "image_count = true",
        'comfyui_url = "file:///tmp"',
        "unknown = 1",
        'storage_dir = ""',
    ],
)
def test_invalid_config(tmp_path, content):
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises((ValidationError, ValueError)):
        load_settings(path)


def test_explicit_missing_config(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "absent.toml")


def test_minimum_generation_count(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("image_count = 6", encoding="utf-8")
    assert load_settings(path).image_count == 6
    assert Settings().image_count == 10


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path / "nested" / "test.sqlite3")
    db.initialize()
    db.initialize()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, initial_image_path) "
            "VALUES (1, 'test', 'reference.png')"
        )
    return db


def test_variable_count_and_persistence(database):
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO generations (id, project_id, parameters_json) VALUES (1, 1, ?)",
            (json.dumps({"image_count": 17}),),
        )
        for position in range(17):
            conn.execute(
                "INSERT INTO images (generation_id, position, file_path, seed, tags_json) "
                "VALUES (1, ?, ?, ?, ?)",
                (position, f"{position}.png", position, '{"cat":null}'),
            )
    with database.connect() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM images").fetchone()[0] == 17


@pytest.mark.parametrize(
    "parameters", ["invalid", "[]", "{}", '{"image_count":0}', '{"image_count":1.5}']
)
def test_parameters_json_constraints(database, parameters):
    with pytest.raises(sqlite3.DatabaseError), database.transaction() as conn:
        conn.execute(
            "INSERT INTO generations (project_id, parameters_json) VALUES (1, ?)", (parameters,)
        )


@pytest.mark.parametrize(
    "selection", ["invalid", "{}", '{"liked":[]}', '{"liked":[],"disliked":[]}']
)
def test_selection_constraints(database, selection):
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO generations (id, project_id, parameters_json) VALUES (1, 1, ?)",
            ('{"image_count":1}',),
        )
    with pytest.raises(sqlite3.DatabaseError), database.transaction() as conn:
        conn.execute(
            "INSERT INTO generations (project_id, parent_id, selection_json, parameters_json) "
            "VALUES (1, 1, ?, ?)",
            (selection, '{"image_count":1}'),
        )


def test_foreign_keys_and_rollback(database):
    with pytest.raises(sqlite3.IntegrityError), database.transaction() as conn:
        conn.execute(
            "INSERT INTO generations (id, project_id, parameters_json) VALUES (1, 1, ?)",
            ('{"image_count":1}',),
        )
        conn.execute(
            "INSERT INTO images (generation_id, position, file_path, seed, tags_json) "
            "VALUES (999, 0, 'bad.png', 1, '{}')"
        )
    with database.connect() as conn:
        assert conn.execute("SELECT count(*) FROM generations").fetchone()[0] == 0
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, initial_image_path) VALUES (2, 'other', 'other.png')"
        )
        conn.execute(
            "INSERT INTO generations (id, project_id, parameters_json) VALUES (1, 1, ?)",
            ('{"image_count":1}',),
        )
    with pytest.raises(sqlite3.IntegrityError), database.transaction() as conn:
        conn.execute(
            "INSERT INTO generations (project_id, parent_id, selection_json, parameters_json) "
            "VALUES (2, 1, ?, ?)",
            ('{"liked":[1],"disliked":[]}', '{"image_count":1}'),
        )


@pytest.mark.parametrize("tags", ["invalid", "[]"])
def test_tags_constraints(database, tags):
    with pytest.raises(sqlite3.DatabaseError), database.transaction() as conn:
        conn.execute(
            "INSERT INTO generations (id, project_id, parameters_json) VALUES (1, 1, ?)",
            ('{"image_count":1}',),
        )
        conn.execute(
            "INSERT INTO images (generation_id, position, file_path, seed, tags_json) "
            "VALUES (1, 0, 'image.png', 1, ?)",
            (tags,),
        )


def test_startup_initializes_empty_database(tmp_path):
    settings = Settings(storage_dir=tmp_path / "storage")
    app = create_app(tmp_path / "missing", settings=settings)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        with app.state.database.connect() as conn:
            assert {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            } == {"projects", "generations", "images"}
