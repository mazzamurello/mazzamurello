"""Fixtures for the web client's browser tests (ADR-0067; the harness's Web procedure).

The app is built from src/web once per session and served by an API process
next to the session's server; Chromium is driven with Playwright.

Tests find elements by their role and accessible name. The sprite is hidden
from assistive technologies (UX-013), so tests find it by its
`data-sprite-pose` attribute, which names the pose it shows: `greeting`,
`thinking`, `searching`, `reading`, `writing`, `running`, `answering`,
`waiting` or `error` (ADR-0070).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from tests.support.accounts import Account, create_account, create_tenant
from tests.support.database import ROOT, Database
from tests.support.fixtures import HarnessModel
from tests.support.fixtures import database as database
from tests.support.fixtures import default_model as default_model
from tests.support.fixtures import harness_model as harness_model
from tests.support.fixtures import model_server as model_server
from tests.support.fixtures import sandboxes as sandboxes
from tests.support.fixtures import search_service as search_service
from tests.support.fixtures import server as server
from tests.support.server import Server

WEB = ROOT / "src" / "web"
AXE = WEB / "node_modules" / "axe-core" / "axe.min.js"
# WCAG 2.2 level AA, and what it includes (UX-007).
WCAG_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]


def _pnpm(*args: str) -> None:
    environment = os.environ | {"COREPACK_ENABLE_DOWNLOAD_PROMPT": "0"}
    corepack = shutil.which("corepack")
    assert corepack, "the web tests need Node.js with corepack"
    subprocess.run([corepack, "pnpm", *args], cwd=WEB, env=environment, check=True, timeout=600)  # noqa: S603


@pytest.fixture(scope="session")
def web_build() -> Path:
    """The app, installed from its lock file and built."""
    _pnpm("install", "--frozen-lockfile")
    _pnpm("build")
    return WEB / "dist"


@pytest.fixture(scope="session")
def web_origin(server: Server, web_build: Path) -> Iterator[str]:
    api, origin = server.start_twin_api(SIBILLO_WEB_ROOT=str(web_build))
    yield origin
    api.close()


@pytest.fixture(scope="session")
def playwright() -> Iterator[Playwright]:
    with sync_playwright() as instance:
        yield instance


@pytest.fixture(scope="session")
def browser(playwright: Playwright) -> Iterator[Browser]:
    chromium = playwright.chromium.launch()
    yield chromium
    chromium.close()


@pytest.fixture
def page(browser: Browser, web_origin: str) -> Iterator[Page]:
    context = browser.new_context(base_url=web_origin)
    page = context.new_page()
    page.set_default_timeout(15_000)
    yield page
    context.close()


@pytest.fixture
def member(database: Database, default_model: HarnessModel) -> Account:
    """A member of a household whose default model is the harness model."""
    account = create_account(database, create_tenant(database))
    default_model.connect(account.tenant_id)
    return account


@pytest.fixture
def admin(database: Database, default_model: HarnessModel) -> Account:
    """A tenant admin, also the instance admin, of a household whose default model is the harness model."""
    account = create_account(database, create_tenant(database), "tenant_admin", instance_admin=True)
    default_model.connect(account.tenant_id)
    return account


def sign_in(page: Page, account: Account, *, form: bool = False) -> None:
    """Sign in with the form, or, quicker, with the same request the form makes (ADR-0067)."""
    if form:
        page.goto("/")
        page.get_by_label("Username").fill(account.username)
        page.get_by_label("Password").fill(account.password)
        page.get_by_role("button", name="Sign in").click()
    else:
        response = page.request.post(
            "/v1/auth/login",
            data={
                "username": account.username,
                "password": account.password,
                "device_name": "browser test",
                "session_delivery": "cookie",
            },
        )
        assert response.status == 201, response.text()
        page.goto("/")
    # The message box: on phones the conversation list is hidden behind a button.
    page.get_by_label("Message").wait_for()


def accessibility_violations(page: Page) -> list[dict[str, Any]]:
    """WCAG 2.2 AA violations on the page, found by axe-core (UX-007).

    The script is evaluated rather than added as a tag, which the app's
    Content Security Policy rightly refuses.
    """
    page.evaluate(AXE.read_text())
    result: dict[str, Any] = page.evaluate(
        "async (tags) => await axe.run(document, {runOnly: {type: 'tag', values: tags}})", WCAG_AA
    )
    return [{"id": v["id"], "nodes": [n["target"] for n in v["nodes"]]} for v in result["violations"]]
