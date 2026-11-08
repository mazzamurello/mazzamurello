"""Questions to the user and the task list in the web client (AGT-015, UX-009, ADR-0083).

The model the tests serve calls the tool named in a message `tool:<name> <arguments>`, then answers
`Tool said: <result>` (tests/support/model.py).
"""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Browser, Page, expect

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
# Two questions, with long options, as a model asks them.
TWO_QUESTIONS = {
    "questions": [
        {
            "header": "Topic",
            "question": "What should this piece of work be about?",
            "options": [
                {"label": f"Topic {n}", "description": "A longer description of what the option means. " * 3}
                for n in range(1, 7)
            ],
            "multi_select": False,
        },
        {
            "header": "Format",
            "question": "How should the result be delivered?",
            "options": [{"label": "PDF"}, {"label": "Markdown"}],
            "multi_select": False,
        },
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


@pytest.mark.spec("AGT-015", "UX-009", "UX-007")
def test_several_questions_are_shown_one_at_a_time(
    browser: Browser, web_origin: str, member: Account, default_model: HarnessModel
) -> None:
    # On a phone, where long questions used to push the buttons out of reach.
    context = browser.new_context(base_url=web_origin, viewport={"width": 390, "height": 700})
    page = context.new_page()
    try:
        sign_in(page, member)
        _send(page, f"tool:ask_user_question {json.dumps(TWO_QUESTIONS)}")
        asks = page.get_by_role("region", name="The assistant asks")
        expect(asks).to_contain_text("1 of 2", timeout=30_000)
        expect(asks).to_contain_text("What should this piece of work be about?")
        expect(asks).not_to_contain_text("How should the result be delivered?")
        answer, skip = asks.get_by_role("button", name="Answer"), asks.get_by_role("button", name="Skip")
        next_one = asks.get_by_role("button", name="Next", exact=True)
        # Before the last question: Skip, and Next once the question is answered.
        expect(next_one).to_be_in_viewport()
        expect(next_one).to_be_disabled()
        expect(skip).to_be_in_viewport()
        expect(answer).to_have_count(0)
        assert accessibility_violations(page) == []
        # Picking a choice stays on the question; Next moves on, the arrows move back and forth.
        asks.get_by_role("radio", name="Topic 6").check()
        expect(asks).to_contain_text("1 of 2")
        expect(next_one).to_be_enabled()
        next_one.click()
        expect(asks).to_contain_text("2 of 2")
        expect(asks).to_contain_text("How should the result be delivered?")
        # On the last: Answer, once it is answered.
        expect(next_one).to_have_count(0)
        expect(answer).to_be_disabled()
        asks.get_by_role("button", name="Previous question").click()
        expect(asks.get_by_role("radio", name="Topic 6")).to_be_checked()
        asks.get_by_role("button", name="Next question").click()
        expect(asks).to_contain_text("2 of 2")
        asks.get_by_role("radio", name="PDF").check()
        expect(answer).to_be_enabled()
        expect(answer).to_be_in_viewport()
        answer.click()
        expect(page.get_by_role("main")).to_contain_text("Tool said:", timeout=30_000)
        expect(page.get_by_role("main")).to_contain_text("Topic 6")
        expect(page.get_by_role("main")).to_contain_text("PDF")
    finally:
        context.close()
