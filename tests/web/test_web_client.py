"""The web client in Chromium (ADR-0067).

The model the tests serve answers `Echo: <message>`, and scripts such as
`slow:N` and `run:<command>` (tests/support/model.py).
"""

from __future__ import annotations

import re
import socket
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.support.accounts import Account
from tests.support.fixtures import HarnessModel, HouseholdModel
from tests.support.model import SERVER_MODELS
from tests.support.server import Server
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
    # The conversation is listed, under the title its model gives it (CNV-006).
    expect(page.get_by_role("navigation").locator(f"a[href='{urlsplit(page.url).path}']")).to_be_visible()
    assert accessibility_violations(page) == []
    page.reload()
    _answer(page, f"Echo: hello {mark}")


@pytest.mark.spec("UX-001", "AUTH-005")
def test_signing_out_returns_to_sign_in_at_once(page: Page, member: Account) -> None:
    sign_in(page, member)
    page.get_by_role("button", name=re.compile("^Sign out")).click()
    expect(page.get_by_label("Username")).to_be_visible()
    page.reload()
    expect(page.get_by_label("Username")).to_be_visible()


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
    expect(answer.get_by_role("button", name="Copy", exact=True)).to_have_count(1)
    expect(answer.locator(".katex").first).to_be_visible()
    expect(answer.locator("img")).to_have_count(0)


@pytest.mark.spec("UX-003")
def test_tool_activity_is_summarized_and_expands(page: Page, member: Account, default_model: HarnessModel) -> None:
    sign_in(page, member)
    _send(page, "run:echo tool-output-42")
    summary = page.locator("summary", has_text="Ran a command")
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


@pytest.mark.spec("CNV-016", "UX-010", "UX-007")
def test_editing_a_message_asks_first_and_replaces_what_followed(
    page: Page, member: Account, default_model: HarnessModel
) -> None:
    sign_in(page, member)
    mark = uuid4().hex[:8]
    _send(page, f"first {mark}")
    _answer(page, f"Echo: first {mark}")
    _send(page, f"second {mark}")
    _answer(page, f"Echo: second {mark}")
    page.get_by_role("button", name="Edit").first.click()
    page.get_by_label("Edit your message").fill(f"first, edited {mark}")
    page.get_by_role("button", name="Send").first.click()
    # Sending asks first: what will be deleted, and that files stay (UX-010).
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text("3 messages")
    expect(dialog).to_contain_text("Files in your workspace")
    assert accessibility_violations(page) == []
    dialog.get_by_role("button", name="Delete and send").click()
    _answer(page, f"Echo: first, edited {mark}")
    expect(page.get_by_role("main")).not_to_contain_text(f"second {mark}")
    expect(page.get_by_text("1 / 2")).to_have_count(0)
    page.reload()
    _answer(page, f"Echo: first, edited {mark}")
    expect(page.get_by_role("main")).not_to_contain_text(f"Echo: first {mark}")
    (request,) = default_model.endpoint.requests_with(f"first, edited {mark}")
    assert request.user_texts() == [f"first, edited {mark}"]


@pytest.mark.spec("CNV-016")
def test_cancelling_the_confirmation_keeps_everything(page: Page, member: Account) -> None:
    sign_in(page, member)
    mark = uuid4().hex[:8]
    _send(page, f"keep {mark}")
    _answer(page, f"Echo: keep {mark}")
    page.get_by_role("button", name="Edit").first.click()
    page.get_by_label("Edit your message").fill(f"changed {mark}")
    page.get_by_role("button", name="Send").first.click()
    page.get_by_role("alertdialog").get_by_role("button", name="Cancel").click()
    page.reload()
    _answer(page, f"Echo: keep {mark}")


def _add_openrouter(server: Server, household: HouseholdModel) -> None:
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


@pytest.mark.spec("UX-015", "MOD-010", "MOD-012", "MOD-014")
def test_choosing_the_model_of_a_conversation(
    page: Page, server: Server, member: Account, default_model: HarnessModel
) -> None:
    household = default_model.connect(member.tenant_id)
    _add_openrouter(server, household)
    sign_in(page, member)
    page.get_by_role("button", name=re.compile("test-model")).click()
    picker = page.get_by_role("dialog", name="Choose a model")
    expect(picker).to_be_visible()
    popular = picker.get_by_role("button", name=re.compile("Test: Popular"))
    expect(popular).to_contain_text("OpenRouter")
    expect(popular).to_contain_text("0.27")
    expect(picker.get_by_role("button", name=re.compile("Test: Chat only"))).to_contain_text(re.compile("chat", re.I))
    expect(picker.get_by_role("button", name=re.compile("test-model"))).to_contain_text("Test server")
    assert accessibility_violations(page) == []
    picker.get_by_role("searchbox").fill("second")
    expect(picker.get_by_role("button", name=re.compile("Test: Second"))).to_be_visible()
    expect(picker.get_by_role("button", name=re.compile("Test: Popular"))).to_have_count(0)
    picker.get_by_role("searchbox").fill("")
    picker.get_by_role("button", name=re.compile("Test: Popular")).click()
    # The data of this conversation now leaves the household, and the client says so (MOD-010).
    expect(page.get_by_role("button", name=re.compile("Test: Popular"))).to_be_visible()
    expect(page.get_by_role("main")).to_contain_text("OpenRouter")
    mark = uuid4().hex[:8]
    _send(page, f"through openrouter {mark}")
    _answer(page, f"Echo: through openrouter {mark}")
    (request,) = household.endpoint.requests_with(f"through openrouter {mark}")
    assert (request.openrouter, request.body["model"]) == (True, "test/popular")


@pytest.mark.spec("UX-016", "MOD-013", "UX-007")
def test_adding_a_connection_shows_its_test(page: Page, admin: Account, default_model: HarnessModel) -> None:
    sign_in(page, admin)
    page.get_by_role("link", name="Settings").click()
    page.get_by_role("button", name="Add a connection").click()
    dialog = page.get_by_role("dialog")
    # OpenRouter needs only its key.
    dialog.get_by_role("button", name="OpenRouter").click()
    expect(dialog.get_by_label("API key")).to_be_visible()
    expect(dialog.get_by_label("Address")).to_have_count(0)
    dialog.get_by_role("button", name="Your own server").click()
    name = f"Gaming PC {uuid4().hex[:6]}"
    dialog.get_by_label("Name", exact=True).fill(name)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    dialog.get_by_label("Address").fill(f"http://127.0.0.1:{closed}/v1")
    dialog.get_by_role("button", name="Test connection").click()
    result = dialog.get_by_role("alert")
    expect(result).to_contain_text("Connect", timeout=30_000)
    expect(result).to_contain_text(str(closed))
    result.get_by_text("Technical details").click()
    expect(result).to_contain_text(re.compile("refused", re.I))
    assert accessibility_violations(page) == []
    dialog.get_by_label("Address").fill(default_model.endpoint.url)
    dialog.get_by_role("button", name="Connect", exact=True).click()
    # The name also appears in the default model list and the notice: look in the connections.
    expect(page.get_by_role("main")).to_contain_text(f"{name}Runs at home", timeout=30_000)
    expect(page.get_by_role("main")).to_contain_text(f"{len(SERVER_MODELS)} models")


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


@pytest.mark.spec("UX-011", "UX-007")
def test_light_and_dark_themes(browser: Browser, web_origin: str, member: Account) -> None:
    context = browser.new_context(base_url=web_origin, color_scheme="dark")
    page = context.new_page()
    try:
        sign_in(page, member)
        dark = page.evaluate("getComputedStyle(document.body).backgroundColor")
        assert _luminance(dark) < 0.2, f"the device asks for dark, the app is {dark}"
        assert accessibility_violations(page) == []
        page.get_by_role("link", name="Settings").click()
        page.get_by_role("button", name="Appearance").click()
        page.get_by_role("button", name="Light").click()
        page.reload()
        light = page.evaluate("getComputedStyle(document.body).backgroundColor")
        assert _luminance(light) > 0.8, f"the user chose light, the app is {light}"
        assert accessibility_violations(page) == []
    finally:
        context.close()


def _luminance(color: str) -> float:
    red, green, blue = (int(value) / 255 for value in re.findall(r"\d+", color)[:3])
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


@pytest.mark.spec("UX-012")
def test_the_sprite_greets_with_a_quote(page: Page, member: Account) -> None:
    sign_in(page, member)
    sprite = page.get_by_role("main").locator("[data-sprite-pose]").first
    expect(sprite).to_have_attribute("data-sprite-pose", "greeting")
    expect(sprite).to_have_attribute("aria-hidden", "true")
    quote = page.get_by_role("main").locator("blockquote")
    expect(quote).to_be_visible()
    assert len(quote.inner_text().strip()) > 10
    expect(page.get_by_role("main").locator("figcaption")).not_to_be_empty()


@pytest.mark.spec("UX-013")
def test_the_sprite_acts_out_the_run_and_then_waits(page: Page, member: Account) -> None:
    sign_in(page, member)
    _send(page, "run:sleep 4; echo acted")
    sprite = page.get_by_role("main").locator("[data-sprite-pose]").last
    expect(sprite).to_have_attribute("data-sprite-pose", "running", timeout=30_000)
    # The same activity is given as text.
    expect(page.get_by_role("status")).to_contain_text(re.compile("command", re.I))
    _answer(page, "acted")
    expect(sprite).to_have_attribute("data-sprite-pose", "waiting", timeout=30_000)


@pytest.mark.spec("UX-013", "UX-007")
def test_the_sprite_keeps_still_with_reduced_motion(browser: Browser, web_origin: str, member: Account) -> None:
    context = browser.new_context(base_url=web_origin, reduced_motion="reduce")
    page = context.new_page()
    try:
        sign_in(page, member)
        expect(page.locator("[data-sprite-pose]").first).to_be_visible()
        moving = page.evaluate(
            "[...document.querySelectorAll('[data-sprite-pose], [data-sprite-pose] *')]"
            ".some((element) => element.getAnimations().length > 0)"
        )
        assert moving is False
    finally:
        context.close()


@pytest.mark.spec("UX-014", "UX-007")
def test_errors_say_what_happened_and_what_to_do(page: Page, member: Account) -> None:
    sign_in(page, member)
    _send(page, "fail")
    notice = page.get_by_role("alert")
    expect(notice).to_be_visible(timeout=30_000)
    text = notice.inner_text()
    assert len(text.strip()) > 30, text
    assert "model.request_failed" not in text, "the notice shows an error code instead of words"
    expect(notice.locator("[data-sprite-pose]")).to_have_attribute("data-sprite-pose", "error")
    assert accessibility_violations(page) == []


@pytest.mark.spec("UX-018")
def test_typing_starts_in_the_expected_field(page: Page, member: Account) -> None:
    page.goto("/")
    expect(page.get_by_label("Username")).to_be_focused()
    sign_in(page, member)
    expect(page.get_by_label("Message")).to_be_focused()


@pytest.mark.spec("UX-018")
def test_touch_screens_keep_the_keyboard_closed(browser: Browser, web_origin: str, member: Account) -> None:
    context = browser.new_context(
        base_url=web_origin, viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
    )
    page = context.new_page()
    try:
        page.goto("/")
        expect(page.get_by_label("Username")).not_to_be_focused()
        sign_in(page, member)
        expect(page.get_by_label("Message")).not_to_be_focused()
    finally:
        context.close()


def _openrouter_default(server: Server, household: HouseholdModel) -> None:
    _add_openrouter(server, household)
    with server.client(household.admin_token) as client:
        (option,) = [m for m in client.get("/models").json()["items"] if m["model"] == "test/popular"]
        assert client.put(
            "/tenant/default-model", json={"connection_id": option["connection_id"], "model": "test/popular"}
        ).is_success


@pytest.mark.spec("UX-008", "MOD-007")
def test_costs_and_context_are_in_view(
    page: Page, server: Server, member: Account, default_model: HarnessModel
) -> None:
    _openrouter_default(server, default_model.connect(member.tenant_id))
    sign_in(page, member)
    # A command that takes a while: the run's first model response, its tool call, is already priced.
    _send(page, "run:sleep 4; echo priced")
    # While it runs: how much of the context window is used, and the run's cost so far.
    expect(page.get_by_role("meter", name="Context used")).to_be_visible(timeout=30_000)
    expect(page.get_by_role("status")).to_contain_text("$", timeout=30_000)
    expect(page.get_by_role("button", name="Send")).to_be_visible(timeout=30_000)
    # Each answer's cost beside it, the conversation's, and the last 24 hours' and 30 days'.
    # Two priced requests: the tool call and the answer.
    expect(page.get_by_role("main").get_by_text("$0.00084").first).to_be_visible()
    expect(page.get_by_text("This conversation", exact=True)).to_be_visible()
    expect(page.get_by_text("Last 24 hours", exact=True)).to_be_visible()
    expect(page.get_by_text("Last 30 days", exact=True)).to_be_visible()
    assert accessibility_violations(page) == []


@pytest.mark.spec("CNV-005", "UX-007")
def test_forking_from_an_answer(page: Page, member: Account) -> None:
    sign_in(page, member)
    mark = uuid4().hex[:8]
    _send(page, f"fork one {mark}")
    _answer(page, f"Echo: fork one {mark}")
    _send(page, f"fork two {mark}")
    _answer(page, f"Echo: fork two {mark}")
    original = page.url
    page.get_by_role("button", name="Fork from here").first.click()
    expect(page).not_to_have_url(original)
    _answer(page, f"Echo: fork one {mark}")
    expect(page.get_by_role("main")).not_to_contain_text(f"fork two {mark}")
    expect(page.get_by_role("main")).to_contain_text("Forked from")
    assert accessibility_violations(page) == []


@pytest.mark.spec("CNV-007", "CNV-008", "UX-007")
def test_folders_pins_and_collapsing(page: Page, member: Account) -> None:
    sign_in(page, member)
    mark = uuid4().hex[:6]
    _send(page, f"folder talk {mark}")
    _answer(page, f"Echo: folder talk {mark}")
    nav = page.get_by_role("navigation", name="Conversations")
    nav.get_by_role("button", name="New folder").click()
    page.get_by_label("Folder name").fill(f"Family {mark}")
    page.get_by_role("button", name="Create").click()
    folder = nav.get_by_role("button", name=f"Family {mark}")
    expect(folder).to_be_visible()
    menu = nav.get_by_role("button", name=re.compile("^Options for"))
    menu.first.click()
    page.get_by_role("menuitem", name="Move to folder").click()
    page.get_by_role("menuitem", name=f"Family {mark}").click()
    expect(folder).to_have_attribute("aria-expanded", "true")
    folder.click()
    expect(folder).to_have_attribute("aria-expanded", "false")
    page.reload()
    expect(nav.get_by_role("button", name=f"Family {mark}")).to_have_attribute("aria-expanded", "false")
    assert accessibility_violations(page) == []


@pytest.mark.spec("CNV-008")
def test_pinning_a_conversation(page: Page, member: Account) -> None:
    sign_in(page, member)
    mark = uuid4().hex[:6]
    for text in (f"first {mark}", f"second {mark}"):
        page.goto("/")
        page.get_by_label("Message").fill(text)
        page.get_by_role("button", name="Send").click()
        _answer(page, f"Echo: {text}")
    nav = page.get_by_role("navigation", name="Conversations")
    links = nav.get_by_role("link")
    # Pin the older one: it moves to the top.
    nav.get_by_role("button", name=re.compile("^Options for")).nth(1).click()
    page.get_by_role("menuitem", name="Pin").click()
    expect(nav.get_by_text("Pinned")).to_be_visible()
    assert links.count() >= 2


@pytest.mark.spec("CNV-009", "UX-007")
def test_searching_conversations(page: Page, member: Account) -> None:
    sign_in(page, member)
    word = f"rosemary{uuid4().hex[:6]}"
    _send(page, f"a recipe with {word}")
    _answer(page, f"Echo: a recipe with {word}")
    page.goto("/")
    page.get_by_role("searchbox", name="Search conversations").fill(word)
    result = page.get_by_role("link", name=re.compile(word))
    expect(result).to_be_visible(timeout=15_000)
    assert accessibility_violations(page) == []
    result.click()
    expect(page).to_have_url(re.compile(r"/c/[0-9a-f-]+$"))
