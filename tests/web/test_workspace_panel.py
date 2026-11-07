"""Files in a conversation, in the web client (UX-019, UX-020, CNV-017, AGT-023, ADR-0079)."""

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


@pytest.mark.spec("UX-020")
def test_an_html_file_is_shown_as_its_source(page: Page, member: Account) -> None:
    sign_in(page, member)
    _send(page, "hello")
    conversation = _conversation_id(page)
    response = page.request.put(
        f"/v1/conversations/{conversation}/workspace/file?path=page.html",
        data=b"<h1>Hello</h1><script>document.title='pwned'</script>",
        headers={"Content-Type": "application/octet-stream", "X-Mazzamurello-Request": "1"},
    )
    assert response.status == 201, response.text()
    _open_panel(page)
    page.get_by_role("tree", name="Workspace").get_by_role("treeitem", name=re.compile("page.html")).click()
    preview = page.get_by_role("region", name="Preview")
    expect(preview).to_contain_text("<script>")
    assert page.title() != "pwned"


@pytest.mark.spec("AGT-023")
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
