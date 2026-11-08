"""Conversation settings and instructions in the web client (CNV-013, CNV-014, ADR-0081).

The model the tests serve reasons when a message starts with `think:`
(tests/support/model.py).
"""

from __future__ import annotations

import re
import uuid
from uuid import uuid4

import pytest
from playwright.sync_api import Page, expect

from tests.support.accounts import Account
from tests.support.fixtures import HarnessModel
from tests.support.model import ModelRequest
from tests.support.server import Server
from tests.web.conftest import accessibility_violations, sign_in


def _send(page: Page, text: str) -> None:
    page.get_by_label("Message").fill(text)
    page.get_by_role("button", name="Send").click()


def _answer(page: Page, text: str) -> None:
    expect(page.get_by_role("main")).to_contain_text(text, timeout=30_000)


def _request(page: Page, model: HarnessModel, text: str) -> ModelRequest:
    _send(page, text)
    _answer(page, f"Echo: {text}")
    return model.endpoint.requests_with(text)[0]


def _add_openrouter(server: Server, model: HarnessModel, tenant_id: uuid.UUID) -> None:
    household = model.connect(tenant_id)
    with server.client(household.admin_token) as client:
        response = client.post(
            "/tenant/connections",
            json={
                "name": "OpenRouter",
                "kind": "openrouter",
                "base_url": household.endpoint.openrouter_url,
                "api_key": f"sk-or-v1-{uuid4().hex}",
            },
        )
    assert response.status_code == 201, response.text


@pytest.mark.spec("CNV-013", "CNV-014", "UX-007")
def test_my_defaults_shape_every_new_chat(page: Page, member: Account, default_model: HarnessModel) -> None:
    sign_in(page, member)
    page.get_by_role("link", name="Settings").click()
    assistant = page.get_by_role("region", name="Assistant")
    expect(assistant).to_be_visible()
    assistant.get_by_role("radio", name="Deep").check()
    assistant.get_by_role("switch", name="Search the web").uncheck()
    mark = uuid4().hex[:8]
    additional = assistant.get_by_label("Additional prompt")
    additional.fill(f"Sign as Ada {mark}.")
    # The system prompt comes last, set apart, and starts from the built-in one.
    danger = assistant.get_by_role("region", name="Danger zone")
    system_prompt = danger.get_by_label("System prompt")
    expect(system_prompt).to_have_value(re.compile("^You are Mazzamurello"))
    additional_box, danger_box = additional.bounding_box(), danger.bounding_box()
    assert additional_box is not None
    assert danger_box is not None
    assert additional_box["y"] < danger_box["y"]
    assistant.get_by_role("button", name="Save prompts").click()
    expect(assistant).to_contain_text("Saved")
    assert accessibility_violations(page) == []
    page.get_by_role("link", name="New chat").click()
    request = _request(page, default_model, f"with my defaults {mark}")
    assert request.reasoning_effort() == "high"
    assert "web_search" not in request.tool_names()
    assert f"Sign as Ada {mark}." in request.system_text()


@pytest.mark.spec("CNV-013", "CNV-014", "UX-007")
def test_changing_the_settings_of_one_chat(page: Page, member: Account, default_model: HarnessModel) -> None:
    sign_in(page, member)
    mark = uuid4().hex[:8]
    _request(page, default_model, f"first {mark}")
    page.get_by_role("button", name="Chat settings").click()
    dialog = page.get_by_role("dialog", name="Chat settings")
    expect(dialog).to_be_visible()
    dialog.get_by_role("radio", name="Off").check()
    dialog.get_by_role("switch", name="Run commands").uncheck()
    system_prompt = dialog.get_by_role("region", name="Danger zone").get_by_label("System prompt")
    expect(system_prompt).to_have_value(re.compile("^You are Mazzamurello"))
    system_prompt.fill(f"You are Bea {mark}.")
    assert accessibility_violations(page) == []
    dialog.get_by_role("button", name="Save").click()
    expect(dialog).to_have_count(0)
    request = _request(page, default_model, f"second {mark}")
    assert request.reasoning_effort() == "none"
    assert "run_command" not in request.tool_names()
    system = request.system_text()
    assert f"You are Bea {mark}." in system
    assert "You are Mazzamurello" not in system
    # Restoring the default brings back the built-in system prompt.
    page.get_by_role("button", name="Chat settings").click()
    expect(system_prompt).to_have_value(f"You are Bea {mark}.")
    dialog.get_by_role("button", name="Restore the default system prompt").click()
    expect(system_prompt).to_have_value(re.compile("^You are Mazzamurello"))
    dialog.get_by_role("button", name="Save").click()
    assert "You are Mazzamurello" in _request(page, default_model, f"third {mark}").system_text()


@pytest.mark.spec("CNV-013")
def test_reasoning_is_disabled_for_models_that_cannot_reason(
    page: Page, server: Server, member: Account, default_model: HarnessModel
) -> None:
    _add_openrouter(server, default_model, member.tenant_id)
    sign_in(page, member)
    _request(page, default_model, f"choose {uuid4().hex[:8]}")
    page.get_by_role("button", name=re.compile("test-model")).click()
    page.get_by_role("dialog", name="Choose a model").get_by_role("button", name=re.compile("Test: Second")).click()
    page.get_by_role("button", name="Chat settings").click()
    dialog = page.get_by_role("dialog", name="Chat settings")
    expect(dialog.get_by_role("switch", name="Run commands")).to_be_visible()
    reasoning = dialog.get_by_role("radiogroup", name="Reasoning")
    expect(reasoning).to_be_visible()
    for level in ("Off", "On", "Deep"):
        expect(reasoning.get_by_role("radio", name=level)).to_be_disabled()
    expect(dialog).to_contain_text("This model can't reason.")
    assert accessibility_violations(page) == []


@pytest.mark.spec("CNV-013", "UX-007")
def test_the_reasoning_is_folded_above_the_answer(page: Page, member: Account) -> None:
    sign_in(page, member)
    mark = uuid4().hex[:8]
    _send(page, f"think:{mark}")
    _answer(page, f"Echo: think:{mark}")
    summary = page.locator("summary", has_text="Reasoning")
    expect(summary).to_be_visible()
    expect(page.locator("details[open]")).to_have_count(0)
    # Above the answer.
    answer = page.get_by_role("main").get_by_text(f"Echo: think:{mark}")
    summary_box, answer_box = summary.bounding_box(), answer.bounding_box()
    assert summary_box is not None
    assert answer_box is not None
    assert summary_box["y"] < answer_box["y"]
    summary.click()
    expect(page.locator("details[open]")).to_contain_text(f"Thinking: {mark}")
    assert accessibility_violations(page) == []
    # Also from the history.
    page.reload()
    expect(page.locator("summary", has_text="Reasoning")).to_be_visible(timeout=30_000)
