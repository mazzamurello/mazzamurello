"""The fixed sandbox policy (ADR-0022, ADR-0053): nothing in a request can change it."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sibillo_sandboxd.config import DriverConfiguration

NETWORK = "sibillo-sandboxes"
BRIDGE_INTERFACE = "sibillosbx0"
WORKSPACE = "/workspace"
# Where commands start: discarded with the sandbox, unlike the workspace (SBX-018, ADR-0076).
SCRATCH = "/scratch"
LABEL = "dev.sibillo.sandbox"
MIB = 1024 * 1024


@dataclass(frozen=True)
class SandboxId:
    """A conversation's sandbox and workspace: its tenant, its user and the conversation (SBX-001, ADR-0078)."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    conversation_id: uuid.UUID

    @property
    def container(self) -> str:
        return f"sibillo-sandbox-{self.tenant_id}-{self.user_id}-{self.conversation_id}"

    @property
    def volume(self) -> str:
        return f"sibillo-workspace-{self.tenant_id}-{self.user_id}-{self.conversation_id}"

    @property
    def labels(self) -> dict[str, str]:
        return {
            f"{LABEL}.tenant": str(self.tenant_id),
            f"{LABEL}.user": str(self.user_id),
            f"{LABEL}.conversation": str(self.conversation_id),
        }


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
        "WorkingDir": SCRATCH,
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
