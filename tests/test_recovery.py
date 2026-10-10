from uuid import uuid4

import pytest

from backend.database import Database
from backend.recovery import recover_storage, storage_lease


def test_recovery_preserves_referenced_and_unknown_files(tmp_path):
    database = Database(tmp_path / "app.sqlite3")
    database.initialize()
    reference = tmp_path / "references" / f"{uuid4().hex}.png"
    reference.parent.mkdir()
    reference.write_bytes(b"saved")
    generation = tmp_path / "generations" / uuid4().hex
    generation.mkdir(parents=True)
    image = generation / "0.png"
    image.write_bytes(b"saved")
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO projects (name, initial_image_path) VALUES (?, ?)",
            ("saved", reference.relative_to(tmp_path).as_posix()),
        )
        connection.execute(
            "INSERT INTO generations (project_id, parameters_json) VALUES (1, ?)",
            ('{"image_count":1}',),
        )
        connection.execute(
            "INSERT INTO images (generation_id, position, file_path, seed, tags_json) "
            "VALUES (1, 0, ?, 1, '{}')",
            (image.relative_to(tmp_path).as_posix(),),
        )
    orphans = []
    for name in ("staging", "generations"):
        path = tmp_path / name / uuid4().hex
        path.mkdir(parents=True)
        (path / "0.png").write_bytes(b"unfinished")
        orphans.append(path)
    for suffix in (".tmp", ".png"):
        path = reference.parent / f"{uuid4().hex}{suffix}"
        path.write_bytes(b"unfinished")
        orphans.append(path)
    unknown = reference.parent / "user.png"
    unknown.write_bytes(b"user")
    with storage_lease(tmp_path):
        recover_storage(database, tmp_path)
        recover_storage(database, tmp_path)
    assert image.read_bytes() == b"saved"
    assert reference.read_bytes() == b"saved"
    assert unknown.read_bytes() == b"user"
    assert not any(path.exists() for path in orphans)
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM images").fetchone()[0] == 1


def test_second_storage_owner_rejected_and_release_allows_restart(tmp_path):
    with storage_lease(tmp_path):
        with pytest.raises(OSError):
            with storage_lease(tmp_path):
                pytest.fail("Second owner accepted")
    with storage_lease(tmp_path):
        pass
