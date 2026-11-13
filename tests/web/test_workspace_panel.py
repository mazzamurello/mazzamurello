"""Files in a conversation, in the web client, and the viewer of artifacts (UX-019, UX-020, CNV-017, AGT-023,
ART-001, ART-002, ART-003, ADR-0079, ADR-0086)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.support.accounts import Account
from tests.web.conftest import accessibility_violations, sign_in


def _send(page: Page, text: str) -> None:
    page.get_by_label("Message").fill(text)
    page.get_by_role("button", name="Send").click()


def _conversation_id(page: Page) -> str:
    page.wait_for_url(re.compile(r"/c/[0-9a-f-]+$"), timeout=30_000)
    return page.url.rsplit("/", 1)[-1]


def _attach(page: Page, tmp_path: Path, name: str, text: str) -> None:
    file = tmp_path / name
    file.write_text(text)
    page.get_by_label("Attach files").set_input_files(str(file))
    # It uploads at once; the chip says so when it is done.
    expect(page.get_by_role("listitem").filter(has_text=name)).to_be_visible(timeout=30_000)


def _open_panel(page: Page) -> None:
    page.get_by_role("button", name="Files").click()
    expect(page.get_by_role("tree", name="Workspace")).to_be_visible()


@pytest.mark.spec("CNV-017", "UX-019")
def test_an_attached_file_reaches_the_workspace_and_the_history(page: Page, member: Account, tmp_path: Path) -> None:
    sign_in(page, member)
    _attach(page, tmp_path, "shopping.txt", "tomatoes\nbasil\n")
    _send(page, "what is on the list")
    expect(page.get_by_role("main")).to_contain_text("Echo: what is on the list", timeout=30_000)
    # The message keeps its attachment, also after a reload.
    page.reload()
    chip = page.get_by_role("main").get_by_role("button", name=re.compile("shopping.txt"))
    expect(chip).to_be_visible(timeout=30_000)
    _open_panel(page)
    tree = page.get_by_role("tree", name="Workspace")
    tree.get_by_role("treeitem", name=re.compile("uploads")).click()
    tree.get_by_role("treeitem", name=re.compile("shopping.txt")).click()
    expect(page.get_by_role("region", name="Preview")).to_contain_text("basil")
    assert accessibility_violations(page) == []


@pytest.mark.spec("UX-021", "UX-019", "UX-007")
def test_the_panel_is_resized_by_dragging_its_edge(page: Page, member: Account) -> None:
    sign_in(page, member)
    _send(page, "a wider panel")
    expect(page.get_by_role("main")).to_contain_text("Echo: a wider panel", timeout=30_000)
    _open_panel(page)
    panel = page.get_by_role("region", name="Files")
    edge = page.get_by_role("separator", name="Resize the files panel")
    start = panel.bounding_box()
    box = edge.bounding_box()
    assert start is not None
    assert box is not None
    # Its edge is on its left: dragging it to the left widens it.
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 - 120, box["y"] + box["height"] / 2, steps=5)
    page.mouse.up()
    wider = panel.bounding_box()
    assert wider is not None
    assert 110 <= wider["width"] - start["width"] <= 130
    assert edge.get_attribute("aria-valuenow") == str(round(wider["width"]))
    assert accessibility_violations(page) == []
    # Kept on the device.
    page.reload()
    _open_panel(page)
    kept = panel.bounding_box()
    assert kept is not None
    assert abs(kept["width"] - wider["width"]) <= 1
    # A double click brings back the default.
    edge.dblclick()
    reset = panel.bounding_box()
    assert reset is not None
    assert abs(reset["width"] - start["width"]) <= 1


@pytest.mark.spec("CNV-017")
def test_removing_an_attachment_before_sending_deletes_it(page: Page, member: Account, tmp_path: Path) -> None:
    sign_in(page, member)
    _attach(page, tmp_path, "draft.txt", "not needed")
    page.get_by_role("button", name="Remove draft.txt").click()
    _send(page, "nothing attached")
    expect(page.get_by_role("main")).to_contain_text("Echo: nothing attached", timeout=30_000)
    _open_panel(page)
    expect(page.get_by_role("tree", name="Workspace")).not_to_contain_text("draft.txt")


@pytest.mark.spec("UX-019")
def test_files_are_deleted_after_confirming(page: Page, member: Account, tmp_path: Path) -> None:
    sign_in(page, member)
    _attach(page, tmp_path, "old.txt", "old")
    _send(page, "keep it")
    expect(page.get_by_role("main")).to_contain_text("Echo: keep it", timeout=30_000)
    _open_panel(page)
    tree = page.get_by_role("tree", name="Workspace")
    tree.get_by_role("treeitem", name=re.compile("uploads")).click()
    tree.get_by_role("treeitem", name=re.compile("old.txt")).click()
    page.get_by_role("button", name="Delete").click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_contain_text("old.txt")
    dialog.get_by_role("button", name="Delete").click()
    expect(tree).not_to_contain_text("old.txt")


@pytest.mark.spec("UX-020", "ART-003")
def test_an_html_file_never_runs_in_the_app(page: Page, member: Account) -> None:
    sign_in(page, member)
    _send(page, "hello")
    conversation = _conversation_id(page)
    response = page.request.put(
        f"/v1/conversations/{conversation}/workspace/file?path=page.html",
        data=b"<h1>Hello</h1><script>document.title='pwned'</script>",
        headers={"Content-Type": "application/octet-stream", "X-Sibillo-Request": "1"},
    )
    assert response.status == 201, response.text()
    _open_panel(page)
    page.get_by_role("tree", name="Workspace").get_by_role("treeitem", name=re.compile("page.html")).click()
    preview = page.get_by_role("region", name="Preview")
    # It runs as a page of its own, a stranger to the app, or shows as its source.
    expect(preview.locator("iframe")).to_have_attribute("sandbox", "allow-scripts")
    expect(preview.locator("iframe").content_frame.get_by_role("heading", name="Hello")).to_be_visible()
    preview.get_by_role("button", name="Source").click()
    expect(preview).to_contain_text("<script>")
    assert page.title() != "pwned"


@pytest.mark.spec("AGT-023", "ART-001")
def test_an_offered_file_downloads_from_its_card(page: Page, member: Account, tmp_path: Path) -> None:
    sign_in(page, member)
    _attach(page, tmp_path, "report.txt", "the report")
    _send(page, "attached")
    expect(page.get_by_role("main")).to_contain_text("Echo: attached", timeout=30_000)
    _send(page, 'tool:offer_download {"path": "uploads/report.txt"}')
    card = page.get_by_role("main").get_by_role("group", name=re.compile("report.txt"))
    expect(card).to_be_visible(timeout=30_000)
    with page.expect_download() as download:
        card.get_by_role("button", name="Download").click()
    assert download.value.suggested_filename == "report.txt"
    assert Path(download.value.path()).read_text() == "the report"
    # The card also opens the file in the viewer.
    card.get_by_role("button", name=re.compile("report.txt")).click()
    expect(page.get_by_role("region", name="Preview")).to_contain_text("the report")


@pytest.mark.spec("UX-019")
def test_the_panel_is_a_full_screen_sheet_on_a_phone(page: Page, member: Account) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    sign_in(page, member)
    _send(page, "hello")
    expect(page.get_by_role("main")).to_contain_text("Echo: hello", timeout=30_000)
    _open_panel(page)
    box = page.get_by_role("dialog", name="Files").bounding_box()
    assert box is not None
    assert box["width"] >= 380
    assert box["height"] >= 800
    assert accessibility_violations(page) == []


# A page that says what it may do: run, read cookies, reach the API or the network.
PAGE = """<!doctype html><title>Planner</title><body><p id="ran">not run</p><p id="api">waiting</p>
<p id="out">waiting</p><p id="cookie">waiting</p>
<script>
document.getElementById("ran").textContent = "Page script ran";
try { document.cookie; document.getElementById("cookie").textContent = "cookies readable"; }
catch (error) { document.getElementById("cookie").textContent = "no cookies"; }
fetch("/v1/me", {credentials: "include"}).then(
  () => { document.getElementById("api").textContent = "API reached"; },
  () => { document.getElementById("api").textContent = "API blocked"; });
fetch("https://example.org/").then(
  () => { document.getElementById("out").textContent = "network reached"; },
  () => { document.getElementById("out").textContent = "network blocked"; });
</script></body>"""


def _show(page: Page, name: str) -> None:
    tree = page.get_by_role("tree", name="Workspace")
    tree.get_by_role("treeitem", name=re.compile("uploads")).click()
    tree.get_by_role("treeitem", name=re.compile(re.escape(name))).click()


@pytest.mark.spec("ART-002", "UX-007")
def test_files_open_in_their_viewers(page: Page, member: Account, tmp_path: Path) -> None:
    sign_in(page, member)
    for name, text in (
        ("notes.md", "# Dinner plan\n\n- **basil**\n"),
        ("plan.py", "def plan():\n    return 'basil'\n"),
        ("flow.mmd", "graph TD\n  Shop --> Cook\n"),
    ):
        _attach(page, tmp_path, name, text)
    _send(page, "here are my files")
    expect(page.get_by_role("main")).to_contain_text("Echo: here are my files", timeout=30_000)
    _open_panel(page)
    preview = page.get_by_role("region", name="Preview")
    # Markdown rendered, and its source on request.
    _show(page, "notes.md")
    expect(preview.locator("strong", has_text="basil")).to_be_visible()
    preview.get_by_role("button", name="Source").click()
    expect(preview).to_contain_text("**basil**")
    # Code highlighted.
    page.get_by_role("tree", name="Workspace").get_by_role("treeitem", name=re.compile("plan.py")).click()
    expect(preview.locator(".shiki-block")).to_contain_text("return")
    # A Mermaid diagram drawn as an image.
    page.get_by_role("tree", name="Workspace").get_by_role("treeitem", name=re.compile("flow.mmd")).click()
    expect(preview.get_by_role("img", name="flow.mmd")).to_be_visible(timeout=15_000)
    assert accessibility_violations(page) == []
    # Larger, on request.
    preview.get_by_role("button", name="Full view").click()
    large = page.get_by_role("dialog", name="flow.mmd")
    expect(large.get_by_role("img", name="flow.mmd")).to_be_visible()


@pytest.mark.spec("ART-003", "ART-002")
def test_a_web_page_runs_in_an_opaque_origin_without_network(page: Page, member: Account, tmp_path: Path) -> None:
    sign_in(page, member)
    _attach(page, tmp_path, "planner.html", PAGE)
    _send(page, "a page")
    expect(page.get_by_role("main")).to_contain_text("Echo: a page", timeout=30_000)
    _open_panel(page)
    _show(page, "planner.html")
    frame = page.get_by_role("region", name="Preview").locator("iframe")
    expect(frame).to_have_attribute("sandbox", "allow-scripts")
    inside = frame.content_frame
    expect(inside.locator("#ran")).to_have_text("Page script ran", timeout=15_000)
    # A stranger to the app: no cookies, no API, no network.
    expect(inside.locator("#cookie")).to_have_text("no cookies")
    expect(inside.locator("#api")).to_have_text("API blocked")
    expect(inside.locator("#out")).to_have_text("network blocked")
    # Its source, on request.
    page.get_by_role("region", name="Preview").get_by_role("button", name="Source").click()
    expect(page.get_by_role("region", name="Preview")).to_contain_text("Page script ran")
