"""Configuration of the API process, read only from the environment.

specs/contracts/configuration.md lists the variables (ADR-0050). Anything
missing, invalid or unknown stops the process before it listens.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass

PREFIX = "MZM_"
API_VARIABLES = frozenset({"MZM_DATABASE_URL", "MZM_HTTP_HOST", "MZM_HTTP_PORT", "MZM_TRUSTED_PROXIES"})

type Network = ipaddress.IPv4Network | ipaddress.IPv6Network


class ConfigurationError(Exception):
    """A configuration variable is missing, invalid or unknown; the message names it."""


@dataclass(frozen=True)
class ApiConfiguration:
    database_url: str
    http_host: str
    http_port: int
    trusted_proxies: tuple[Network, ...]


def _database_url(environment: Mapping[str, str]) -> str:
    url = environment.get("MZM_DATABASE_URL", "")
    if not url:
        raise ConfigurationError("MZM_DATABASE_URL is required")
    scheme, separator, rest = url.partition("://")
    if not separator or scheme not in ("postgresql", "postgres") or not rest:
        raise ConfigurationError("MZM_DATABASE_URL must be a postgresql://USER:PASSWORD@HOST:PORT/DATABASE URL")
    return url


def _port(environment: Mapping[str, str]) -> int:
    value = environment.get("MZM_HTTP_PORT", "8000")
    if not value.isdigit() or not 1 <= int(value) <= 65535:
        raise ConfigurationError("MZM_HTTP_PORT must be a port number from 1 to 65535")
    return int(value)


def _trusted_proxies(environment: Mapping[str, str]) -> tuple[Network, ...]:
    networks: list[Network] = []
    for item in environment.get("MZM_TRUSTED_PROXIES", "").split(","):
        if not item.strip():
            continue
        try:
            networks.append(ipaddress.ip_network(item.strip()))
        except ValueError:
            raise ConfigurationError(
                f"MZM_TRUSTED_PROXIES: {item.strip()!r} is not an IP address or CIDR network"
            ) from None
    return tuple(networks)


def load_api_configuration(environment: Mapping[str, str]) -> ApiConfiguration:
    unknown = sorted(name for name in environment if name.startswith(PREFIX) and name not in API_VARIABLES)
    if unknown:
        raise ConfigurationError(f"unknown configuration variable {unknown[0]}")
    host = environment.get("MZM_HTTP_HOST", "0.0.0.0")  # noqa: S104 - the container's published entry point
    if not host:
        raise ConfigurationError("MZM_HTTP_HOST must not be empty")
    return ApiConfiguration(
        database_url=_database_url(environment),
        http_host=host,
        http_port=_port(environment),
        trusted_proxies=_trusted_proxies(environment),
    )
