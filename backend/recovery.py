"""Recover only app-owned orphan files while exclusively owning the storage."""

import logging
import os
import re
import shutil
from contextlib import contextmanager
from pathlib import Path

from backend.database import Database

logger = logging.getLogger("uvicorn.error")
TOKEN = re.compile(r"[0-9a-f]{32}")


@contextmanager
def storage_lease(storage: Path):
    storage.mkdir(parents=True, exist_ok=True)
    with (storage / ".storage.lock").open("a+b") as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def recover_storage(database: Database, storage: Path) -> None:
    """Called before requests are accepted, under storage_lease. Never edit DB rows."""
    with database.connect() as connection:
        paths = {row[0] for row in connection.execute("SELECT file_path FROM images")}
        paths.update(
            row[0]
            for row in connection.execute("SELECT initial_image_path FROM projects")
            if row[0]
        )
    used = {(storage / path).resolve() for path in paths}
    protected = used | {parent for path in used for parent in path.parents}
    for name in ("staging", "generations", "references"):
        root = storage / name
        if not root.is_dir() or root.is_symlink():
            continue
        for entry in root.iterdir():
            # Restrict deletion to generated UUID names; preserve unknown files and links.
            if entry.is_symlink() or not entry.resolve().is_relative_to(storage.resolve()):
                continue
            owned = (
                TOKEN.fullmatch(entry.name)
                if name != "references"
                else TOKEN.fullmatch(entry.stem)
                and entry.suffix in {".tmp", ".png", ".jpg", ".webp"}
            )
            if not owned or entry.resolve() in protected:
                continue
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            except OSError:
                logger.exception("Could not clean orphan %s", entry)
    for path in used:
        if not path.is_file():
            logger.warning("Stored image missing: %s", path)
