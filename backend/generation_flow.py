"""Connect reference images and transient selections to completed generations."""

import json
import logging
import sqlite3

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from backend.app_options import installed_models
from backend.comfyui import ComfyUIClient, ComfyUIError, ComfyUITimeout
from backend.config import Settings
from backend.database import Database
from backend.generation import generate_images
from backend.generation_storage import tag_and_save_generation, validate_selection
from backend.tag_feedback import INHERITANCE_RATE, update_tag_weights
from backend.tagging import tag_image


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: StrictInt | None = None
    selection: dict[str, list[StrictInt]] | None = None
    checkpoint: str | None = Field(default=None, min_length=1)


def prompt(weights: dict[str, float], positive: bool) -> str:
    # Escape CLIP's emphasis syntax while retaining the exact signed tag weights.
    def escape(tag):
        return tag.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    return ", ".join(
        f"({escape(tag)}:{abs(weight):.8g})"
        for tag, weight in sorted(weights.items())
        if (weight > 0 if positive else weight < 0)
    )


def flow_router(
    database: Database, settings: Settings, running: set[int] | None = None
) -> APIRouter:
    router = APIRouter(prefix="/api/projects", tags=["generation flow"])
    running = running if running is not None else set()

    @router.get("/{project_id}/generation-status")
    async def status(project_id: int) -> dict:
        with database.connect() as connection:
            if not connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone():
                raise HTTPException(404, "Project not found")
        return {"running": project_id in running}

    @router.post("/{project_id}/generations", status_code=201)
    async def generate(project_id: int, body: GenerateRequest) -> dict:
        with database.connect() as connection:
            project = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise HTTPException(404, "Project not found")
            try:
                validate_selection(connection, project_id, body.parent_id, body.selection)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            parent = None
            tags = {}
            if body.parent_id is not None:
                parent = json.loads(
                    connection.execute(
                        "SELECT parameters_json FROM generations WHERE id = ?", (body.parent_id,)
                    ).fetchone()[0]
                )
                tags = {
                    row["id"]: json.loads(row["tags_json"])
                    for row in connection.execute(
                        "SELECT id, tags_json FROM images WHERE generation_id = ?",
                        (body.parent_id,),
                    )
                }
            elif connection.execute(
                "SELECT id FROM generations WHERE project_id = ?", (project_id,)
            ).fetchone():
                raise HTTPException(409, "Select a parent generation")
        if project_id in running:
            raise HTTPException(409, "Generation already running")
        running.add(project_id)
        try:
            project_config = (
                json.loads(project["generation_config_json"])
                if project["generation_config_json"]
                else None
            )
            effective_settings = settings
            if project_config:
                if body.checkpoint and body.checkpoint != project_config["checkpoint"]:
                    raise HTTPException(422, "プロジェクト作成時のモデルを使用してください。")
                if project_config["checkpoint"] not in await installed_models(settings):
                    raise HTTPException(409, "プロジェクトのモデルがComfyUIに存在しません。")
                effective_settings = settings.model_copy(
                    update={"width": project_config["width"], "height": project_config["height"]}
                )
            async with httpx.AsyncClient(trust_env=False) as http:
                client = ComfyUIClient(http, settings.comfyui_url)
                if parent is None:
                    path = (settings.storage_dir / project["initial_image_path"]).resolve()
                    if (
                        not project["initial_image_path"]
                        or not path.is_file()
                        or not path.is_relative_to(settings.storage_dir.resolve())
                    ):
                        raise HTTPException(409, "Register a reference image first")
                    initial = await tag_image(client, path.read_bytes())
                    weights = dict.fromkeys(initial.tags, 1.0)
                else:
                    feedback = update_tag_weights(
                        parent.get("tag_weights", {}),
                        liked=[tags[item] for item in body.selection["liked"]],
                        disliked=[tags[item] for item in body.selection["disliked"]],
                    )
                    weights = feedback.weights
                checkpoint = (
                    (project_config or {}).get("checkpoint")
                    or body.checkpoint
                    or (parent or {}).get("checkpoint")
                )
                if not checkpoint:
                    info = await client._request("GET", "/object_info/CheckpointLoaderSimple", 30)
                    try:
                        checkpoint = info["CheckpointLoaderSimple"]["input"]["required"][
                            "ckpt_name"
                        ][0][0]
                    except (KeyError, IndexError, TypeError) as exc:
                        raise ComfyUIError("No checkpoint available") from exc
                sampling = {
                    key: parent[key]
                    for key in ("steps", "cfg", "sampler", "scheduler")
                    if parent and key in parent
                }
                result = await generate_images(
                    client,
                    effective_settings,
                    checkpoint=checkpoint,
                    positive=prompt(weights, True),
                    negative=prompt(weights, False),
                    **sampling,
                )
                result.parameters.update(
                    tag_weights=weights,
                    inheritance_rate=INHERITANCE_RATE,
                    tagger={
                        "model": "wd-v1-4-moat-tagger-v2",
                        "threshold": 0.35,
                        "character_threshold": 0.85,
                    },
                )
                generation_id = await tag_and_save_generation(
                    client,
                    database,
                    settings.storage_dir,
                    project_id,
                    result,
                    parent_id=body.parent_id,
                    selection=body.selection,
                )
            return {"id": generation_id}
        except ComfyUITimeout as exc:
            raise HTTPException(504, str(exc)) from exc
        except ComfyUIError as exc:
            raise HTTPException(502, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (OSError, sqlite3.Error) as exc:
            logging.getLogger("uvicorn.error").exception("Generation storage failed")
            raise HTTPException(
                500, "Cannot save generation; reload saved results before retrying"
            ) from exc
        finally:
            running.discard(project_id)

    return router
