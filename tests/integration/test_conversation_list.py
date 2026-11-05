"""Folders, pins and the conversation list, and search (CNV-007, CNV-008, CNV-009, ADR-0073)."""

from __future__ import annotations

import secrets
from typing import Any

import pytest

from tests.support.accounts import assert_problem, body
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.households import Member, new_member
from tests.support.runs import create_conversation, start_run, wait_for_run
from tests.support.server import Server


@pytest.fixture
def member(database: Database, server: Server, harness_model: HarnessModel) -> Member:
    return new_member(database, server, harness_model)


def _list(server: Server, token: str, **params: Any) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.get("/conversation-list", params=params)
    assert response.status_code == 200, response.text
    return body(response)


def _names(page: dict[str, Any]) -> list[str]:
    """The list as names: a folder as `[name: titles…]`."""
    names: list[str] = []
    for entry in page["items"]:
        if entry["kind"] == "folder":
            inside = ", ".join(c["title"] for c in entry["conversations"])
            names.append(f"[{entry['folder']['name']}: {inside}]")
        else:
            names.append(entry["conversation"]["title"])
    return names


def _talk(server: Server, token: str, title: str, text: str = "hello") -> dict[str, Any]:
    conversation = create_conversation(server, token, title)
    run_id, _ = start_run(server, token, conversation["id"], text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    return conversation


def _patch(server: Server, token: str, path: str, change: dict[str, Any]) -> dict[str, Any]:
    with server.client(token) as client:
        response = client.patch(path, json=change)
    assert response.status_code == 200, response.text
    return body(response)


@pytest.mark.spec("CNV-007", "CNV-008")
def test_folders_sit_in_the_list_by_their_newest_conversation(server: Server, member: Member) -> None:
    oldest = _talk(server, member.token, "Oldest")
    with server.client(member.token) as client:
        folder = body(client.post("/folders", json={"name": "Home"}))
    in_folder = _talk(server, member.token, "In the folder")
    _patch(server, member.token, f"/conversations/{in_folder['id']}", {"folder_id": folder["id"]})
    _talk(server, member.token, "Newest")
    assert _names(_list(server, member.token)) == ["Newest", "[Home: In the folder]", "Oldest"]
    # A new message moves its folder up.
    run_id, _ = start_run(server, member.token, in_folder["id"], "again")
    wait_for_run(server, member.token, run_id)
    assert _names(_list(server, member.token)) == ["[Home: In the folder]", "Newest", "Oldest"]
    # Renaming leaves the order as it was: only messages count.
    _patch(server, member.token, f"/conversations/{oldest['id']}", {"title": "Oldest, renamed"})
    assert _names(_list(server, member.token))[-1] == "Oldest, renamed"


@pytest.mark.spec("CNV-008")
def test_pinned_entries_come_first(server: Server, member: Member) -> None:
    first = _talk(server, member.token, "First")
    _talk(server, member.token, "Second")
    with server.client(member.token) as client:
        folder = body(client.post("/folders", json={"name": "Empty"}))
    _patch(server, member.token, f"/conversations/{first['id']}", {"pinned": True})
    _patch(server, member.token, f"/folders/{folder['id']}", {"pinned": True})
    names = _names(_list(server, member.token))
    assert set(names[:2]) == {"First", "[Empty: ]"}
    assert names[2:] == ["Second"]
    _patch(server, member.token, f"/conversations/{first['id']}", {"pinned": False})
    assert _names(_list(server, member.token))[1:] == ["Second", "First"]


@pytest.mark.spec("CNV-007", "CNV-008")
def test_folders_are_renamed_collapsed_and_deleted(server: Server, member: Member) -> None:
    with server.client(member.token) as client:
        folder = body(client.post("/folders", json={"name": "School"}))
    homework = _talk(server, member.token, "Homework")
    _patch(server, member.token, f"/conversations/{homework['id']}", {"folder_id": folder["id"]})
    changed = _patch(server, member.token, f"/folders/{folder['id']}", {"name": "School 2026", "collapsed": True})
    assert (changed["name"], changed["collapsed"]) == ("School 2026", True)
    (entry,) = [e for e in _list(server, member.token)["items"] if e["kind"] == "folder"]
    assert entry["folder"]["collapsed"] is True
    with server.client(member.token) as client:
        assert client.delete(f"/folders/{folder['id']}").status_code == 204
        moved = body(client.get(f"/conversations/{homework['id']}"))
    # Its conversations stay, out of the folder.
    assert moved["folder_id"] is None
    assert _names(_list(server, member.token)) == ["Homework"]


@pytest.mark.spec("CNV-007", "TEN-006")
def test_folders_are_their_owners(
    database: Database, server: Server, member: Member, harness_model: HarnessModel
) -> None:
    other = new_member(database, server, harness_model)
    with server.client(other.token) as client:
        theirs = body(client.post("/folders", json={"name": "Theirs"}))
    mine = create_conversation(server, member.token, "Mine")
    with server.client(member.token) as client:
        refused = client.patch(f"/conversations/{mine['id']}", json={"folder_id": theirs["id"]})
        assert_problem(refused, 422, "request.validation_failed")
        assert_problem(client.patch(f"/folders/{theirs['id']}", json={"name": "Mine"}), 404, "resource.not_found")
        assert_problem(client.delete(f"/folders/{theirs['id']}"), 404, "resource.not_found")
    assert "[Theirs: ]" not in _names(_list(server, member.token))


@pytest.mark.spec("CNV-008")
def test_the_list_is_paginated(server: Server, member: Member) -> None:
    for number in range(3):
        create_conversation(server, member.token, f"Page {number}")
    first = _list(server, member.token, limit=2)
    assert len(first["items"]) == 2
    assert first["next_cursor"]
    rest = _list(server, member.token, limit=2, cursor=first["next_cursor"])
    assert _names(first) + _names(rest) == ["Page 2", "Page 1", "Page 0"]
    assert rest["next_cursor"] is None


def _search(server: Server, token: str, query: str) -> list[dict[str, Any]]:
    with server.client(token) as client:
        response = client.get("/search", params={"q": query})
    assert response.status_code == 200, response.text
    return list(body(response)["items"])


@pytest.mark.spec("CNV-009")
def test_search_finds_titles_and_message_text(server: Server, member: Member) -> None:
    word = f"zucchini{secrets.token_hex(3)}"
    by_text = _talk(server, member.token, "Dinner", f"how do I grill {word} tonight")
    by_title = create_conversation(server, member.token, f"Garden {word}")
    found = _search(server, member.token, word)
    assert {item["conversation_id"] for item in found} == {by_text["id"], by_title["id"]}
    (match,) = [item for item in found if item["conversation_id"] == by_text["id"]]
    assert word in match["snippet"]
    assert match["title"] == "Dinner"
    # Words in any language, and in either case.
    assert {item["conversation_id"] for item in _search(server, member.token, word.upper())} >= {by_text["id"]}


@pytest.mark.spec("CNV-009", "TEN-003", "TEN-006")
def test_search_finds_only_the_users_own(
    database: Database, server: Server, member: Member, harness_model: HarnessModel
) -> None:
    word = f"secret{secrets.token_hex(3)}"
    _talk(server, member.token, "Private", f"my {word} recipe")
    other = new_member(database, server, harness_model)
    assert _search(server, other.token, word) == []
    with server.client(member.token) as client:
        assert_problem(client.get("/search", params={"q": ""}), 422, "request.validation_failed")
