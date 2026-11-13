"""Tenant model requests connect only to checked addresses (MOD-009, ADR-0061, threat T-27).

No test can serve a model on a public address, so these tests use the
gateway's transport directly, with an injected resolver and, where a
connection must succeed, a policy that allows the loopback address.
"""

from __future__ import annotations

import asyncio
import ipaddress
import threading
from collections.abc import Awaitable, Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

import httpx
import openai
import pytest

from sibillo_server.endpoints import Address, PublicEndpointTransport, is_public, tenant_http_client


class _Server:
    """A local HTTP server that records requests and redirects `/redirect` to `/secret`."""

    def __init__(self) -> None:
        self.paths: list[str] = []
        self.hosts: list[str] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def _answer(self) -> None:
                server.paths.append(self.path)
                server.hosts.append(self.headers.get("Host", ""))
                if "redirect" in self.path:
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{server.port}/secret")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = b'{"ok": true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                self._answer()

            def do_POST(self) -> None:
                self._answer()

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.http.server_address[1]
        threading.Thread(target=self.http.serve_forever, daemon=True).start()


@pytest.fixture
def local_server() -> Iterator[_Server]:
    server = _Server()
    yield server
    server.http.shutdown()


def _resolver(addresses: dict[str, list[str]]) -> Callable[[str, int], Awaitable[list[Address]]]:
    async def resolve(host: str, port: int) -> list[Address]:
        return [ipaddress.ip_address(address) for address in addresses.get(host, [])]

    return resolve


def _loopback_allowed(address: Address) -> bool:
    return address.is_loopback


@pytest.mark.spec("MOD-009")
@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("8.8.8.8", True),
        ("2606:4700:4700::1111", True),
        ("::ffff:8.8.8.8", True),
        ("10.0.0.1", False),
        ("127.0.0.1", False),
        ("100.64.0.1", False),
        ("169.254.169.254", False),
        ("192.168.1.1", False),
        ("::1", False),
        ("fc00::1", False),
        ("fe80::1", False),
        ("::ffff:10.0.0.1", False),
        ("64:ff9b::a00:1", False),
    ],
)
def test_public_means_a_global_unicast_address(address: str, public: bool) -> None:
    assert is_public(ipaddress.ip_address(address)) is public


@pytest.mark.spec("MOD-009")
@pytest.mark.parametrize("addresses", [["10.0.0.5"], ["93.184.216.34", "192.168.1.1"], []])
def test_names_with_a_private_or_no_address_are_refused_at_connection_time(addresses: list[str]) -> None:
    transport = PublicEndpointTransport(resolve=_resolver({"rebind.example": addresses}))

    async def request() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get("https://rebind.example/v1/models")

    with pytest.raises(httpx.ConnectError):
        asyncio.run(request())


@pytest.mark.spec("MOD-009")
def test_the_connection_goes_to_the_checked_address_with_the_endpoints_name(local_server: _Server) -> None:
    # `model.invalid` resolves nowhere: only the transport's own resolution can reach the server.
    transport = PublicEndpointTransport(resolve=_resolver({"model.invalid": ["127.0.0.1"]}), allowed=_loopback_allowed)

    async def request() -> httpx.Response:
        async with httpx.AsyncClient(transport=transport) as client:
            return await client.get(f"http://model.invalid:{local_server.port}/v1/models")

    response = asyncio.run(request())
    assert response.status_code == 200
    assert local_server.hosts == [f"model.invalid:{local_server.port}"]


@pytest.mark.spec("MOD-009")
def test_redirects_are_not_followed(local_server: _Server) -> None:
    client = tenant_http_client(resolve=_resolver({"model.invalid": ["127.0.0.1"]}), allowed=_loopback_allowed)
    # The SDK's signature names httpx2; it also accepts the legacy httpx client the gateway uses.
    legacy_client = cast("Any", client)
    model = openai.AsyncOpenAI(
        base_url=f"http://model.invalid:{local_server.port}/redirect", api_key="sk-test", http_client=legacy_client
    )

    async def request() -> None:
        async with client:
            await model.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}])

    with pytest.raises(openai.APIError):
        asyncio.run(request())
    assert local_server.paths == ["/redirect/chat/completions"]
