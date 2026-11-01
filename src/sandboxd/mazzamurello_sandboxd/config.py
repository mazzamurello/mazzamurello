"""Configuration of the sandbox driver, read only from the environment (ADR-0050, ADR-0053).

specs/contracts/configuration.md lists the variables. Anything missing,
invalid or unknown stops the driver before it listens.
"""

from __future__ import annotations

import ipaddress
import re
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
        "MZM_SANDBOX_MINIMUM_GVISOR_RELEASE",
    }
)
MINIMUM_TOKEN_LENGTH = 32
# The oldest gVisor release the driver accepts (ADR-0053); the instance
# admin may require a newer one, never an older one (ADR-0058).
BUILT_IN_MINIMUM_RELEASE = "release-20261026.0"
RELEASE = re.compile(r"^release-(\d{8})\.(\d+)$")


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
    minimum_release: str = BUILT_IN_MINIMUM_RELEASE


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


def release_key(release: str) -> tuple[int, int] | None:
    found = RELEASE.match(release)
    return None if found is None else (int(found.group(1)), int(found.group(2)))


def _minimum_release(environment: Mapping[str, str]) -> str:
    name = "MZM_SANDBOX_MINIMUM_GVISOR_RELEASE"
    value = environment.get(name, BUILT_IN_MINIMUM_RELEASE) or BUILT_IN_MINIMUM_RELEASE
    key, built_in = release_key(value), release_key(BUILT_IN_MINIMUM_RELEASE)
    if key is None:
        raise ConfigurationError(f"{name} must be a gVisor release such as {BUILT_IN_MINIMUM_RELEASE}")
    if built_in is not None and key < built_in:
        raise ConfigurationError(f"{name} may not be older than the built-in minimum, {BUILT_IN_MINIMUM_RELEASE}")
    return value


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
        minimum_release=_minimum_release(environment),
    )
