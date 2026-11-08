"""Temporary conversations in the web client (CNV-011, ADR-0082)."""

from __future__ import annotations

import re
import time

import pytest
from playwright.sync_api import Page, expect

from tests.support.accounts import Account, login
from tests.support.fixtures import HarnessModel
from tests.support.server import Server
from tests.web.conftest import accessibility_violations, sign_in


def _start_temporary(page: Page, text: str) -> str:
    """Start a temporary chat with `text`, and its conversation ID once answered."""
    toggle = page.get_by_role("button", name="Temporary chat")
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "true")
    page.get_by_label("Message").fill(text)
    page.get_by_role("button", name="Send").click()
    expect(page.get_by_role("main")).to_contain_text(f"Echo: {text}", timeout=30_000)
    match = re.search(r"/c/([0-9a-f-]+)", page.url)
    assert match is not None, page.url
    return match.group(1)


def _wait_until_deleted(server: Server, member: Account, conversation_id: str) -> None:
    token = login(server, member)
    deadline = time.monotonic() + 10
    with server.client(token) as client:
        while client.get(f"/conversations/{conversation_id}").status_code != 404:
            assert time.monotonic() < deadline, "the temporary conversation was not deleted"
            time.sleep(0.25)


@pytest.mark.spec("CNV-011", "UX-007")
def test_a_temporary_chat_is_deleted_when_left(
    page: Page, server: Server, member: Account, default_model: HarnessModel
) -> None:
    sign_in(page, member)
    conversation_id = _start_temporary(page, "just between us")
    # It says so while it is open, and it is not in the list.
    expect(page.get_by_role("main")).to_contain_text("deleted when you leave")
    listed = page.get_by_role("navigation", name="Conversations").locator(f'a[href="/c/{conversation_id}"]')
    expect(listed).to_have_count(0)
    assert accessibility_violations(page) == []
    # A reload is not leaving.
    page.reload()
    expect(page.get_by_role("main")).to_contain_text("Echo: just between us", timeout=30_000)
    page.get_by_role("link", name="New chat").click()
    _wait_until_deleted(server, member, conversation_id)
    # The new chat is a normal one again.
    expect(page.get_by_role("button", name="Temporary chat")).to_have_attribute("aria-pressed", "false")


@pytest.mark.spec("CNV-011")
def test_signing_out_deletes_a_temporary_chat(
    page: Page, server: Server, member: Account, default_model: HarnessModel
) -> None:
    sign_in(page, member)
    conversation_id = _start_temporary(page, "before signing out")
    page.get_by_role("button", name="Sign out").click()
    expect(page.get_by_role("button", name="Sign in")).to_be_visible()
    _wait_until_deleted(server, member, conversation_id)
