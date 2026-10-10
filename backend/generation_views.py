"""Read complete generation snapshots and their stored images."""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

from backend.database import Database


def generation_router(
    database: Database, storage: Path, running: set[int] | None = None
) -> APIRouter:
    router = APIRouter(prefix="/api/projects", tags=["generations"])

    @router.get("/{project_id}/generations")
    def list_generations(project_id: int, response: Response) -> list[dict]:
        response.headers["X-Generation-Running"] = str(project_id in (running or set())).lower()
        with database.connect() as connection:
            if (
                connection.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
                is None
            ):
                raise HTTPException(404, "Project not found")
            rows = connection.execute(
                "SELECT * FROM generations WHERE project_id = ? ORDER BY id", (project_id,)
            ).fetchall()
            images = connection.execute(
                "SELECT i.* FROM images i JOIN generations g ON g.id = i.generation_id "
                "WHERE g.project_id = ? ORDER BY i.generation_id, i.position",
                (project_id,),
            ).fetchall()
        grouped: dict[int, list[dict]] = {}
        for image in images:
            grouped.setdefault(image["generation_id"], []).append(
                {
                    "id": image["id"],
                    "position": image["position"],
                    "seed": image["seed"],
                    "tags": json.loads(image["tags_json"]),
                    "url": f"/api/projects/{project_id}/images/{image['id']}",
                }
            )
        return [
            {
                "id": row["id"],
                "parent_id": row["parent_id"],
                "selection": json.loads(row["selection_json"]) if row["selection_json"] else None,
                "created_at": row["created_at"],
                "parameters": json.loads(row["parameters_json"]),
                "images": grouped.get(row["id"], []),
            }
            for row in rows
        ]

    @router.get("/{project_id}/images/{image_id}")
    def get_image(project_id: int, image_id: int) -> FileResponse:
        with database.connect() as connection:
            row = connection.execute(
                "SELECT i.file_path FROM images i JOIN generations g ON g.id = i.generation_id "
                "WHERE i.id = ? AND g.project_id = ?",
                (image_id, project_id),
            ).fetchone()
        if row is None:
            raise HTTPException(404, "Image not found")
        path = (storage / row[0]).resolve()
        if not path.is_relative_to((storage / "generations").resolve()) or not path.is_file():
            raise HTTPException(404, "Image not found")
        return FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})

    return router
