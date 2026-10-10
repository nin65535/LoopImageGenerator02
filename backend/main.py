"""Local API and built frontend delivery."""

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.lifecycle import ConnectionMonitor

logger = logging.getLogger("uvicorn.error")
DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app(dist: Path = DIST, monitor: ConnectionMonitor | None = None) -> FastAPI:
    app = FastAPI(title="LoopImageGenerator V2")

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
