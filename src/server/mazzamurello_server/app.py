"""The ASGI application of the public API (API-001)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from mazzamurello_server import admin, auth, conversations, model_configurations, runs
from mazzamurello_server.config import ApiConfiguration
from mazzamurello_server.database import create_engine
from mazzamurello_server.durable import create_client
from mazzamurello_server.errors import install_error_handlers

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
        title="Mazzamurello public API",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.configuration = configuration
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(admin.router, prefix=API_PREFIX)
    app.include_router(model_configurations.router, prefix=API_PREFIX)
    app.include_router(conversations.router, prefix=API_PREFIX)
    app.include_router(runs.router, prefix=API_PREFIX)
    install_error_handlers(app)
    return app
