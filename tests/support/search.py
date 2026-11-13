"""The search service the tests serve: SearXNG's JSON API, with scripted results.

See specs/contracts/test-harness.md ("Search"). `GET /search?q=…&format=json`
answers by the query:

- `fail` answers with a server error;
- `many` answers with `MANY_RESULTS` results;
- `nothing` answers with no results;
- anything else answers with `RESULTS` results, whose titles, addresses and
  excerpts name the query (`result`).

While `scripted_results` is set, every query is answered with those results
instead, as an eval scenario sets them (ADR-0092).

Every request is recorded, so that tests can check what left the worker.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

RESULTS = 3
MANY_RESULTS = 15


def result(query: str, index: int) -> dict[str, Any]:
    """The result at `index` of the scripted answer to `query`, as SearXNG gives it."""
    return {
        "title": f"Result {index} about {query}",
        "url": f"https://example.org/{index}/{quote(query)}",
        "content": f"Excerpt {index} of a page about {query}.",
        "engine": "duckduckgo",
        "engines": ["duckduckgo", "brave"],
        "score": 1.0 / (index + 1),
        "category": "general",
    }


@dataclass(frozen=True)
class SearchRequest:
    path: str
    params: dict[str, list[str]]
    headers: dict[str, str]


@dataclass
class SearchServer:
    url: str
    requests: list[SearchRequest] = field(default_factory=list[SearchRequest])
    scripted_results: list[dict[str, Any]] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, request: SearchRequest) -> None:
        with self._lock:
            self.requests.append(request)

    def queries(self) -> list[str]:
        """The query of every search request so far."""
        with self._lock:
            return [request.params.get("q", [""])[0] for request in self.requests]

    def requests_for(self, query: str) -> list[SearchRequest]:
        with self._lock:
            return [request for request in self.requests if request.params.get("q", [""])[0] == query]


def _handler(search: SearchServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            params = parse_qs(parts.query)
            headers = {name.lower(): value for name, value in self.headers.items()}
            search.record(SearchRequest(parts.path, params, headers))
            query = params.get("q", [""])[0]
            if parts.path != "/search" or params.get("format") != ["json"]:
                self._json(404, {"error": "not found"})
                return
            if query == "fail":
                self._json(500, {"error": "scripted failure"})
                return
            scripted = search.scripted_results
            count = {"many": MANY_RESULTS, "nothing": 0}.get(query, RESULTS)
            results = list(scripted) if scripted is not None else [result(query, index) for index in range(count)]
            count = len(results)
            self._json(
                200,
                {
                    "query": query,
                    "number_of_results": count,
                    "results": results,
                    "answers": [],
                    "corrections": [],
                    "infoboxes": [],
                    "suggestions": [],
                    "unresponsive_engines": [],
                },
            )

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def start_search_server() -> tuple[SearchServer, ThreadingHTTPServer]:
    """Serve the search service on the loopback address."""
    search = SearchServer(url="")
    http = ThreadingHTTPServer(("127.0.0.1", 0), _handler(search))
    http.daemon_threads = True
    search.url = f"http://127.0.0.1:{http.server_address[1]}"
    threading.Thread(target=http.serve_forever, daemon=True).start()
    return search, http
