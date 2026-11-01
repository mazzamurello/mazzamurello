"""The fixed sandbox policy (ADR-0022, ADR-0053): nothing in a request can change it."""

from __future__ import annotations

import uuid
from typing import Any

from mazzamurello_sandboxd.config import DriverConfiguration

NETWORK = "mazzamurello-sandboxes"
BRIDGE_INTERFACE = "mzmsbx0"
WORKSPACE = "/workspace"
LABEL = "dev.mazzamurello.sandbox"
MIB = 1024 * 1024


def container_name(tenant_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return f"mzm-sandbox-{tenant_id}-{user_id}"


def volume_name(tenant_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return f"mzm-workspace-{tenant_id}-{user_id}"


def network_config() -> dict[str, Any]:
    """The sandbox bridge (ADR-0021): fixed interface name, no traffic between sandboxes, no IPv6."""
    return {
        "Name": NETWORK,
        "Driver": "bridge",
        "EnableIPv6": False,
        "Internal": False,
        "Options": {
            "com.docker.network.bridge.name": BRIDGE_INTERFACE,
            "com.docker.network.bridge.enable_icc": "false",
            "com.docker.network.bridge.enable_ip_masquerade": "true",
        },
        "Labels": {LABEL: "network"},
    }


def container_config(configuration: DriverConfiguration, volume: str | None, labels: dict[str, str]) -> dict[str, Any]:
    """A sandbox container: gVisor, the sandbox bridge, the limits, no privileges, no credentials.

    `volume` is the user's workspace, the only mount; the canary has none.
    """
    mounts = [] if volume is None else [{"Type": "volume", "Source": volume, "Target": WORKSPACE}]
    memory = configuration.memory_mb * MIB
    return {
        "Image": configuration.image,
        "Cmd": ["sleep", "infinity"],
        "WorkingDir": WORKSPACE,
        "Hostname": "sandbox",
        # No credentials, and nothing from the driver's environment (SBX-008).
        "Env": [],
        "Labels": {LABEL: "sandbox"} | labels,
        "HostConfig": {
            "Runtime": configuration.runtime,
            "NetworkMode": NETWORK,
            "Dns": [configuration.resolver],
            "NanoCpus": int(configuration.cpus * 1_000_000_000),
            "Memory": memory,
            "MemorySwap": memory,
            # Docker's pids limit counts gVisor's own threads, not the sandbox's
            # processes, and breaks programs at small values: RLIMIT_NPROC counts
            # the processes inside the sandbox (ADR-0022).
            "Ulimits": [{"Name": "nproc", "Soft": configuration.processes, "Hard": configuration.processes}],
            "Mounts": mounts,
            "Privileged": False,
            "SecurityOpt": ["no-new-privileges"],
            "RestartPolicy": {"Name": "no"},
        },
    }
