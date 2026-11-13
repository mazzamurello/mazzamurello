"""Local models only, in the web client (UX-024, MOD-003, ADR-0091).

Each household reaches the model the tests serve through a server whose
inference runs locally and, here, through OpenRouter, which runs remotely
(tests/support/model.py).
"""

from __future__ import annotations

import re
import secrets
from uuid import uuid4

import pytest
from playwright.sync_api import Page, expect

from tests.support.accounts import Account, create_account
from tests.support.database import Database
from tests.support.fixtures import HarnessModel, HouseholdModel
from tests.support.server import Server
from tests.web.conftest import accessibility_violations, sign_in

REASON = re.compile("only local models", re.IGNORECASE)


def _openrouter(server: Server, household: HouseholdModel) -> str:
    """Give the household OpenRouter, with its speech models: the new connection."""
    with server.client(household.admin_token) as client:
        created = client.post(
            "/tenant/connections",
            json={
                "name": "OpenRouter",
                "kind": "openrouter",
                "base_url": household.endpoint.openrouter_url,
                "api_key": f"sk-or-v1-{secrets.token_hex(8)}",
            },
        )
        assert created.status_code == 201, created.text
        connection_id: str = created.json()["id"]
        response = client.put(
            "/tenant/speech",
            json={
                "transcription": {"connection_id": connection_id, "model": "test/transcribe"},
                "speech": {"connection_id": connection_id, "model": "test/voice", "voice": "nova"},
            },
        )
        assert response.status_code == 200, response.text
    return connection_id


def _send(page: Page, text: str) -> None:
    page.get_by_label("Message").fill(text)
    page.get_by_role("button", name="Send").click()


@pytest.mark.spec("UX-024", "MOD-003", "UX-015", "UX-007")
def test_a_member_keeps_their_chats_at_home(
    page: Page, server: Server, member: Account, default_model: HarnessModel
) -> None:
    _openrouter(server, default_model.connect(member.tenant_id))
    sign_in(page, member)
    # A chat on a remote model, before the choice.
    page.get_by_role("button", name=re.compile("test-model")).click()
    picker = page.get_by_role("dialog", name="Choose a model")
    picker.get_by_role("button", name=re.compile("Test: Popular")).click()
    mark = uuid4().hex[:8]
    _send(page, f"before {mark}")
    main = page.get_by_role("main")
    expect(main).to_contain_text(f"Echo: before {mark}", timeout=30_000)
    chat_url = page.url
    # The choice, among the member's own settings.
    page.get_by_role("link", name="Settings").click()
    assistant = page.get_by_role("region", name="Assistant")
    switch = assistant.get_by_role("switch", name="Use only local models")
    expect(switch).not_to_be_checked()
    switch.check()
    expect(assistant).to_contain_text("Saved")
    assert accessibility_violations(page) == []
    # The chat says its model is no longer allowed, before anything is sent.
    page.goto(chat_url)
    expect(main).to_contain_text(REASON, timeout=30_000)
    # The picker shows remote models as unavailable, saying why.
    page.get_by_role("button", name=re.compile("Test: Popular")).click()
    expect(picker.get_by_role("button", name=re.compile("Test: Popular"))).to_be_disabled()
    expect(picker).to_contain_text(REASON)
    assert accessibility_violations(page) == []
    # A local model answers.
    picker.get_by_role("button", name=re.compile("test-model")).click()
    _send(page, f"after {mark}")
    expect(main).to_contain_text(f"Echo: after {mark}", timeout=30_000)
    # Voice uses the household's remote speech models: unavailable, saying why.
    dictate = page.get_by_role("button", name="Dictate")
    expect(dictate).to_be_disabled()
    expect(dictate).to_have_accessible_description(REASON)


@pytest.mark.spec("UX-024", "MOD-003", "UX-015", "UX-007")
def test_a_household_admin_chooses_local_models_only(
    page: Page, server: Server, database: Database, admin: Account, default_model: HarnessModel
) -> None:
    household = default_model.connect(admin.tenant_id)
    _openrouter(server, household)
    member = create_account(database, admin.tenant_id)
    sign_in(page, admin)
    page.get_by_role("link", name="Settings").click()
    sections = page.get_by_role("navigation", name="Settings sections")
    # For one member, with their tool permissions.
    sections.get_by_role("group", name="Household").get_by_role("button", name="Tool permissions").click()
    permissions = page.get_by_role("region", name="Tool permissions")
    permissions.get_by_label("User").select_option(label=member.username)
    for_member = permissions.get_by_role("switch", name="Only local models")
    expect(for_member).not_to_be_checked()
    for_member.check()
    expect(permissions).to_contain_text("Saved")
    assert accessibility_violations(page) == []
    # The member finds it chosen, and locked.
    page.context.clear_cookies()
    sign_in(page, member)
    page.get_by_role("link", name="Settings").click()
    own = page.get_by_role("region", name="Assistant").get_by_role("switch", name="Use only local models")
    expect(own).to_be_checked()
    expect(own).to_be_disabled()
    expect(page.get_by_role("main")).to_contain_text("Your household's admin chose only local models for you.")
    # For the whole household, among its models.
    page.context.clear_cookies()
    sign_in(page, admin)
    page.get_by_role("link", name="Settings").click()
    sections.get_by_role("group", name="Household").get_by_role("button", name="Models").click()
    everyone = page.get_by_role("main").get_by_role("switch", name="Only local models for everyone")
    expect(everyone).not_to_be_checked()
    everyone.check()
    expect(page.get_by_role("main")).to_contain_text("Saved")
    assert accessibility_violations(page) == []
    sections.get_by_role("group", name="Yours").get_by_role("button", name="Assistant").click()
    own = page.get_by_role("region", name="Assistant").get_by_role("switch", name="Use only local models")
    expect(own).to_be_checked()
    expect(own).to_be_disabled()
    expect(page.get_by_role("main")).to_contain_text("Your household uses only local models.")
