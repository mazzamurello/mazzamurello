"""Web search and page reading, through runs (AGT-020, AGT-021, ADR-0074, ADR-0075).

The model the tests serve calls a tool by name when the user's message is
`tool:<name> <arguments>` (tests/support/model.py). Searches reach the search
service the tests serve (tests/support/search.py); pages are served from
inside the user's sandbox, on its own loopback address.
"""

from __future__ import annotations

import json
import secrets
import shlex

import pytest

from tests.support.accounts import Account, create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, start_run, text_of, wait_for_run
from tests.support.sandbox import Driver
from tests.support.search import MANY_RESULTS, SearchServer, result
from tests.support.server import Server

PAGE_PORT = 8765
PAGE = """<!doctype html>
<html><head><title>Garden notes</title></head>
<body>
<nav><a href="/">Home</a> <a href="/shop">Shop for seedlings</a> <a href="/contact">Contact</a></nav>
<article>
<h1>Watering tomatoes</h1>
<p>Tomatoes want deep watering twice a week rather than a little every day,
so that their roots grow down into the cooler soil, where they find water
even in the hottest weeks of the summer.</p>
<p>Water early in the morning, at the foot of the plant, and keep the leaves
dry, which keeps blight away from them.</p>
</article>
<footer>Copyright the garden club</footer>
</body></html>
"""


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


def _call(tool: str, **arguments: str) -> str:
    return f"tool:{tool} {json.dumps(arguments)}"


def _tool_result(model: HarnessModel, text: str) -> str:
    """What the model received as the tool's result, for the run of `text`."""
    (content,) = [
        str(message.get("content", ""))
        for request in model.endpoint.requests_with(text)[-1:]
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]
    return content


def _completed(server: Server, token: str, text: str) -> str:
    """Run `text` in a new conversation; the run's answer, once completed."""
    conversation = create_conversation(server, token)
    run_id, events = start_run(server, token, conversation["id"], text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    return text_of(events)


def _serve_page(sandboxes: Driver, account: Account, name: str, html: str) -> str:
    """Serve `html` at `name` from inside the user's sandbox; its address there."""
    tenant, user = str(account.tenant_id), str(account.id)
    written = sandboxes.sh(tenant, user, f"mkdir -p /tmp/site && printf %s {shlex.quote(html)} > /tmp/site/{name}")
    assert written.exit_code == 0, written
    started = sandboxes.sh(
        tenant,
        user,
        f"cd /tmp/site && (setsid python3 -m http.server {PAGE_PORT} --bind 127.0.0.1 >/dev/null 2>&1 &)"
        f" ; for _ in $(seq 50); do curl -fso /dev/null http://127.0.0.1:{PAGE_PORT}/{name} && exit 0; sleep 0.1;"
        " done; exit 1",
    )
    assert started.exit_code == 0, started
    return f"http://127.0.0.1:{PAGE_PORT}/{name}"


@pytest.mark.spec("AGT-020")
def test_web_search_returns_untrusted_results(
    server: Server, token: str, default_model: HarnessModel, search_service: SearchServer
) -> None:
    query = f"tomato watering {secrets.token_hex(4)}"
    text = _call("web_search", query=query)
    assert _completed(server, token, text).startswith("Tool said:")
    content = _tool_result(default_model, text)
    for index in range(3):
        expected = result(query, index)
        assert expected["title"] in content
        assert expected["url"] in content
        assert expected["content"] in content
    # It says where the results come from, and that they are data.
    assert "untrusted" in content.lower()
    assert search_service.queries().count(query) == 1


@pytest.mark.spec("AGT-020")
def test_web_search_returns_at_most_ten_results(server: Server, token: str, default_model: HarnessModel) -> None:
    text = _call("web_search", query="many")
    _completed(server, token, text)
    content = _tool_result(default_model, text)
    assert result("many", 9)["url"] in content
    assert all(result("many", index)["url"] not in content for index in range(10, MANY_RESULTS))


@pytest.mark.spec("AGT-020")
def test_only_the_query_reaches_the_search_service(server: Server, token: str, search_service: SearchServer) -> None:
    query = f"private {secrets.token_hex(4)}"
    _completed(server, token, _call("web_search", query=query))
    (request,) = search_service.requests_for(query)
    assert request.path == "/search"
    assert request.params["format"] == ["json"]
    assert set(request.params) <= {"q", "format", "pageno", "language", "safesearch"}
    assert not {"authorization", "cookie"} & set(request.headers)
    # The worker never fetches the results itself.
    assert not any(entry.get("resolve") == "example.org" for entry in server.outbound())
    # Queries are not logged (OBS-001).
    assert query not in server.worker.output()


@pytest.mark.spec("AGT-020")
@pytest.mark.parametrize("query", ["fail", "nothing"])
def test_a_failed_or_empty_search_is_told_to_the_model(
    server: Server, token: str, default_model: HarnessModel, query: str
) -> None:
    text = _call("web_search", query=query)
    assert _completed(server, token, text).startswith("Tool said:")
    assert _tool_result(default_model, text).strip()


@pytest.mark.spec("AGT-021")
def test_read_page_returns_the_main_text_of_a_page(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    address = _serve_page(sandboxes, account, "notes.html", PAGE)
    text = _call("read_page", url=address)
    assert _completed(server, token, text).startswith("Tool said:")
    content = _tool_result(default_model, text)
    assert "Garden notes" in content
    assert address in content
    assert "Watering tomatoes" in content
    assert "deep watering twice a week" in content
    assert "keep the leaves" in content
    # Only the main text: not the page's navigation.
    assert "Shop for seedlings" not in content
    assert "untrusted" in content.lower()


@pytest.mark.spec("AGT-021")
def test_read_page_output_is_bounded(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    words = " ".join(f"word{index}" for index in range(3_000))
    html = f"<html><body><article><p>{words}</p></article></body></html>"
    address = _serve_page(sandboxes, account, "long.html", html)
    text = _call("read_page", url=address)
    _completed(server, token, text)
    content = _tool_result(default_model, text)
    assert "word0 " in content
    assert len(content) < len(words)


@pytest.mark.spec("AGT-021")
@pytest.mark.parametrize(
    "address",
    ["file:///etc/passwd", "ftp://example.org/file", f"http://127.0.0.1:{PAGE_PORT + 1}/missing"],
    ids=["file", "ftp", "unreachable"],
)
def test_read_page_tells_the_model_what_it_cannot_read(
    server: Server, token: str, default_model: HarnessModel, address: str
) -> None:
    text = _call("read_page", url=address)
    assert _completed(server, token, text).startswith("Tool said:")
    content = _tool_result(default_model, text)
    assert content.strip()
    assert "root:" not in content
