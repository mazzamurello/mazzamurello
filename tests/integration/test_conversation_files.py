"""A conversation's workspace through the API: browsing, previews, uploads, attachments and offers.

(UX-019, UX-020, CNV-017, AGT-023, SBX-014, SBX-019, TEN-006, ADR-0079.)
"""

from __future__ import annotations

import io
import json
import secrets
import zipfile
from typing import Any

import httpx
import pytest

from tests.support.accounts import Account, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, messages, run_input, start_run, wait_for_run
from tests.support.sandbox import WORKSPACE_QUOTA_BYTES
from tests.support.server import Server, fresh_source


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


BINARY = {"Content-Type": "application/octet-stream"}


def _workspace(conversation_id: str) -> str:
    return f"/conversations/{conversation_id}/workspace"


def _put(client: httpx.Client, conversation_id: str, path: str, data: bytes) -> httpx.Response:
    return client.put(f"{_workspace(conversation_id)}/file", params={"path": path}, content=data, headers=BINARY)


def _upload(client: httpx.Client, conversation_id: str, name: str, data: bytes) -> httpx.Response:
    return client.post(f"{_workspace(conversation_id)}/uploads", params={"name": name}, content=data, headers=BINARY)


@pytest.mark.spec("UX-019", "SBX-014")
def test_the_workspace_is_browsed_and_managed_through_the_api(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        assert _put(client, conversation, "notes/todo.md", b"# To do\n").status_code == 201
        assert client.post(f"{_workspace(conversation)}/folders", json={"path": "drafts"}).status_code == 201
        listed = client.get(f"{_workspace(conversation)}/entries", params={"path": ""})
        assert listed.status_code == 200, listed.text
        assert [entry["name"] for entry in listed.json()["entries"]] == ["drafts", "notes"]
        moved = client.post(f"{_workspace(conversation)}/move", json={"from": "notes/todo.md", "to": "drafts/todo.md"})
        assert moved.status_code == 200, moved.text
        summary = client.get(_workspace(conversation)).json()
        assert summary["quota"] == WORKSPACE_QUOTA_BYTES
        assert summary["size"] >= 8
        zipped = client.get(f"{_workspace(conversation)}/archive", params={"path": "drafts"})
        assert zipped.status_code == 200
        assert "attachment" in zipped.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:
            assert archive.read("todo.md") == b"# To do\n"
        assert client.delete(f"{_workspace(conversation)}/entries", params={"path": "notes"}).status_code == 204
        assert client.delete(_workspace(conversation)).status_code == 204
        emptied = client.get(f"{_workspace(conversation)}/entries", params={"path": ""}).json()
    assert emptied["entries"] == []


@pytest.mark.spec("UX-019", "TEN-006")
def test_only_the_owner_reaches_a_conversations_workspace(
    database: Database, server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        assert _put(client, conversation, "private.txt", b"mine").status_code == 201
    other = create_account(database, create_tenant(database))
    with server.client(login(server, other)) as client:
        assert client.get(f"{_workspace(conversation)}/entries", params={"path": ""}).status_code == 404
        assert client.get(f"{_workspace(conversation)}/file", params={"path": "private.txt"}).status_code == 404
        assert _put(client, conversation, "planted.txt", b"x").status_code == 404


@pytest.mark.spec("UX-020")
@pytest.mark.parametrize(
    ("name", "data", "preview_type"),
    [
        ("notes.txt", b"plain notes", "text/plain"),
        ("page.html", b"<script>alert(1)</script>", "text/plain"),
        ("readme.md", b"# Title", "text/markdown"),
        ("table.csv", b"a,b\n1,2\n", "text/csv"),
        ("logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "image/svg+xml"),
        ("photo.png", b"\x89PNG\r\n\x1a\nfake", "image/png"),
        ("program.exe", b"MZ\x90\x00", None),
    ],
    ids=["text", "html", "markdown", "csv", "svg", "png", "binary"],
)
def test_files_are_downloaded_as_attachments_and_previewed_only_as_safe_types(
    server: Server, token: str, name: str, data: bytes, preview_type: str | None
) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        assert _put(client, conversation, name, data).status_code == 201
        download = client.get(f"{_workspace(conversation)}/file", params={"path": name})
        preview = client.get(f"{_workspace(conversation)}/file", params={"path": name, "preview": "true"})
    assert download.status_code == 200
    assert download.content == data
    assert download.headers["content-disposition"].startswith("attachment")
    assert download.headers["content-type"].startswith("application/octet-stream")
    assert download.headers["x-content-type-options"] == "nosniff"
    if preview_type is None:
        assert preview.status_code == 415
        assert preview.json()["code"] == "file.not_previewable"
    else:
        assert preview.status_code == 200, preview.text
        assert preview.headers["content-type"].split(";")[0] == preview_type
        assert preview.headers["x-content-type-options"] == "nosniff"
        assert "text/html" not in preview.headers["content-type"]
        # Opened by itself, as from a link, it runs nothing in the app's origin (T-22).
        assert "sandbox" in preview.headers["content-security-policy"]


@pytest.mark.spec("UX-020")
def test_a_text_preview_stops_at_one_mebibyte(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        assert _put(client, conversation, "big.log", b"l" * (2 * 1024 * 1024)).status_code == 201
        preview = client.get(f"{_workspace(conversation)}/file", params={"path": "big.log", "preview": "true"})
    assert preview.status_code == 200
    assert len(preview.content) == 1024 * 1024


@pytest.mark.spec("CNV-017")
def test_attachments_never_replace_a_file(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        first = _upload(client, conversation, "budget.csv", b"one")
        second = _upload(client, conversation, "budget.csv", b"two")
        third = _upload(client, conversation, "../budget.csv", b"three")
    assert first.status_code == 201, first.text
    assert first.json()["path"] == "uploads/budget.csv"
    assert second.json()["path"] == "uploads/budget (2).csv"
    # A name is only a name: never a path.
    assert third.status_code in {201, 422}
    if third.status_code == 201:
        assert third.json()["path"].startswith("uploads/")


@pytest.mark.spec("CNV-017")
def test_the_model_reads_the_attachments_of_a_message(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        path = _upload(client, conversation, "receipt.pdf", b"%PDF-1.4 fake").json()["path"]
    text = f"what is in it {secrets.token_hex(4)}"
    payload = run_input(conversation, text) | {"attachments": [path]}
    with server.client(token) as client:
        response = client.post(f"/conversations/{conversation}/runs", json=payload)
        assert response.status_code == 200, response.text
    run_id = str(payload["runId"])
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    request_texts = [
        json.dumps(request.body) for request in default_model.endpoint.requests if text in json.dumps(request.body)
    ]
    assert request_texts, "the model received no request"
    # The answer's request has them; the title's needs only the text.
    assert any("uploads/receipt.pdf" in body for body in request_texts)
    history = messages(server, token, conversation)
    (user,) = [message for message in history["items"] if message["role"] == "user"]
    assert user["attachments"] == [{"path": "uploads/receipt.pdf", "size": 13}]
    assert user["content"] == text


@pytest.mark.spec("CNV-017")
@pytest.mark.parametrize(
    "path", ["notes.txt", "uploads/missing.pdf", "../etc/passwd"], ids=["outside-uploads", "missing", "escape"]
)
def test_only_uploaded_files_can_be_attached(server: Server, token: str, path: str) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        assert _put(client, conversation, "notes.txt", b"n").status_code == 201
        payload = run_input(conversation, "with a wrong attachment") | {"attachments": [path]}
        response = client.post(f"/conversations/{conversation}/runs", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.spec("CNV-017", "SBX-019")
def test_uploads_are_limited_by_size_and_quota(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        over_quota = _upload(client, conversation, "huge.bin", b"x" * (WORKSPACE_QUOTA_BYTES + 1024))
    assert over_quota.status_code == 413
    assert over_quota.json()["code"] == "workspace.quota_exceeded"
    api, origin = server.start_twin_api(MZM_UPLOAD_MAX_MB="1")
    try:
        too_large = httpx.post(
            f"{origin}/v1{_workspace(conversation)}/uploads",
            params={"name": "two-mib.bin"},
            content=b"x" * (2 * 1024 * 1024),
            headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": fresh_source(), **BINARY},
            timeout=60,
        )
    finally:
        api.close()
    assert too_large.status_code == 413
    assert too_large.json()["code"] == "file.too_large"


def _tool_result(model: HarnessModel, text: str) -> str:
    (content,) = [
        str(message.get("content", ""))
        for request in model.endpoint.requests_with(text)[-1:]
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]
    return content


@pytest.mark.spec("AGT-023")
def test_the_agent_offers_a_file_of_the_workspace(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)["id"]
    with server.client(token) as client:
        assert _put(client, conversation, "report.pdf", b"%PDF report").status_code == 201
    text = 'tool:offer_download {"path": "report.pdf"}'
    run_id, events = start_run(server, token, conversation, text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert "report.pdf" in _tool_result(default_model, text)
    calls = [event for event in events if event.type == "TOOL_CALL_START"]
    assert [event.data.get("toolCallName") for event in calls] == ["offer_download"]
    # The offer stays in history, where clients show it as a card.
    history = messages(server, token, conversation)["items"]
    offers: list[Any] = [
        call
        for message in history
        if message["role"] == "assistant"
        for call in message.get("toolCalls", [])
        if call["function"]["name"] == "offer_download"
    ]
    assert offers


@pytest.mark.spec("AGT-023")
@pytest.mark.parametrize("path", ["missing.pdf", "../../etc/passwd"], ids=["missing", "escape"])
def test_an_offer_of_a_file_that_is_not_there_is_told_to_the_model(
    server: Server, token: str, default_model: HarnessModel, path: str
) -> None:
    conversation = create_conversation(server, token)["id"]
    text = f"tool:offer_download {json.dumps({'path': path})}"
    run_id, _ = start_run(server, token, conversation, text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    result = _tool_result(default_model, text).lower()
    assert "not" in result
    assert "root:" not in result
