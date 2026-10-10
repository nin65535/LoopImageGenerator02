"""Local API and built frontend delivery."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.config import Settings, load_settings
from backend.database import Database
from backend.lifecycle import ConnectionMonitor
from backend.projects import project_router

logger = logging.getLogger("uvicorn.error")
DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app(
    dist: Path = DIST,
    monitor: ConnectionMonitor | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    database = Database(settings.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.initialize()
        yield

    app = FastAPI(title="LoopImageGenerator V2", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = database
    app.include_router(project_router(database))

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        async def stream():
            if monitor:
                monitor.connect()
            try:
                yield "event: ready\ndata: connected\n\n"
                while not await request.is_disconnected():
                    await asyncio.sleep(0.5)
                    yield ": heartbeat\n\n"
            finally:
                if monitor:
                    monitor.disconnect()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

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
