"""Voice turns in the web client: dictation, reading aloud and hands-free mode (UX-005, ADR-0088).

The model the tests serve transcribes any recording as `Heard <bytes> bytes of
<format>` and speaks silence; Chromium records a tone from a fake microphone
(tests/support/model.py, specs/contracts/test-harness.md).
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Iterator

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.support.accounts import Account
from tests.support.fixtures import HarnessModel, HouseholdModel
from tests.support.server import Server
from tests.web.conftest import accessibility_violations, sign_in

# Records every sound the hands-free button plays, in order.
WATCH_CUES = """() => {
    window.__cues = [];
    new MutationObserver((changes) => {
        for (const change of changes) {
            const cue = change.target.getAttribute("data-voice-cue");
            if (cue) window.__cues.push(cue);
        }
    }).observe(document.body, {subtree: true, attributes: true, attributeFilter: ["data-voice-cue"]});
}"""


@pytest.fixture
def page(page: Page) -> Iterator[Page]:
    """The page, failing its test if the app logs an error, such as audio it may not play."""
    errors: list[str] = []
    # A failed request the test arranges is logged by the browser, not the app.
    page.on(
        "console",
        lambda message: (
            errors.append(message.text)
            if message.type == "error" and not message.text.startswith("Failed to load resource")
            else None
        ),
    )
    yield page
    assert errors == []


def _speech(server: Server, household: HouseholdModel, *, remote: bool = False) -> None:
    """Give the household its speech models: the test server's, or OpenRouter's."""
    with server.client(household.admin_token) as client:
        connection_id = household.connection_id
        if remote:
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
            connection_id = created.json()["id"]
        settings = {
            "transcription": {
                "connection_id": connection_id,
                "model": "test/transcribe" if remote else "test-transcribe",
            },
            "speech": {
                "connection_id": connection_id,
                "model": "test/voice" if remote else "test-tts",
                "voice": "nova",
            },
        }
        response = client.put("/tenant/speech", json=settings)
        assert response.status_code == 200, response.text


def _send(page: Page, text: str) -> None:
    page.get_by_label("Message").fill(text)
    page.get_by_role("button", name="Send").click()


def _answer(page: Page, text: str | re.Pattern[str]) -> None:
    expect(page.get_by_role("main")).to_contain_text(text, timeout=30_000)


@pytest.mark.spec("UX-005")
def test_without_speech_models_there_is_no_voice(page: Page, member: Account) -> None:
    sign_in(page, member)
    _send(page, "quiet please")
    _answer(page, "Echo: quiet please")
    expect(page.get_by_role("button", name="Dictate")).to_have_count(0)
    expect(page.get_by_role("button", name="Hands-free")).to_have_count(0)
    expect(page.get_by_role("button", name="Read aloud")).to_have_count(0)


@pytest.mark.spec("UX-005", "API-006", "UX-007")
def test_dictation_puts_the_spoken_turn_in_the_message_box(
    page: Page, server: Server, member: Account, default_model: HarnessModel
) -> None:
    household = default_model.connect(member.tenant_id)
    _speech(server, household)
    sign_in(page, member)
    page.get_by_role("button", name="Dictate").click()
    # In the message box: the voice as it is captured, and a button to stop.
    box = page.locator("form").filter(has=page.get_by_role("img", name="Your voice, as it is captured"))
    expect(box).to_be_visible()
    stop = box.get_by_role("button", name="Stop dictating")
    expect(stop).to_be_visible()
    assert accessibility_violations(page) == []
    page.wait_for_timeout(800)
    stop.click()
    # Shown as it was heard, for the user to review: nothing is sent.
    expect(page.get_by_label("Message")).to_have_value(re.compile(r"^Heard \d+ bytes of \w+$"), timeout=15_000)
    assert household.endpoint.speech("/audio/transcriptions")[-1].body["model"] == "test-transcribe"
    expect(page.get_by_role("main").get_by_role("listitem")).to_have_count(0)
    # Sent, the assistant is told it was dictated.
    said = page.get_by_label("Message").input_value()
    page.get_by_role("button", name="Send").click()
    _answer(page, f"Echo: {said}")
    assert "dictated" in household.endpoint.requests_with(said)[0].system_text()


@pytest.mark.spec("UX-005", "UX-007")
def test_an_answer_is_read_aloud_naming_what_is_not_read(
    page: Page, server: Server, member: Account, default_model: HarnessModel
) -> None:
    household = default_model.connect(member.tenant_id)
    _speech(server, household)
    sign_in(page, member)
    _send(page, "Here is the script.\n\n```python\nprint('not read')\n```\n\nThat is all.")
    _answer(page, "That is all.")
    page.get_by_role("button", name="Read aloud").click()
    expect(page.get_by_role("button", name="Stop reading")).to_be_visible()
    assert accessibility_violations(page) == []
    expect(page.get_by_role("button", name="Read aloud")).to_be_visible(timeout=15_000)
    said = " ".join(str(r.body["input"]) for r in household.endpoint.speech("/audio/speech"))
    assert "Here is the script." in said
    assert "That is all." in said
    assert "not read" not in said
    assert "code" in said.lower()
    assert "```" not in said


def _hands_free(page: Page) -> Locator:
    page.get_by_role("button", name="Hands-free").click()
    button = page.locator("[data-voice-state]")
    expect(button).to_have_attribute("data-voice-state", "idle")
    return button


@pytest.mark.spec("UX-005", "UX-007")
def test_hands_free_turns_with_one_large_button_and_sounds(
    page: Page, server: Server, member: Account, default_model: HarnessModel
) -> None:
    household = default_model.connect(member.tenant_id)
    _speech(server, household)
    sign_in(page, member)
    page.evaluate(WATCH_CUES)
    button = _hands_free(page)
    # Large enough not to miss.
    box = button.bounding_box()
    viewport = page.viewport_size
    assert box is not None
    assert viewport is not None
    assert box["width"] >= viewport["width"] * 0.5
    assert box["height"] >= 200
    # Above the button, the sprite acts out what happens.
    sprite = page.locator("[data-sprite-pose]").last
    sprite_box = sprite.bounding_box()
    assert sprite_box is not None
    assert sprite_box["y"] + sprite_box["height"] <= box["y"] + 1
    assert accessibility_violations(page) == []
    button.click()
    expect(button).to_have_attribute("data-voice-state", "listening")
    expect(sprite).to_have_attribute("data-sprite-pose", "listening")
    # The screen shows that the microphone hears, as dictation does, on the button.
    level = page.get_by_role("region", name="Hands-free").get_by_role("img", name="Your voice, as it is captured")
    expect(level).to_be_visible()
    level_box = level.bounding_box()
    assert level_box is not None
    assert box["y"] <= level_box["y"] <= box["y"] + box["height"]
    page.wait_for_timeout(800)
    button.click()
    # Sent at once, answered, and read aloud.
    _answer(page, re.compile(r"Echo: Heard \d+ bytes"))
    expect(button).to_have_attribute("data-voice-state", "reading", timeout=30_000)
    # Once the answer is read, the next turn starts by itself, with the sound of a turn starting.
    expect(button).to_have_attribute("data-voice-state", "listening", timeout=30_000)
    said = " ".join(str(r.body["input"]) for r in household.endpoint.speech("/audio/speech"))
    assert "Echo: Heard" in said
    # The assistant was told its answer is read aloud.
    sent = re.search(r"Echo: (Heard \d+ bytes of \w+)", said)
    assert sent is not None
    assert "read aloud" in household.endpoint.requests_with(sent.group(1))[0].system_text()
    cues: list[str] = page.evaluate("window.__cues")
    assert cues[:2] == ["start", "end"]
    assert cues[-2:] == ["answer", "start"]


@pytest.mark.spec("UX-005", "UX-007")
def test_hands_free_mode_says_which_step_a_turn_is_at_and_why_it_failed(
    page: Page, server: Server, member: Account, default_model: HarnessModel
) -> None:
    _speech(server, default_model.connect(member.tenant_id))
    sign_in(page, member)
    # A speech model that fails, as one that takes too long does.
    detail = "The speech model took more than 120 seconds to answer."
    page.route(
        "**/v1/speech/synthesis",
        lambda route: route.fulfill(
            status=502,
            content_type="application/problem+json",
            body=json.dumps(
                {
                    "type": "about:blank",
                    "title": "Speech failed",
                    "status": 502,
                    "code": "model.request_failed",
                    "detail": detail,
                }
            ),
        ),
    )
    region = page.get_by_role("region", name="Hands-free")
    button = _hands_free(page)
    button.click()
    expect(region.get_by_role("status")).to_contain_text("Listening")
    page.wait_for_timeout(600)
    button.click()
    # Each step in words, with how long it has taken.
    expect(region.get_by_role("status")).to_contain_text(
        re.compile(r"(Transcribing|Writing the answer|Preparing the voice)")
    )
    expect(region.get_by_role("status")).to_contain_text(re.compile(r"\d+ s"))
    # The step that failed, and why.
    expect(button).to_have_attribute("data-voice-state", "failed", timeout=30_000)
    expect(region).to_contain_text("Preparing the voice failed")
    expect(region).to_contain_text(detail)
    assert accessibility_violations(page) == []


@pytest.mark.spec("UX-005")
def test_media_buttons_start_and_end_a_turn_and_stop_the_reading(
    page: Page, server: Server, member: Account, default_model: HarnessModel
) -> None:
    household = default_model.connect(member.tenant_id)
    _speech(server, household)
    sign_in(page, member)
    # The served model is shared by every test of the session.
    before = len(household.endpoint.speech("/audio/transcriptions"))
    button = _hands_free(page)
    page.keyboard.press("MediaTrackNext")
    expect(button).to_have_attribute("data-voice-state", "listening")
    page.wait_for_timeout(800)
    page.keyboard.press("MediaTrackNext")
    _answer(page, re.compile(r"Echo: Heard \d+ bytes"))
    # A press while the answer is read stops the reading and starts the next turn.
    expect(button).to_have_attribute("data-voice-state", "reading", timeout=30_000)
    page.keyboard.press("MediaPlayPause")
    expect(button).to_have_attribute("data-voice-state", "listening")
    page.wait_for_timeout(500)
    page.keyboard.press("MediaTrackNext")
    # The second turn is answered and read in turn, and the third starts by itself.
    expect(button).to_have_attribute("data-voice-state", "reading", timeout=30_000)
    expect(button).to_have_attribute("data-voice-state", "listening", timeout=30_000)
    assert len(household.endpoint.speech("/audio/transcriptions")) - before == 2


@pytest.mark.spec("UX-005", "MOD-010")
def test_remote_speech_is_said_to_be_remote(
    page: Page, server: Server, member: Account, default_model: HarnessModel
) -> None:
    _speech(server, default_model.connect(member.tenant_id), remote=True)
    sign_in(page, member)
    _hands_free(page)
    expect(page.get_by_role("main")).to_contain_text("Your voice goes to OpenRouter.")


@pytest.mark.spec("UX-005", "UX-007")
def test_hands_free_mode_fills_a_phones_screen(
    page: Page, server: Server, member: Account, default_model: HarnessModel
) -> None:
    _speech(server, default_model.connect(member.tenant_id))
    page.set_viewport_size({"width": 390, "height": 844})
    sign_in(page, member)
    button = _hands_free(page)
    box = button.bounding_box()
    assert box is not None
    # The lower half of the screen, the sprite above it.
    assert box["width"] >= 300
    assert box["height"] >= 844 * 0.35
    assert box["y"] >= 844 * 0.4
    assert accessibility_violations(page) == []
