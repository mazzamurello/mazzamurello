"""The ASGI application of the public API (API-001)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sibillo_server import (
    admin,
    auth,
    connections,
    conversations,
    costs,
    folders,
    health,
    runs,
    settings,
    web,
    workspace,
)
from sibillo_server.config import ApiConfiguration
from sibillo_server.database import create_engine
from sibillo_server.durable import create_client
from sibillo_server.errors import install_error_handlers

API_PREFIX = "/v1"


def create_app(configuration: ApiConfiguration) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        engine = create_engine(configuration.database_url)
        app.state.engine = engine
        durable = create_client(configuration.database_url)
        app.state.durable = durable
        try:
            yield
        finally:
            durable.destroy()
            await engine.dispose()

    app = FastAPI(
        title="Sibillo public API",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.configuration = configuration
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(settings.router, prefix=API_PREFIX)
    app.include_router(admin.router, prefix=API_PREFIX)
    app.include_router(connections.router, prefix=API_PREFIX)
    app.include_router(conversations.router, prefix=API_PREFIX)
    app.include_router(folders.router, prefix=API_PREFIX)
    app.include_router(costs.router, prefix=API_PREFIX)
    app.include_router(runs.router, prefix=API_PREFIX)
    app.include_router(workspace.router, prefix=API_PREFIX)
    app.include_router(health.router, prefix=API_PREFIX)
    if configuration.web_root.is_dir():
        # After the API's routes, so that the app never hides an operation (ADR-0067).
        app.include_router(web.router(configuration.web_root))
    install_error_handlers(app)
    return app
