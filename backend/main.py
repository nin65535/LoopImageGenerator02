"""Local API and built frontend delivery."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("uvicorn.error")
DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app(dist: Path = DIST) -> FastAPI:
    app = FastAPI(title="LoopImageGenerator V2")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        logger.info("Health check requested")
        return {"status": "ok", "app": "LoopImageGenerator V2"}

    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:
        logger.info("Frontend build missing; use the Vite dev server or build frontend")
    return app


app = create_app()
