"""Project creation and retrieval without unfinished generation records."""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app_options import FIXED_SIZES, ImageSize, OptionsStore, installed_models
from backend.config import Settings
from backend.database import Database
from backend.recovery import TOKEN


class ProjectGenerationConfig(ImageSize):
    checkpoint: str = Field(min_length=1)


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    generation_config: ProjectGenerationConfig | None = None

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class Project(BaseModel):
    id: int
    name: str
    initial_image_path: str | None
    created_at: str
    updated_at: str
    generation_count: int
    generation_config: ProjectGenerationConfig | None = None


QUERY = """
SELECT p.*, (SELECT COUNT(*) FROM generations g WHERE g.project_id = p.id)
    AS generation_count FROM projects p
"""


def project_from_row(row) -> Project:
    values = dict(row)
    values["initial_image_path"] = values["initial_image_path"] or None
    raw = values.pop("generation_config_json", None)
    values["generation_config"] = json.loads(raw) if raw else None
    return Project(**values)


def project_router(
    database: Database,
    storage: Path,
    running: set[int],
    settings: Settings | None = None,
    store: OptionsStore | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/projects", tags=["projects"])
    settings = settings or Settings(storage_dir=storage)
    store = store or OptionsStore(storage)

    @router.post("", response_model=Project, status_code=201)
    async def create_project(payload: ProjectCreate) -> Project:
        config = payload.generation_config
        if config:
            installed = await installed_models(settings)
            options = store.read()
            if (
                config.checkpoint not in options.model_whitelist
                or config.checkpoint not in installed
            ):
                raise HTTPException(422, "ホワイトリスト内の利用可能なモデルを選んでください。")
            if (config.width, config.height) not in {
                (size.width, size.height) for size in FIXED_SIZES + options.extra_sizes
            }:
                raise HTTPException(422, "登録済みの画像サイズを選んでください。")
        with database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO projects (name, initial_image_path, generation_config_json) "
                "VALUES (?, '', ?)",
                (payload.name, config.model_dump_json() if config else None),
            )
            row = connection.execute(QUERY + " WHERE p.id = ?", (cursor.lastrowid,)).fetchone()
            return project_from_row(row)

    @router.get("", response_model=list[Project])
    def list_projects() -> list[Project]:
        with database.connect() as connection:
            rows = connection.execute(QUERY + " ORDER BY p.updated_at DESC, p.id DESC").fetchall()
            return [project_from_row(row) for row in rows]

    @router.get("/{project_id}", response_model=Project)
    def get_project(project_id: int) -> Project:
        with database.connect() as connection:
            row = connection.execute(QUERY + " WHERE p.id = ?", (project_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Project not found")
            return project_from_row(row)

    @router.delete("/{project_id}", status_code=204)
    async def delete_project(project_id: int) -> Response:
        # No awaits: generation start and deletion cannot interleave on the event loop.
        if project_id in running:
            raise HTTPException(409, "Generation already running")
        with database.transaction() as connection:
            connection.execute("UPDATE projects SET id = id WHERE id = ?", (project_id,))
            row = connection.execute(
                "SELECT initial_image_path FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(404, "Project not found")
            paths = [row[0]] if row[0] else []
            paths.extend(
                item[0]
                for item in connection.execute(
                    "SELECT i.file_path FROM images i JOIN generations g "
                    "ON g.id = i.generation_id WHERE g.project_id = ?",
                    (project_id,),
                )
            )
            connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            used = {item[0] for item in connection.execute("SELECT file_path FROM images")}
            used.update(
                item[0] for item in connection.execute("SELECT initial_image_path FROM projects")
            )
        protected = {(storage / item).resolve() for item in used if item}
        for value in paths:
            relative = Path(value)
            reference = (
                len(relative.parts) == 2
                and relative.parts[0] == "references"
                and TOKEN.fullmatch(relative.stem)
                and relative.suffix in {".png", ".jpg", ".webp"}
            )
            generated = (
                len(relative.parts) == 3
                and relative.parts[0] == "generations"
                and TOKEN.fullmatch(relative.parts[1])
            )
            target = storage / relative
            if (
                not (reference or generated)
                or target.is_symlink()
                or any(parent.is_symlink() for parent in target.parents)
                or not target.resolve().is_relative_to(storage.resolve())
                or target.resolve() in protected
            ):
                continue
            try:
                target.unlink(missing_ok=True)
                if generated and target.parent.is_dir() and not any(target.parent.iterdir()):
                    target.parent.rmdir()
            except OSError:
                logging.getLogger("uvicorn.error").exception(
                    "Could not clean deleted image %s", target
                )
        return Response(status_code=204)

    return router
