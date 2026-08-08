from __future__ import annotations

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


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    await init_db()
    get_runtime()  # warm registry + providers
    yield


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
    app.include_router(studio.router)
    app.include_router(agents.router)
    app.include_router(sources.router)
    app.include_router(chat.router)
    app.include_router(public.router)
    app.include_router(graph.router)
    return app


app = create_app()
