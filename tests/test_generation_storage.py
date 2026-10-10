import asyncio
import io
import json
from dataclasses import replace

import pytest
from PIL import Image

from backend.database import Database
from backend.generation import GeneratedImage, GenerationResult
from backend.generation_storage import save_generation, tag_and_save_generation
from backend.tagging import TaggingResult


@pytest.fixture
def setup(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        connection.execute("INSERT INTO projects (name, initial_image_path) VALUES ('one', '')")
        connection.execute("INSERT INTO projects (name, initial_image_path) VALUES ('two', '')")
    buffer = io.BytesIO()
    Image.new("RGB", (64, 96)).save(buffer, format="PNG")
    images = tuple(GeneratedImage(i, i + 1, str(i), buffer.getvalue(), {}) for i in range(3))
    result = GenerationResult(
        {"image_count": 3, "width": 64, "height": 96, "seeds": [1, 2, 3]}, images
    )
    return database, tmp_path, result


def assert_empty(database, storage):
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM generations").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM images").fetchone()[0] == 0
    assert not list((storage / "generations").glob("*"))
    assert not list((storage / "staging").glob("*"))


def test_root_and_branches_preserve_snapshots(setup):
    database, storage, result = setup
    root = save_generation(database, storage, 1, result, ({"sky": None}, {}, {"solo": None}))
    with database.connect() as connection:
        rows = connection.execute("SELECT * FROM images ORDER BY position").fetchall()
        parent = dict(connection.execute("SELECT * FROM generations").fetchone())
    for row, image in zip(rows, result.images, strict=True):
        assert (storage / row["file_path"]).read_bytes() == image.data
        assert row["seed"] == image.seed
    selection = {"liked": [], "disliked": [rows[0]["id"]]}
    for _ in range(2):
        child = save_generation(
            database, storage, 1, result, ({}, {}, {}), parent_id=root, selection=selection
        )
        with database.connect() as connection:
            row = connection.execute("SELECT * FROM generations WHERE id = ?", (child,)).fetchone()
            assert json.loads(row["selection_json"]) == selection
            assert json.loads(row["parameters_json"]) == result.parameters
            assert (
                dict(
                    connection.execute("SELECT * FROM generations WHERE id = ?", (root,)).fetchone()
                )
                == parent
            )
    assert len(list((storage / "generations").glob("*/*"))) == 9


@pytest.mark.parametrize("failure", ["count", "tags", "positions", "seed", "corrupt"])
def test_invalid_complete_results_do_not_write(setup, failure):
    database, storage, result = setup
    tags = ({}, {}, {})
    if failure == "count":
        result = replace(result, images=result.images[:-1])
    elif failure == "tags":
        tags = ({}, {})
    else:
        changes = {
            "positions": {"position": 9},
            "seed": {"seed": True},
            "corrupt": {"data": b"bad"},
        }
        result = replace(
            result, images=(replace(result.images[0], **changes[failure]), *result.images[1:])
        )
    with pytest.raises(Exception):
        save_generation(database, storage, 1, result, tags)
    assert_empty(database, storage)


@pytest.mark.parametrize(
    "selection",
    [
        {"liked": [], "disliked": []},
        {"liked": [1, 1], "disliked": []},
        {"liked": [1], "disliked": [1]},
        {"liked": [True], "disliked": []},
        {"liked": [999], "disliked": []},
    ],
)
def test_invalid_parent_selection(setup, selection):
    database, storage, result = setup
    root = save_generation(database, storage, 1, result, ({}, {}, {}))
    with pytest.raises(ValueError):
        save_generation(
            database, storage, 1, result, ({}, {}, {}), parent_id=root, selection=selection
        )
    with pytest.raises(ValueError):
        save_generation(
            database,
            storage,
            2,
            result,
            ({}, {}, {}),
            parent_id=root,
            selection={"liked": [1], "disliked": []},
        )
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM generations").fetchone()[0] == 1
    assert len(list((storage / "generations").glob("*/*"))) == 3


@pytest.mark.parametrize("failure", ["write", "rename", "insert", "commit"])
def test_storage_and_database_failures_cleanup(setup, monkeypatch, failure):
    database, storage, result = setup
    if failure == "write":
        original_open = type(storage).open

        def fail(path, *args, **kwargs):
            if path.name == "1.png" and "staging" in path.parts:
                raise OSError("write failed")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(type(storage), "open", fail)
    elif failure == "rename":

        def fail(*args):
            raise OSError("rename failed")

        monkeypatch.setattr(type(storage), "rename", fail)
    elif failure == "insert":
        with database.connect() as connection:
            connection.execute(
                "CREATE TRIGGER reject_image BEFORE INSERT ON images WHEN NEW.position = 1 "
                "BEGIN SELECT RAISE(ABORT, 'injected'); END"
            )
    else:
        # Deferred FK failure occurs on commit, after file publication.
        with database.connect() as connection:
            connection.executescript(
                "CREATE TABLE bad (id INTEGER REFERENCES projects(id) "
                "DEFERRABLE INITIALLY DEFERRED); "
                "CREATE TRIGGER reject_commit AFTER INSERT ON generations "
                "BEGIN INSERT INTO bad VALUES (999); END;"
            )
    with pytest.raises(Exception):
        save_generation(database, storage, 1, result, ({}, {}, {}))
    assert_empty(database, storage)


@pytest.mark.parametrize("fail_at", [None, 2])
def test_all_images_tagged_before_save(setup, monkeypatch, fail_at):
    database, storage, result = setup
    calls = []

    async def tag(client, data):
        calls.append(data)
        assert_empty(database, storage)
        if len(calls) == fail_at:
            raise RuntimeError("tagging failed")
        return TaggingResult("tag", {"sky": None})

    monkeypatch.setattr("backend.generation_storage.tag_image", tag)
    operation = tag_and_save_generation(None, database, storage, 1, result)
    if fail_at:
        with pytest.raises(RuntimeError):
            asyncio.run(operation)
        assert_empty(database, storage)
    else:
        assert asyncio.run(operation) == 1
        assert len(calls) == 3


def test_more_than_ten_images(setup):
    database, storage, result = setup
    images = tuple(replace(result.images[0], position=i, seed=i) for i in range(11))
    result = GenerationResult(
        {**result.parameters, "image_count": 11, "seeds": list(range(11))}, images
    )
    save_generation(database, storage, 1, result, tuple({} for _ in images))
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM images").fetchone()[0] == 11
    assert len(list((storage / "generations").glob("*/*"))) == 11


def test_cancel_during_tagging_leaves_no_partial_data(setup, monkeypatch):
    database, storage, result = setup

    async def tag(client, data):
        raise asyncio.CancelledError

    monkeypatch.setattr("backend.generation_storage.tag_image", tag)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(tag_and_save_generation(None, database, storage, 1, result))
    assert_empty(database, storage)
