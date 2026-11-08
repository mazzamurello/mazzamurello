"""Questions to the user and the task list in the web client (AGT-015, UX-009, ADR-0083).

The model the tests serve calls the tool named in a message `tool:<name> <arguments>`, then answers
`Tool said: <result>` (tests/support/model.py).
"""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, expect

from tests.support.accounts import Account
from tests.support.fixtures import HarnessModel
from tests.web.conftest import accessibility_violations, sign_in

QUESTION = {
    "questions": [
        {
            "header": "Colour",
            "question": "Which colour do you like?",
            "options": [{"label": "Red"}, {"label": "Blue", "description": "Like the sea"}],
            "multi_select": False,
        }
    ]
}
STEPS = [
    {"id": "find", "content": "Find the file", "status": "completed"},
    {"id": "sum", "content": "Summarize it", "status": "in_progress", "active_form": "Summarizing it"},
]


def _send(page: Page, text: str) -> None:
    page.get_by_label("Message").fill(text)
    page.get_by_role("button", name="Send").click()


@pytest.mark.spec("AGT-015", "UX-009", "UX-007")
def test_a_question_is_answered_with_its_choices(page: Page, member: Account, default_model: HarnessModel) -> None:
    sign_in(page, member)
    _send(page, f"tool:ask_user_question {json.dumps(QUESTION)}")
    asks = page.get_by_role("region", name="The assistant asks")
    expect(asks).to_contain_text("Which colour do you like?", timeout=30_000)
    expect(asks).to_contain_text("Like the sea")
    # It takes the message box's place until it is answered.
    expect(page.get_by_label("Message")).to_have_count(0)
    assert accessibility_violations(page) == []
    asks.get_by_role("radio", name="Blue").check()
    asks.get_by_role("button", name="Answer").click()
    expect(page.get_by_role("main")).to_contain_text("Tool said:", timeout=30_000)
    expect(page.get_by_role("main")).to_contain_text("Blue")
    expect(page.get_by_label("Message")).to_be_visible()


@pytest.mark.spec("AGT-015", "UX-009")
def test_a_question_waits_for_its_answer_and_can_be_skipped(
    page: Page, member: Account, default_model: HarnessModel
) -> None:
    sign_in(page, member)
    _send(page, f"tool:ask_user_question {json.dumps(QUESTION)}")
    asks = page.get_by_role("region", name="The assistant asks")
    expect(asks).to_be_visible(timeout=30_000)
    # Opened again later, the conversation still asks.
    page.reload()
    expect(asks).to_contain_text("Which colour do you like?", timeout=30_000)
    asks.get_by_role("button", name="Skip").click()
    expect(page.get_by_role("main")).to_contain_text("The user declined", timeout=30_000)
    expect(asks).to_have_count(0)


@pytest.mark.spec("UX-009", "UX-007")
def test_the_task_list_shows_how_far_the_assistant_got(
    page: Page, member: Account, default_model: HarnessModel
) -> None:
    sign_in(page, member)
    _send(page, f"tool:write_plan {json.dumps({'items': STEPS})}")
    steps = page.get_by_role("list", name="Task list")
    expect(steps).to_contain_text("Find the file", timeout=30_000)
    expect(steps.get_by_role("listitem")).to_have_count(2)
    expect(steps.get_by_role("listitem").first).to_contain_text("Done")
    expect(steps.get_by_role("listitem").last).to_contain_text("Summarizing it")
    assert accessibility_violations(page) == []
    # Kept with the conversation.
    page.reload()
    expect(steps).to_contain_text("Summarizing it", timeout=30_000)
