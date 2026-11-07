"""The sandbox driver's file operations on a conversation's workspace (SBX-014, SBX-018, SBX-019, ADR-0079, T-34)."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from tests.support.database import uuid7
from tests.support.sandbox import WORKSPACE_QUOTA_BYTES, Driver


def _sandbox() -> tuple[str, str, str]:
    return str(uuid7()), str(uuid7()), str(uuid7())


def _base(sandbox: tuple[str, str, str]) -> str:
    return f"/sandboxes/{sandbox[0]}/{sandbox[1]}/{sandbox[2]}"


def _write(client: httpx.Client, sandbox: tuple[str, str, str], path: str, data: bytes) -> httpx.Response:
    return client.put(f"{_base(sandbox)}/files", params={"path": path}, content=data)


def _entries(client: httpx.Client, sandbox: tuple[str, str, str], path: str = "") -> dict[str, dict[str, Any]]:
    response = client.get(f"{_base(sandbox)}/entries", params={"path": path})
    assert response.status_code == 200, response.text
    return {entry["name"]: entry for entry in response.json()["entries"]}


@pytest.mark.spec("SBX-014")
def test_files_are_written_listed_and_read_back(sandboxes: Driver) -> None:
    sandbox = _sandbox()
    with sandboxes.client() as client:
        written = _write(client, sandbox, "notes/2026/todo.txt", b"buy tomatoes\n")
        assert written.status_code == 201, written.text
        assert written.json()["path"] == "notes/2026/todo.txt"
        assert written.json()["size"] == 13
        # Missing folders are created; folders are listed first.
        root = _entries(client, sandbox)
        assert root["notes"]["type"] == "folder"
        assert _entries(client, sandbox, "notes/2026")["todo.txt"]["size"] == 13
        read = client.get(f"{_base(sandbox)}/files", params={"path": "notes/2026/todo.txt"})
        assert read.status_code == 200
        assert read.content == b"buy tomatoes\n"
        size = client.get(f"{_base(sandbox)}/size").json()
        assert size["quota_bytes"] == WORKSPACE_QUOTA_BYTES
        assert size["bytes"] >= 13


@pytest.mark.spec("SBX-014")
def test_a_write_never_replaces_a_file(sandboxes: Driver) -> None:
    sandbox = _sandbox()
    with sandboxes.client() as client:
        assert _write(client, sandbox, "a.txt", b"first").status_code == 201
        assert _write(client, sandbox, "a.txt", b"second").status_code == 409
        assert client.get(f"{_base(sandbox)}/files", params={"path": "a.txt"}).content == b"first"


@pytest.mark.spec("SBX-014", "SBX-019")
def test_a_write_over_the_quota_is_refused_whole(sandboxes: Driver) -> None:
    sandbox = _sandbox()
    with sandboxes.client() as client:
        response = _write(client, sandbox, "big.bin", b"x" * (WORKSPACE_QUOTA_BYTES + 1024))
        assert response.status_code == 413, response.text
        assert "big.bin" not in _entries(client, sandbox)


@pytest.mark.spec("SBX-014")
def test_an_interrupted_write_leaves_nothing(sandboxes: Driver) -> None:
    sandbox = _sandbox()

    def body() -> Iterator[bytes]:
        yield b"y" * 65536
        raise RuntimeError("the client went away")

    with sandboxes.client() as client:
        with pytest.raises((RuntimeError, httpx.HTTPError)):
            client.put(
                f"{_base(sandbox)}/files",
                params={"path": "partial.bin"},
                content=body(),
                headers={"Content-Length": str(4 * 65536)},
            )
        listing = client.get(f"{_base(sandbox)}/entries", params={"path": ""})
        entries: list[dict[str, Any]] = listing.json()["entries"] if listing.status_code == 200 else []
        names = {str(entry["name"]) for entry in entries}
    assert not any("partial" in name for name in names), names


@pytest.mark.spec("SBX-014")
@pytest.mark.parametrize(
    "path",
    ["../escape.txt", "/etc/passwd", "a/../../escape.txt", "out/passwd", "out"],
    ids=["parent", "absolute", "nested-parent", "through-link", "link"],
)
def test_paths_that_leave_the_workspace_are_refused(sandboxes: Driver, path: str) -> None:
    sandbox = _sandbox()
    # A link the agent could have planted, pointing out of the workspace.
    sandboxes.sh(*sandbox, "ln -s /etc /workspace/out")
    with sandboxes.client() as client:
        read = client.get(f"{_base(sandbox)}/files", params={"path": path})
        assert read.status_code in {404, 422}, read.text
        assert b"root:" not in read.content
        written = _write(client, sandbox, path if path != "out" else "out/new.txt", b"planted")
        assert written.status_code in {404, 422}, written.text
        listed = client.get(f"{_base(sandbox)}/entries", params={"path": path})
        assert listed.status_code in {404, 422}, listed.text
    assert sandboxes.sh(*sandbox, "test -e /etc/new.txt || echo absent").stdout == "absent\n"


@pytest.mark.spec("SBX-014")
def test_links_are_listed_and_deleted_but_never_followed(sandboxes: Driver) -> None:
    sandbox = _sandbox()
    sandboxes.sh(*sandbox, "echo kept > /workspace/target.txt; ln -s target.txt /workspace/alias.txt")
    with sandboxes.client() as client:
        entries = _entries(client, sandbox)
        assert entries["alias.txt"]["type"] == "link"
        # Even a link that stays inside the workspace is not read through.
        assert client.get(f"{_base(sandbox)}/files", params={"path": "alias.txt"}).status_code == 422
        assert client.delete(f"{_base(sandbox)}/entries", params={"path": "alias.txt"}).status_code == 204
        entries = _entries(client, sandbox)
    assert "alias.txt" not in entries
    assert entries["target.txt"]["type"] == "file"


@pytest.mark.spec("SBX-014")
def test_folders_are_created_moved_and_deleted(sandboxes: Driver) -> None:
    sandbox = _sandbox()
    with sandboxes.client() as client:
        created = client.post(f"{_base(sandbox)}/folders", json={"path": "drafts/old"})
        assert created.status_code == 201, created.text
        assert client.post(f"{_base(sandbox)}/folders", json={"path": "drafts/old"}).status_code == 409
        assert _write(client, sandbox, "drafts/old/letter.md", b"# Dear").status_code == 201
        assert _write(client, sandbox, "kept.md", b"kept").status_code == 201
        moved = client.post(f"{_base(sandbox)}/move", json={"from": "drafts/old", "to": "archive/2025"})
        assert moved.status_code == 200, moved.text
        assert moved.json()["path"] == "archive/2025"
        assert client.post(f"{_base(sandbox)}/move", json={"from": "kept.md", "to": "archive"}).status_code == 409
        assert client.post(f"{_base(sandbox)}/move", json={"from": "kept.md", "to": "../kept.md"}).status_code == 422
        assert _entries(client, sandbox, "archive/2025")["letter.md"]["size"] == 6
        assert client.delete(f"{_base(sandbox)}/entries", params={"path": "archive"}).status_code == 204
        root = _entries(client, sandbox)
    assert set(root) == {"drafts", "kept.md"}


@pytest.mark.spec("SBX-014")
def test_a_folder_downloads_as_a_zip_without_its_links(sandboxes: Driver) -> None:
    sandbox = _sandbox()
    sandboxes.sh(
        *sandbox,
        "mkdir -p /workspace/site/css && echo '<h1>Hi</h1>' > /workspace/site/index.html"
        " && echo 'h1{}' > /workspace/site/css/main.css && ln -s /etc/passwd /workspace/site/secret",
    )
    with sandboxes.client() as client:
        response = client.get(f"{_base(sandbox)}/archive", params={"path": "site"})
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert archive.read("index.html") == b"<h1>Hi</h1>\n"
    assert "css/main.css" in names
    assert not any("secret" in name for name in names)


@pytest.mark.spec("SBX-014", "SBX-018")
def test_file_operations_leave_no_sandbox_running(sandboxes: Driver) -> None:
    sandbox = _sandbox()
    with sandboxes.client() as client:
        assert _write(client, sandbox, "a.txt", b"a").status_code == 201
        _entries(client, sandbox)
    assert sandboxes.running(sandbox[2]) == []
