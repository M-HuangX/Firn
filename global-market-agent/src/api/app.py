"""FastAPI application factory — entry point for the web API.

Run with: uvicorn src.api.app:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()  # Load .env when started via uvicorn (CLI uses __main__.py)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan: warm up MCP client + execution queue on startup, close on shutdown."""
    # Start execution queue
    from src.api.services import start_execution_queue, stop_execution_queue

    start_execution_queue()
    logger.info("Execution queue started")

    try:
        from src.tools.mcp_client import get_mcp_tools

        await get_mcp_tools()
        logger.info("MCP client initialized")
    except Exception:
        logger.warning("MCP client init failed — tools will init lazily on first use")
    yield
    # Shutdown
    await stop_execution_queue()
    logger.info("Execution queue stopped")
    try:
        from src.tools.mcp_client import close_mcp_client

        await close_mcp_client()
        logger.info("MCP client closed")
    except Exception:
        logger.warning("MCP client close failed")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Financial Analysis Agent API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — allow localhost for dev + production origin from env
    allowed_origins = ["http://localhost:3000"]
    extra_origins = os.environ.get("ALLOWED_ORIGINS", "")
    if extra_origins:
        allowed_origins.extend(o.strip() for o in extra_origins.split(",") if o.strip())

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global error handler
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error: %s", exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    # Routers
    from src.api.routers import analysis, config, digest, events, kb, system

    app.include_router(system.router, prefix="/api", tags=["system"])
    app.include_router(analysis.router, prefix="/api", tags=["analysis"])
    app.include_router(digest.router, prefix="/api", tags=["digest"])
    app.include_router(kb.router, prefix="/api/kb", tags=["kb"])
    app.include_router(config.router, prefix="/api/config", tags=["config"])
    app.include_router(events.router, prefix="/api", tags=["events"])

    return app


app = create_app()
