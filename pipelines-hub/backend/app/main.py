"""Punto de entrada: API + front estático + MCP + poller."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import kube
from app.api import router
from app.config import get_settings
from app.db import init_db
from app.infra_api import router as infra_router
from app.mcp_server import mcp
from app.providers import close_all
from app.servers import poller as infra_poller
from app.sync import syncer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

settings = get_settings()
mcp_app = mcp.http_app(path="/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    syncer.start()
    infra_poller.start()
    async with mcp_app.lifespan(app):
        yield
    await syncer.stop()
    await infra_poller.stop()
    await close_all()
    await kube.close_all()


app = FastAPI(title="Pipelines Hub", lifespan=lifespan)
app.include_router(router)
app.include_router(infra_router)
app.mount("/mcp", mcp_app)


@app.get("/api/health")
async def health():
    return {"ok": True}


static_dir: Path | None = settings.static_dir
if static_dir and static_dir.exists():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith(("api/", "mcp")):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        file = static_dir / path
        if path and file.is_file():
            return FileResponse(file)
        return FileResponse(static_dir / "index.html")
