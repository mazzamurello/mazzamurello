"""Configuration of the sandbox driver, read only from the environment (ADR-0050, ADR-0053).

specs/contracts/configuration.md lists the variables. Anything missing,
invalid or unknown stops the driver before it listens.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass

PREFIX = "MZM_"
VARIABLES = frozenset(
    {
        "MZM_SANDBOXD_HOST",
        "MZM_SANDBOXD_PORT",
        "MZM_SANDBOXD_TOKEN",
        "MZM_SANDBOX_IMAGE",
        "MZM_SANDBOX_RUNTIME",
        "MZM_NETGUARD_CONTAINER",
        "MZM_SANDBOX_RESOLVER",
        "MZM_SANDBOX_CPUS",
        "MZM_SANDBOX_MEMORY_MB",
        "MZM_SANDBOX_PROCESSES",
        "MZM_SANDBOX_COMMAND_TIMEOUT_SECONDS",
        "MZM_SANDBOX_MAX_OUTPUT_BYTES",
        "MZM_SANDBOX_IDLE_MINUTES",
    }
)
MINIMUM_TOKEN_LENGTH = 32


class ConfigurationError(Exception):
    """A configuration variable is missing, invalid or unknown; the message names it."""


@dataclass(frozen=True)
class DriverConfiguration:
    host: str
    port: int
    token: str
    image: str
    runtime: str
    netguard_container: str
    resolver: str
    cpus: float
    memory_mb: int
    processes: int
    command_timeout_seconds: int
    max_output_bytes: int
    idle_minutes: int


def _integer(environment: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    value = environment.get(name, str(default))
    if not value.isdigit() or not low <= int(value) <= high:
        raise ConfigurationError(f"{name} must be a whole number from {low} to {high}")
    return int(value)


def _cpus(environment: Mapping[str, str]) -> float:
    value = environment.get("MZM_SANDBOX_CPUS", "1")
    try:
        cpus = float(value)
    except ValueError:
        cpus = -1.0
    if not 0.1 <= cpus <= 64:
        raise ConfigurationError("MZM_SANDBOX_CPUS must be a number from 0.1 to 64")
    return cpus


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "")
    if not value:
        raise ConfigurationError(f"{name} is required")
    return value


def load_configuration(environment: Mapping[str, str]) -> DriverConfiguration:
    unknown = sorted(name for name in environment if name.startswith(PREFIX) and name not in VARIABLES)
    if unknown:
        raise ConfigurationError(f"unknown configuration variable {unknown[0]}")
    token = _required(environment, "MZM_SANDBOXD_TOKEN")
    if len(token) < MINIMUM_TOKEN_LENGTH:
        raise ConfigurationError(f"MZM_SANDBOXD_TOKEN must be at least {MINIMUM_TOKEN_LENGTH} characters")
    resolver = environment.get("MZM_SANDBOX_RESOLVER", "9.9.9.9")
    try:
        if not isinstance(ipaddress.ip_address(resolver), ipaddress.IPv4Address):
            raise ValueError(resolver)
    except ValueError:
        raise ConfigurationError("MZM_SANDBOX_RESOLVER must be an IPv4 address") from None
    return DriverConfiguration(
        host=environment.get("MZM_SANDBOXD_HOST", "0.0.0.0"),  # noqa: S104 - the internal network only (OPS-003)
        port=_integer(environment, "MZM_SANDBOXD_PORT", 8100, 1, 65535),
        token=token,
        image=_required(environment, "MZM_SANDBOX_IMAGE"),
        runtime=environment.get("MZM_SANDBOX_RUNTIME", "runsc") or "runsc",
        netguard_container=environment.get("MZM_NETGUARD_CONTAINER", "mazzamurello-netguard"),
        resolver=resolver,
        cpus=_cpus(environment),
        memory_mb=_integer(environment, "MZM_SANDBOX_MEMORY_MB", 1024, 64, 262144),
        processes=_integer(environment, "MZM_SANDBOX_PROCESSES", 512, 16, 65536),
        command_timeout_seconds=_integer(environment, "MZM_SANDBOX_COMMAND_TIMEOUT_SECONDS", 300, 1, 86400),
        max_output_bytes=_integer(environment, "MZM_SANDBOX_MAX_OUTPUT_BYTES", 1048576, 1024, 67108864),
        idle_minutes=_integer(environment, "MZM_SANDBOX_IDLE_MINUTES", 30, 1, 10080),
    )
