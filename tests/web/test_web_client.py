"""The web client in Chromium (ADR-0067).

The model the tests serve answers `Echo: <message>`, and scripts such as
`slow:N` and `run:<command>` (tests/support/model.py).
"""

from __future__ import annotations

import re
from uuid import uuid4

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.support.accounts import Account
from tests.support.fixtures import HarnessModel
from tests.web.conftest import accessibility_violations, sign_in


def _send(page: Page, text: str) -> None:
    page.get_by_label("Message").fill(text)
    page.get_by_role("button", name="Send").click()


def _answer(page: Page, text: str) -> None:
    expect(page.get_by_role("main")).to_contain_text(text, timeout=30_000)


@pytest.mark.spec("UX-001", "AUTH-005", "UX-007")
def test_signing_in_and_chatting(page: Page, member: Account, default_model: HarnessModel) -> None:
    page.goto("/")
    assert accessibility_violations(page) == []
    sign_in(page, member)
    # The session is a cookie that scripts cannot read (AUTH-005).
    assert "mzm_session" not in page.evaluate("document.cookie")
    mark = uuid4().hex[:8]
    _send(page, f"hello {mark}")
    _answer(page, f"Echo: hello {mark}")
    expect(page).to_have_url(re.compile(r"/c/[0-9a-f-]+$"))
    expect(page.get_by_role("navigation")).to_contain_text("New conversation")
    assert accessibility_violations(page) == []
    page.reload()
    _answer(page, f"Echo: hello {mark}")


@pytest.mark.spec("UX-002")
def test_messages_render_markdown_but_no_html_or_images(
    page: Page, member: Account, default_model: HarnessModel
) -> None:
    sign_in(page, member)
    # The served model answers `Echo: <message>`: the table starts on a line of its own.
    message = (
        "markdown\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nprint(1)\n```\n\n$x^2$\n\n"
        "![remote](http://203.0.113.9/x.png) <img src=x onerror=alert(1)>"
    )
    _send(page, message)
    answer = page.get_by_role("main")
    expect(answer.locator("table")).to_have_count(1, timeout=30_000)
    expect(answer.get_by_role("button", name="Copy")).to_have_count(1)
    expect(answer.locator(".katex").first).to_be_visible()
    expect(answer.locator("img")).to_have_count(0)


@pytest.mark.spec("UX-003")
def test_tool_activity_is_summarized_and_expands(page: Page, member: Account, default_model: HarnessModel) -> None:
    sign_in(page, member)
    _send(page, "run:echo tool-output-42")
    summary = page.locator("summary", has_text="Used")
    expect(summary).to_be_visible(timeout=30_000)
    # Collapsed by default; its details expand on request.
    expect(page.locator("details[open]")).to_have_count(0)
    summary.click()
    expect(page.locator("details[open]")).to_contain_text("tool-output-42")


@pytest.mark.spec("UX-001")
def test_a_run_can_be_stopped(page: Page, member: Account, default_model: HarnessModel) -> None:
    sign_in(page, member)
    _send(page, "slow:20")
    page.get_by_role("button", name="Stop").click()
    expect(page.get_by_role("status")).to_contain_text("Stopped.", timeout=30_000)
    expect(page.get_by_role("button", name="Send")).to_be_visible()


@pytest.mark.spec("UX-010", "UX-007")
def test_versions_and_going_back(page: Page, member: Account, default_model: HarnessModel) -> None:
    sign_in(page, member)
    mark = uuid4().hex[:8]
    _send(page, f"first {mark}")
    _answer(page, f"Echo: first {mark}")
    _send(page, f"second {mark}")
    _answer(page, f"Echo: second {mark}")
    # Editing the first message makes a second version of it.
    page.get_by_role("button", name="Edit").first.click()
    page.get_by_label("Edit your message").fill(f"first, edited {mark}")
    page.get_by_role("button", name="Send").first.click()
    _answer(page, f"Echo: first, edited {mark}")
    expect(page.get_by_text("2 / 2")).to_be_visible()
    expect(page.get_by_role("main")).not_to_contain_text(f"second {mark}")
    # The first version comes back with the turn that followed it.
    page.get_by_role("button", name="Previous version").click()
    _answer(page, f"Echo: second {mark}")
    expect(page.get_by_text("1 / 2")).to_be_visible()
    # Going back says that the workspace's files stay (UX-010).
    page.get_by_role("button", name="Go back to here").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("Files in your workspace are not changed")
    assert accessibility_violations(page) == []
    dialog.get_by_role("button", name="Go back").click()
    expect(page.get_by_role("main")).not_to_contain_text(f"second {mark}")


@pytest.mark.spec("UX-007")
def test_model_settings(page: Page, admin: Account, default_model: HarnessModel) -> None:
    sign_in(page, admin)
    page.get_by_role("link", name="Model settings").click()
    expect(page.get_by_role("heading", name="Models for the whole instance")).to_be_visible()
    name = f"Local model {uuid4().hex[:6]}"
    page.get_by_role("button", name="Add a model").first.click()
    page.get_by_label("Name", exact=True).fill(name)
    page.get_by_label("Model name").fill("llama3.2")
    page.get_by_label("Endpoint").fill("http://192.168.1.10:11434/v1")
    page.get_by_role("button", name="Save").click()
    expect(page.get_by_text(name)).to_be_visible()
    assert accessibility_violations(page) == []


@pytest.mark.spec("UX-001")
def test_the_app_is_installable(page: Page, member: Account) -> None:
    page.goto("/")
    manifest = page.evaluate("fetch(document.querySelector('link[rel=manifest]').href).then(r => r.json())")
    assert manifest["display"] == "standalone"
    assert {icon["sizes"] for icon in manifest["icons"]} >= {"192x192", "512x512"}
    assert page.evaluate("navigator.serviceWorker.ready.then(r => Boolean(r.active))")


@pytest.mark.spec("UX-001", "UX-007")
def test_on_a_phone_the_list_opens_over_the_conversation(
    browser: Browser, web_origin: str, member: Account, default_model: HarnessModel
) -> None:
    context = browser.new_context(base_url=web_origin, viewport={"width": 390, "height": 844}, has_touch=True)
    page = context.new_page()
    try:
        sign_in(page, member)
        expect(page.get_by_role("link", name="New chat")).to_be_hidden()
        _send(page, "from the phone")
        _answer(page, "Echo: from the phone")
        page.get_by_role("button", name="Open the conversation list").click()
        expect(page.get_by_role("link", name="New chat")).to_be_visible()
        assert accessibility_violations(page) == []
        page.get_by_role("button", name="Close the conversation list").click()
        expect(page.get_by_role("link", name="New chat")).to_be_hidden()
    finally:
        context.close()
