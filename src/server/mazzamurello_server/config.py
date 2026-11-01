"""Configuration of the API process, read only from the environment.

specs/contracts/configuration.md lists the variables (ADR-0050). Anything
missing, invalid or unknown stops the process before it listens.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass

PREFIX = "MZM_"
API_VARIABLES = frozenset(
    {"MZM_DATABASE_URL", "MZM_HTTP_HOST", "MZM_HTTP_PORT", "MZM_TRUSTED_PROXIES", "MZM_SECRET_KEY"}
)
WORKER_VARIABLES = frozenset(
    {"MZM_DATABASE_URL", "MZM_SECRET_KEY", "MZM_RUN_RETENTION_DAYS", "MZM_SANDBOXD_URL", "MZM_SANDBOXD_TOKEN"}
)
MINIMUM_DRIVER_TOKEN_LENGTH = 32
SECRET_KEY_BYTES = 32

type Network = ipaddress.IPv4Network | ipaddress.IPv6Network


class ConfigurationError(Exception):
    """A configuration variable is missing, invalid or unknown; the message names it."""


@dataclass(frozen=True)
class ApiConfiguration:
    database_url: str
    http_host: str
    http_port: int
    trusted_proxies: tuple[Network, ...]
    secret_key: bytes


@dataclass(frozen=True)
class WorkerConfiguration:
    database_url: str
    secret_key: bytes
    run_retention_days: int
    sandboxd_url: str
    sandboxd_token: str


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


def _secret_key(environment: Mapping[str, str]) -> bytes:
    value = environment.get("MZM_SECRET_KEY", "")
    if not value:
        raise ConfigurationError("MZM_SECRET_KEY is required")
    try:
        key = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError):
        key = b""
    if len(key) != SECRET_KEY_BYTES:
        raise ConfigurationError("MZM_SECRET_KEY must be 32 random bytes, base64url-encoded")
    return key


def _refuse_unknown(environment: Mapping[str, str], known: frozenset[str]) -> None:
    unknown = sorted(name for name in environment if name.startswith(PREFIX) and name not in known)
    if unknown:
        raise ConfigurationError(f"unknown configuration variable {unknown[0]}")


def load_worker_configuration(environment: Mapping[str, str]) -> WorkerConfiguration:
    _refuse_unknown(environment, WORKER_VARIABLES)
    days = environment.get("MZM_RUN_RETENTION_DAYS", "30")
    if not days.isdigit() or not 1 <= int(days) <= 3650:
        raise ConfigurationError("MZM_RUN_RETENTION_DAYS must be a number of days from 1 to 3650")
    url = environment.get("MZM_SANDBOXD_URL", "")
    if not url:
        raise ConfigurationError("MZM_SANDBOXD_URL is required")
    if not url.startswith(("http://", "https://")):
        raise ConfigurationError("MZM_SANDBOXD_URL must be an http:// or https:// URL")
    token = environment.get("MZM_SANDBOXD_TOKEN", "")
    if len(token) < MINIMUM_DRIVER_TOKEN_LENGTH:
        raise ConfigurationError(f"MZM_SANDBOXD_TOKEN must be at least {MINIMUM_DRIVER_TOKEN_LENGTH} characters")
    return WorkerConfiguration(
        database_url=_database_url(environment),
        secret_key=_secret_key(environment),
        run_retention_days=int(days),
        sandboxd_url=url.rstrip("/"),
        sandboxd_token=token,
    )


def load_api_configuration(environment: Mapping[str, str]) -> ApiConfiguration:
    _refuse_unknown(environment, API_VARIABLES)
    host = environment.get("MZM_HTTP_HOST", "0.0.0.0")  # noqa: S104 - the container's published entry point
    if not host:
        raise ConfigurationError("MZM_HTTP_HOST must not be empty")
    return ApiConfiguration(
        database_url=_database_url(environment),
        http_host=host,
        http_port=_port(environment),
        trusted_proxies=_trusted_proxies(environment),
        secret_key=_secret_key(environment),
    )
