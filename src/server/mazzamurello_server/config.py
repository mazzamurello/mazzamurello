"""Configuration of the API process, read only from the environment.

specs/contracts/configuration.md lists the variables (ADR-0050). Anything
missing, invalid or unknown stops the process before it listens.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PREFIX = "MZM_"
# Where the server image puts the built web app (ADR-0067).
DEFAULT_WEB_ROOT = Path("/opt/mazzamurello/web")
API_VARIABLES = frozenset(
    {
        "MZM_DATABASE_URL",
        "MZM_HTTP_HOST",
        "MZM_HTTP_PORT",
        "MZM_TRUSTED_PROXIES",
        "MZM_SECRET_KEY",
        "MZM_SANDBOXD_URL",
        "MZM_SANDBOXD_TOKEN",
        "MZM_WEB_ROOT",
        "MZM_BACKUP_STATUS",
    }
)
BACKUP_VARIABLES = frozenset(
    {
        "MZM_DATABASE_URL",
        "MZM_SECRET_KEY",
        "MZM_BACKUP_KEY",
        "MZM_SANDBOXD_URL",
        "MZM_SANDBOXD_TOKEN",
        "MZM_BACKUP_DIR",
        "MZM_BACKUP_TIME",
        "MZM_BACKUP_KEEP",
    }
)
BACKUP_TIME = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
WORKER_VARIABLES = frozenset(
    {
        "MZM_DATABASE_URL",
        "MZM_SECRET_KEY",
        "MZM_RUN_RETENTION_DAYS",
        "MZM_SANDBOXD_URL",
        "MZM_SANDBOXD_TOKEN",
        "MZM_SEARCH_URL",
    }
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
    sandboxd_url: str
    sandboxd_token: str
    # The built web app, served at `/` when the directory exists (ADR-0067).
    web_root: Path = DEFAULT_WEB_ROOT
    # The backup service's status file, when backups are checked (OPS-011).
    backup_status: Path | None = None


@dataclass(frozen=True)
class WorkerConfiguration:
    database_url: str
    secret_key: bytes
    run_retention_days: int
    sandboxd_url: str
    sandboxd_token: str
    # Empty when the instance has no search service (AGT-020).
    search_url: str = ""


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


def _sandbox_driver(environment: Mapping[str, str]) -> tuple[str, str]:
    url = environment.get("MZM_SANDBOXD_URL", "")
    if not url:
        raise ConfigurationError("MZM_SANDBOXD_URL is required")
    if not url.startswith(("http://", "https://")):
        raise ConfigurationError("MZM_SANDBOXD_URL must be an http:// or https:// URL")
    token = environment.get("MZM_SANDBOXD_TOKEN", "")
    if len(token) < MINIMUM_DRIVER_TOKEN_LENGTH:
        raise ConfigurationError(f"MZM_SANDBOXD_TOKEN must be at least {MINIMUM_DRIVER_TOKEN_LENGTH} characters")
    return url.rstrip("/"), token


def load_worker_configuration(environment: Mapping[str, str]) -> WorkerConfiguration:
    _refuse_unknown(environment, WORKER_VARIABLES)
    days = environment.get("MZM_RUN_RETENTION_DAYS", "30")
    if not days.isdigit() or not 1 <= int(days) <= 3650:
        raise ConfigurationError("MZM_RUN_RETENTION_DAYS must be a number of days from 1 to 3650")
    url, token = _sandbox_driver(environment)
    search_url = environment.get("MZM_SEARCH_URL", "")
    if search_url and not search_url.startswith(("http://", "https://")):
        raise ConfigurationError("MZM_SEARCH_URL must be an http:// or https:// URL")
    return WorkerConfiguration(
        database_url=_database_url(environment),
        secret_key=_secret_key(environment),
        run_retention_days=int(days),
        sandboxd_url=url,
        sandboxd_token=token,
        search_url=search_url.rstrip("/"),
    )


def load_api_configuration(environment: Mapping[str, str]) -> ApiConfiguration:
    _refuse_unknown(environment, API_VARIABLES)
    driver_url, driver_token = _sandbox_driver(environment)
    host = environment.get("MZM_HTTP_HOST", "0.0.0.0")  # noqa: S104 - the container's published entry point
    if not host:
        raise ConfigurationError("MZM_HTTP_HOST must not be empty")
    return ApiConfiguration(
        database_url=_database_url(environment),
        http_host=host,
        http_port=_port(environment),
        trusted_proxies=_trusted_proxies(environment),
        secret_key=_secret_key(environment),
        sandboxd_url=driver_url,
        sandboxd_token=driver_token,
        web_root=Path(environment.get("MZM_WEB_ROOT") or DEFAULT_WEB_ROOT),
        backup_status=Path(status) if (status := environment.get("MZM_BACKUP_STATUS")) else None,
    )


@dataclass(frozen=True)
class BackupConfiguration:
    """What backups and restores need (ADR-0077)."""

    # PostgreSQL's superuser, so that row-level security hides nothing.
    database_url: str
    # The instance's secret key, as written in `.env`.
    secret_key: str
    backup_key: str
    sandboxd_url: str
    sandboxd_token: str
    backup_dir: Path
    backup_time: str
    keep: int


def load_backup_configuration(environment: Mapping[str, str]) -> BackupConfiguration:
    _refuse_unknown(environment, BACKUP_VARIABLES)
    _secret_key(environment)
    key = environment.get("MZM_BACKUP_KEY", "").strip()
    if not key.upper().startswith("AGE-SECRET-KEY-1"):
        raise ConfigurationError("MZM_BACKUP_KEY must be an age identity, AGE-SECRET-KEY-1…")
    at = environment.get("MZM_BACKUP_TIME", "03:00")
    if not BACKUP_TIME.match(at):
        raise ConfigurationError("MZM_BACKUP_TIME must be HH:MM, in UTC")
    keep = environment.get("MZM_BACKUP_KEEP", "14")
    if not keep.isdigit() or not 1 <= int(keep) <= 365:
        raise ConfigurationError("MZM_BACKUP_KEEP must be a number from 1 to 365")
    url, token = _sandbox_driver(environment)
    return BackupConfiguration(
        database_url=_database_url(environment),
        secret_key=environment["MZM_SECRET_KEY"],
        backup_key=key,
        sandboxd_url=url,
        sandboxd_token=token,
        backup_dir=Path(environment.get("MZM_BACKUP_DIR") or "/backups"),
        backup_time=at,
        keep=int(keep),
    )
