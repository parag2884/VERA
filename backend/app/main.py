from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.db import init_db
from app.logging_utils import setup_logging
from app.middleware_public_cors import PublicCORSMiddleware
from app.routers import agents, chat, graph, health, public, sources, studio, workspaces
from app.runtime import get_runtime
from app.trust_forge import router as trust_forge_router
from app.knowledge_os.router import board_router as knowledge_os_board
from app.knowledge_os.router import router as knowledge_os_router


async def _care_loop() -> None:
    from app.config import get_settings
    from app.knowledge_os.care import tick_fleet

    interval = max(0, int(get_settings().vera_care_interval_sec))
    if interval <= 0:
        return
    await asyncio.sleep(min(90, interval))
    while True:
        try:
            await tick_fleet()
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    await init_db()
    get_runtime()  # warm registry + providers
    from app.trust_forge.service import abandon_orphaned_runs

    await abandon_orphaned_runs()
    task = asyncio.create_task(_care_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="VERA — Verified Evidence & Reliable Agents",
        version=__version__,
        description=(
            "Graph-Primary Evidence Engine. "
            "No evidence-bearing edge = no answer-bearing edge."
        ),
        lifespan=lifespan,
    )
    # Public embed CORS first (outermost after reverse add order)
    app.add_middleware(PublicCORSMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(workspaces.router)
    app.include_router(trust_forge_router)
    app.include_router(knowledge_os_router)
    app.include_router(knowledge_os_board)
    app.include_router(studio.router)
    app.include_router(agents.router)
    app.include_router(sources.router)
    app.include_router(chat.router)
    app.include_router(public.router)
    app.include_router(graph.router)
    return app


app = create_app()
