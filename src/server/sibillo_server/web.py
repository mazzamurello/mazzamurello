"""The web app, served at `/` next to the API (UX-001, ADR-0067).

The app is a static single-page app: its files are served as they are, and
any other path outside the API loads the app, which routes it itself. Every
response carries a Content Security Policy that allows only the app's own
scripts (UX-002).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from sibillo_server import errors

API_SEGMENT = "v1"
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        # Rendered math sets inline styles; no inline scripts are allowed.
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "worker-src 'self'",
        "manifest-src 'self'",
        "form-action 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
    )
)
HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def router(root: Path) -> APIRouter:
    """Routes serving the built app in `root`; the API's own routes come first."""
    root = root.resolve()
    index = root / "index.html"
    routes = APIRouter(include_in_schema=False)

    @routes.get("/{path:path}")
    async def serve(path: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        if path == API_SEGMENT or path.startswith(f"{API_SEGMENT}/"):
            raise errors.not_found()
        candidate = (root / path).resolve()
        if not candidate.is_relative_to(root):
            return Response(status_code=404, headers=HEADERS)
        if candidate.is_file():
            # Built files have content hashes in their names; the page and the
            # service worker must always be fetched fresh.
            fresh = candidate.name in {"index.html", "sw.js"} or candidate.suffix == ".webmanifest"
            cache = "no-cache" if fresh else "public, max-age=31536000, immutable"
            return FileResponse(candidate, headers=HEADERS | {"Cache-Control": cache})
        if Path(path).suffix:
            # A missing file, not a route of the app.
            return Response(status_code=404, headers=HEADERS)
        return FileResponse(index, headers=HEADERS | {"Cache-Control": "no-cache"})

    return routes
