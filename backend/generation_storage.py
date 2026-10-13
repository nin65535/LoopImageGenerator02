"""Tag every candidate, then publish files and a complete immutable DB snapshot."""

import asyncio
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from backend.comfyui import ComfyUIClient
from backend.database import Database
from backend.generation import GenerationResult
from backend.reference_images import MAX_BYTES, validate_image
from backend.tagging import tag_image


def validate_selection(connection, project_id: int, parent_id: int | None, selection) -> None:
    if connection.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
        raise ValueError("Project not found")
    if parent_id is None:
        if selection is not None:
            raise ValueError("Root generations cannot have selections")
        return
    if (
        type(parent_id) is not int
        or connection.execute(
            "SELECT id FROM generations WHERE id = ? AND project_id = ?", (parent_id, project_id)
        ).fetchone()
        is None
    ):
        raise ValueError("Parent must belong to the project")
    if not isinstance(selection, dict) or set(selection) != {"liked", "disliked"}:
        raise ValueError("Selection requires liked and disliked arrays")
    groups = [selection["liked"], selection["disliked"]]
    if any(not isinstance(group, list) for group in groups):
        raise ValueError("Selections must be arrays")
    ids = groups[0] + groups[1]
    if not ids or any(type(item) is not int for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("Select distinct, disjoint integer image IDs, at least one")
    available = {
        row[0]
        for row in connection.execute("SELECT id FROM images WHERE generation_id = ?", (parent_id,))
    }
    if not set(ids) <= available:
        raise ValueError("Selected images must belong to the parent")


def save_generation(
    database: Database,
    storage: Path,
    project_id: int,
    result: GenerationResult,
    tags: tuple[dict, ...],
    *,
    parent_id: int | None = None,
    selection: dict | None = None,
) -> int:
    """Synchronous commit boundary: cancellation cannot interrupt filesystem/DB coordination."""
    count = result.parameters.get("image_count")
    if type(count) is not int or count < 1 or len(result.images) != count or len(tags) != count:
        raise ValueError("Every requested image must be present and tagged")
    if [image.position for image in result.images] != list(range(count)):
        raise ValueError("Image positions must be contiguous and ordered")
    if any(type(image.seed) is not int or not 0 <= image.seed < 2**63 for image in result.images):
        raise ValueError("Seeds must fit SQLite INTEGER")
    if result.parameters.get("seeds") != [image.seed for image in result.images]:
        raise ValueError("Parameter seeds must match the images")
    parameters_json = json.dumps(result.parameters, allow_nan=False)
    selection_json = None if selection is None else json.dumps(selection, allow_nan=False)
    tags_json = []
    extensions = []
    for image, image_tags in zip(result.images, tags, strict=True):
        if not isinstance(image_tags, dict) or any(
            not isinstance(key, str) or not key.strip() for key in image_tags
        ):
            raise ValueError("Tags must be objects with non-empty string keys")
        tags_json.append(json.dumps(image_tags, allow_nan=False))
        if len(image.data) > MAX_BYTES:
            raise ValueError("Image exceeds 20MiB")
        extensions.append(validate_image(image.data))

    token = uuid4().hex
    staged = storage / "staging" / token
    target = storage / "generations" / token
    committed = False
    try:
        # Validate before writing; revalidate under the write lock at commit time.
        with database.connect() as connection:
            validate_selection(connection, project_id, parent_id, selection)
        staged.mkdir(parents=True)
        filenames = [f"{image.position}.{ext}" for image, ext in zip(result.images, extensions)]
        for image, filename in zip(result.images, filenames, strict=True):
            with (staged / filename).open("xb") as file:
                file.write(image.data)
        target.parent.mkdir(parents=True, exist_ok=True)
        with database.transaction() as connection:
            connection.execute("UPDATE projects SET id = id WHERE id = ?", (project_id,))
            validate_selection(connection, project_id, parent_id, selection)
            generation_id = connection.execute(
                "INSERT INTO generations (project_id, parent_id, selection_json, parameters_json) "
                "VALUES (?, ?, ?, ?)",
                (project_id, parent_id, selection_json, parameters_json),
            ).lastrowid
            connection.executemany(
                "INSERT INTO images (generation_id, position, file_path, seed, tags_json) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        generation_id,
                        image.position,
                        (target / filename).relative_to(storage).as_posix(),
                        image.seed,
                        encoded_tags,
                    )
                    for image, filename, encoded_tags in zip(
                        result.images, filenames, tags_json, strict=True
                    )
                ],
            )
            staged.rename(target)
            connection.execute(
                "UPDATE projects SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE id = ?",
                (project_id,),
            )
        committed = True
        return generation_id
    finally:
        if staged.exists():
            shutil.rmtree(staged)
        if not committed and target.exists():
            shutil.rmtree(target)


async def tag_and_save_generation(
    client: ComfyUIClient,
    database: Database,
    storage: Path,
    project_id: int,
    result: GenerationResult,
    *,
    parent_id: int | None = None,
    selection: dict | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> int:
    tagged = []
    for image in result.images:
        tagged.append((await tag_image(client, image.data)).tags)
        if on_progress:
            on_progress(len(tagged))
    tags = tuple(tagged)
    return await save_tagged_generation(
        database, storage, project_id, result, tags, parent_id=parent_id, selection=selection
    )


async def save_tagged_generation(
    database: Database,
    storage: Path,
    project_id: int,
    result: GenerationResult,
    tags: tuple[dict, ...],
    *,
    parent_id: int | None = None,
    selection: dict | None = None,
) -> int:
    # Once commit starts, wait for its outcome even if the caller is cancelled.
    task = asyncio.create_task(
        asyncio.to_thread(
            save_generation,
            database,
            storage,
            project_id,
            result,
            tags,
            parent_id=parent_id,
            selection=selection,
        )
    )
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise
