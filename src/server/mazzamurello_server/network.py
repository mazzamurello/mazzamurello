"""The source address of a request (ADR-0050)."""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence

from mazzamurello_server.config import Network

type Address = ipaddress.IPv4Address | ipaddress.IPv6Address


def _parse(value: str) -> Address | None:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    # An IPv4 client seen through an IPv6 socket is still an IPv4 client.
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _trusted(address: Address, trusted_proxies: Sequence[Network]) -> bool:
    return any(address in network for network in trusted_proxies)


def source_address(peer: str | None, forwarded_for: str | None, trusted_proxies: Sequence[Network]) -> Address | None:
    """The peer's address, or the client reported by trusted proxies in `X-Forwarded-For`.

    Walking `X-Forwarded-For` from the right, each trusted proxy vouches for
    the address before it; the first address that is not a trusted proxy is
    the client. Without a trusted peer the header is ignored.
    """
    address = _parse(peer) if peer else None
    if address is None or not forwarded_for or not _trusted(address, trusted_proxies):
        return address
    for item in reversed(forwarded_for.split(",")):
        reported = _parse(item)
        if reported is None:
            # A malformed entry ends what the proxies vouch for.
            return address
        address = reported
        if not _trusted(address, trusted_proxies):
            return address
    return address
