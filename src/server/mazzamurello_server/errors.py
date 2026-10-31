"""Errors as RFC 9457 problem details with a stable code (API-007)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"


class ApiError(Exception):
    """An error with a status and a code of the API contract."""

    def __init__(self, status: int, code: str, title: str, headers: Mapping[str, str] | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.title = title
        self.headers = dict(headers or {})


def unauthenticated() -> ApiError:
    return ApiError(401, "auth.unauthenticated", "Unauthenticated")


def invalid_credentials() -> ApiError:
    return ApiError(401, "auth.invalid_credentials", "Invalid credentials")


def rate_limited(retry_after_seconds: int) -> ApiError:
    return ApiError(429, "auth.rate_limited", "Too many attempts", {"Retry-After": str(max(1, retry_after_seconds))})


def permission_denied() -> ApiError:
    return ApiError(403, "permission.denied", "Forbidden")


def not_found() -> ApiError:
    return ApiError(404, "resource.not_found", "Not found")


def conflict() -> ApiError:
    return ApiError(409, "resource.conflict", "Conflict")


def validation_failed(errors: list[dict[str, str]]) -> JSONResponse:
    return problem(422, "request.validation_failed", "Validation failed", errors=errors)


def problem(status: int, code: str, title: str, headers: Mapping[str, str] | None = None, **extra: Any) -> JSONResponse:
    content: dict[str, Any] = {"type": "about:blank", "title": title, "status": status, "code": code} | extra
    return JSONResponse(content, status_code=status, headers=dict(headers or {}), media_type=PROBLEM_MEDIA_TYPE)


def _location(location: tuple[int | str, ...]) -> str:
    """A JSON pointer into the body, or the name of a parameter."""
    if location and location[0] == "body":
        return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in location[1:])
    return str(location[-1]) if location else ""


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return problem(error.status, error.code, error.title, error.headers)

    @app.exception_handler(RequestValidationError)
    async def request_validation(  # pyright: ignore[reportUnusedFunction]
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        # Field locations and error types only: values may be passwords.
        return validation_failed(
            [{"location": _location(tuple(item["loc"])), "code": str(item["type"])} for item in error.errors()]
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(  # pyright: ignore[reportUnusedFunction]
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        if error.status_code == 404:
            return problem(404, "resource.not_found", "Not found")
        return problem(error.status_code, "request.validation_failed", "Request not accepted", error.headers)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        logger.error("unhandled error in %s %s: %s", request.method, request.url.path, type(error).__name__)
        return problem(500, "internal.error", "Internal error")
