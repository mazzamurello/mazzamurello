"""The API process serves the web app at `/`, next to the API (UX-001, UX-002, ADR-0067).

These tests use a small stand-in for the built app, so they need no build;
the browser tests in tests/web use the real one.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from tests.support.server import Server

INDEX = "<!doctype html><title>Sibillo</title><div id=root></div><script src=/assets/app.js></script>"


@pytest.fixture(scope="module")
def web(server: Server, tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """The origin of an API process that serves a stand-in for the built app."""
    root: Path = tmp_path_factory.mktemp("web")
    (root / "index.html").write_text(INDEX)
    (root / "assets").mkdir()
    (root / "assets" / "app.js").write_text("console.log('app')")
    (root / "manifest.webmanifest").write_text('{"name": "Sibillo"}')
    api, origin = server.start_twin_api(SIBILLO_WEB_ROOT=str(root))
    yield origin
    api.close()


@pytest.mark.spec("UX-001")
def test_the_app_is_served_at_the_root(web: str) -> None:
    response = httpx.get(f"{web}/", timeout=10)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == INDEX
    assert httpx.get(f"{web}/assets/app.js", timeout=10).text == "console.log('app')"
    assert httpx.get(f"{web}/manifest.webmanifest", timeout=10).status_code == 200


@pytest.mark.spec("UX-001")
def test_the_apps_own_routes_load_the_app(web: str) -> None:
    response = httpx.get(f"{web}/conversations/0190f5c4-0000-7000-8000-000000000000", timeout=10)
    assert response.status_code == 200
    assert response.text == INDEX


@pytest.mark.spec("UX-001", "API-001")
def test_the_api_is_unchanged_next_to_the_app(web: str) -> None:
    unknown = httpx.get(f"{web}/v1/no-such-operation", timeout=10)
    assert unknown.status_code == 404
    assert unknown.headers["content-type"].startswith("application/problem+json")
    assert httpx.get(f"{web}/v1/me", timeout=10).status_code == 401


@pytest.mark.spec("UX-001")
def test_missing_files_are_not_found_and_nothing_outside_the_app_is_served(web: str) -> None:
    assert httpx.get(f"{web}/assets/missing.js", timeout=10).status_code == 404
    assert httpx.get(f"{web}/assets/..%2f..%2findex.html", timeout=10).status_code in {400, 404}
    assert httpx.get(f"{web}/..%2f..%2fetc%2fpasswd", timeout=10).text != "root"


@pytest.mark.spec("UX-002")
def test_the_app_runs_only_its_own_scripts(web: str) -> None:
    policy = httpx.get(f"{web}/", timeout=10).headers["content-security-policy"]
    directives = {part.strip().split(" ", 1)[0]: part.strip() for part in policy.split(";") if part.strip()}
    assert directives["script-src"] == "script-src 'self'"
    assert directives["object-src"] == "object-src 'none'"
    assert directives["base-uri"] == "base-uri 'none'"
    assert directives["frame-ancestors"] == "frame-ancestors 'none'"


@pytest.mark.spec("UX-001")
def test_without_a_built_app_only_the_api_is_served(server: Server) -> None:
    origin = server.base_url.removesuffix("/v1")
    assert httpx.get(f"{origin}/", timeout=10).status_code == 404
