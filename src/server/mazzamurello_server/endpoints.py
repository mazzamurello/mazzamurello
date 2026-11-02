"""Connections to tenant model endpoints: public addresses only, checked at connection time (MOD-009, ADR-0061).

A tenant admin chooses the endpoint and the request leaves from the control
plane, so the address it reaches is checked when the connection is made,
against the addresses this module resolved itself, and redirects are never
followed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable

import httpx

type Address = ipaddress.IPv4Address | ipaddress.IPv6Address
type Resolver = Callable[[str, int], Awaitable[list[Address]]]

# A NAT64 gateway can map these to any IPv4 address, private ones included.
NAT64 = ipaddress.ip_network("64:ff9b::/96")
MODEL_TIMEOUT = httpx.Timeout(600, connect=10)


def is_public(address: Address) -> bool:
    """A global unicast address; an IPv4-mapped IPv6 address is judged as its IPv4 address."""
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return is_public(address.ipv4_mapped)
        if address in NAT64:
            return False
    return address.is_global and not address.is_multicast


async def resolve(host: str, port: int) -> list[Address]:
    """Every address `host` resolves to; a literal address resolves to itself."""
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        found = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return []
    return [ipaddress.ip_address(str(info[4][0]).split("%", 1)[0]) for info in found]


class PublicEndpointTransport(httpx.AsyncBaseTransport):
    """Connects only to addresses that `allowed` accepts, among those the transport resolved itself."""

    def __init__(self, *, resolve: Resolver = resolve, allowed: Callable[[Address], bool] = is_public) -> None:
        self._resolve = resolve
        self._allowed = allowed
        self._transport = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        addresses = await self._resolve(host, port)
        if not addresses or not all(self._allowed(address) for address in addresses):
            raise httpx.ConnectError(f"{host} does not resolve only to public addresses", request=request)
        # The connection goes to a checked address; the Host header and TLS keep the endpoint's name.
        request.url = request.url.copy_with(host=str(addresses[0]))
        request.extensions = {**request.extensions, "sni_hostname": host}
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        await self._transport.aclose()


def tenant_http_client(
    *, resolve: Resolver = resolve, allowed: Callable[[Address], bool] = is_public
) -> httpx.AsyncClient:
    """The HTTP client of a tenant model: checked addresses only, and no redirects (ADR-0061)."""
    return httpx.AsyncClient(
        transport=PublicEndpointTransport(resolve=resolve, allowed=allowed),
        follow_redirects=False,
        timeout=MODEL_TIMEOUT,
    )
