"""Bounded reference uploads, validated by decoding rather than client filenames."""

import io
import logging
import warnings
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from backend.database import Database
from backend.projects import QUERY, Project, project_from_row

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 25_000_000
FORMATS = {
    "PNG": ("png", "image/png"),
    "JPEG": ("jpg", "image/jpeg"),
    "WEBP": ("webp", "image/webp"),
}
logger = logging.getLogger("uvicorn.error")


def validate_image(data: bytes) -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in FORMATS:
                    raise HTTPException(415, "PNG・JPEG・WebPを選んでください。")
                if image.width * image.height > MAX_PIXELS:
                    raise HTTPException(413, "画像は2,500万画素以下にしてください。")
                if getattr(image, "n_frames", 1) != 1:
                    raise HTTPException(415, "静止画像を選んでください。")
                extension = FORMATS[image.format][0]
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
            return extension
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise HTTPException(413, "画像の画素数が大きすぎます。") from error
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as error:
        raise HTTPException(422, "画像が空か破損しています。") from error


def reference_router(database: Database, storage: Path) -> APIRouter:
    router = APIRouter(prefix="/api/projects", tags=["reference-images"])

    def save(project_id: int, data: bytes) -> Project:
        extension = validate_image(data)
        target = storage / "references" / f"{uuid4().hex}.{extension}"
        staged = target.with_suffix(".tmp")
        committed = False
        try:
            # Acquire the write lock before checking: concurrent uploads cannot overwrite.
            with database.transaction() as connection:
                connection.execute("UPDATE projects SET id = id WHERE id = ?", (project_id,))
                row = connection.execute(QUERY + " WHERE p.id = ?", (project_id,)).fetchone()
                if row is None:
                    raise HTTPException(404, "Project not found")
                if row["initial_image_path"] or row["generation_count"]:
                    raise HTTPException(
                        409, "参考画像は登録済みです。新規プロジェクトを作成してください。"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                with staged.open("xb") as file:
                    file.write(data)
                staged.replace(target)
                connection.execute(
                    "UPDATE projects SET initial_image_path = ?, "
                    "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                    (target.relative_to(storage).as_posix(), project_id),
                )
                result = project_from_row(
                    connection.execute(QUERY + " WHERE p.id = ?", (project_id,)).fetchone()
                )
            committed = True
            return result
        finally:
            staged.unlink(missing_ok=True)
            if not committed:
                target.unlink(missing_ok=True)

    @router.put("/{project_id}/initial-image", response_model=Project)
    async def upload(project_id: int, request: Request) -> Project:
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_BYTES:
                raise HTTPException(413, "画像は20MiB以下にしてください。")
            data.extend(chunk)
        try:
            return await run_in_threadpool(save, project_id, bytes(data))
        except OSError as error:
            logger.exception("Reference image storage failed")
            raise HTTPException(500, "画像を保存できません。再試行してください。") from error

    @router.get("/{project_id}/initial-image")
    def retrieve(project_id: int) -> FileResponse:
        with database.connect() as connection:
            row = connection.execute(
                "SELECT initial_image_path FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row is None or not row[0]:
            raise HTTPException(404, "Reference image not found")
        path = (storage / row[0]).resolve()
        if not path.is_relative_to((storage / "references").resolve()) or not path.is_file():
            raise HTTPException(404, "Reference image not found")
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}
        return FileResponse(
            path,
            media_type=mime.get(path.suffix, "application/octet-stream"),
            headers={"X-Content-Type-Options": "nosniff"},
        )

    return router
