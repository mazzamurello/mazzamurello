"""The user's sandbox, as the agent's workspace (AGT-011, SBX-001, SBX-009, ADR-0035).

The control plane never talks to the container runtime: it calls the sandbox
driver's API (specs/contracts/sandbox-driver.yaml) with the shared secret.
The sandbox is derived from the run's authenticated tenant and user; a
workspace reference that names any other sandbox is declined.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import WorkspaceRef
from pydantic_ai.workspaces import (
    CommandResult,
    WorkspaceBackend,
    WorkspaceCommand,
    WorkspaceTimeoutError,
    WorkspaceUnavailableError,
)

from mazzamurello_server.gateway import RunDeps

PROVIDER = "mazzamurello-sandbox"
WORKING_DIR = "/workspace"
REQUEST_GRACE_SECONDS = 30


@dataclass(frozen=True)
class SandboxDriver:
    """Where the sandbox driver listens, and the secret it expects."""

    url: str
    token: str


class SandboxBackend:
    """A workspace backend on one user's sandbox, through the driver."""

    def __init__(self, driver: SandboxDriver, tenant_id: str, user_id: str) -> None:
        self._driver = driver
        self._path = f"/sandboxes/{tenant_id}/{user_id}"
        self._ref = WorkspaceRef(provider=PROVIDER, id=f"{tenant_id}/{user_id}")

    @property
    def ref(self) -> WorkspaceRef | None:
        return self._ref

    async def working_dir(self) -> str:
        return WORKING_DIR

    async def run(
        self,
        command: WorkspaceCommand,
        *,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,  # noqa: ASYNC109 - the workspace protocol's parameter
    ) -> CommandResult:
        request: dict[str, Any] = {"env": dict(env or {})}
        if shell:
            if not isinstance(command, str):
                raise TypeError("a shell command must be a string")
            request["shell_command"] = command
        else:
            if isinstance(command, str):
                raise TypeError("an argv command must be a sequence of strings")
            request["argv"] = list(_argv(command))
        if timeout is not None:
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("the timeout must be a positive finite number of seconds")
            request["timeout_seconds"] = max(1, math.ceil(timeout))
        stdout: list[str] = []
        stderr: list[str] = []
        exit_object: dict[str, Any] | None = None
        try:
            async with (
                httpx.AsyncClient(
                    base_url=self._driver.url,
                    headers={"Authorization": f"Bearer {self._driver.token}"},
                    timeout=httpx.Timeout(10, read=(timeout or 300) + REQUEST_GRACE_SECONDS),
                ) as client,
                client.stream("POST", f"{self._path}/exec", json=request) as response,
            ):
                if response.status_code != 200:
                    await response.aread()
                    raise WorkspaceUnavailableError(f"the sandbox is unavailable ({response.status_code})")
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    item: dict[str, Any] = json.loads(line)
                    if item["kind"] == "output":
                        (stdout if item["stream"] == "stdout" else stderr).append(item["data"])
                    else:
                        exit_object = item
        except httpx.HTTPError as error:
            raise WorkspaceUnavailableError(f"the sandbox driver is unreachable: {error}") from error
        if exit_object is None:
            raise WorkspaceUnavailableError("the sandbox ended the command without an exit status")
        if exit_object["timed_out"]:
            raise WorkspaceTimeoutError("the command timed out", stdout="".join(stdout), stderr="".join(stderr))
        # A command killed by a signal reports the shell's convention for it.
        exit_code = exit_object["exit_code"]
        return CommandResult(
            exit_code=137 if exit_code is None else int(exit_code), stdout="".join(stdout), stderr="".join(stderr)
        )


def _argv(command: Sequence[str]) -> Sequence[str]:
    if not command:
        raise ValueError("an argv command needs a program")
    return command


@dataclass
class SandboxWorkspace(AbstractCapability[RunDeps]):
    """Gives each run the sandbox of the user it acts for (SBX-001, ADR-0035)."""

    def get_workspace(self, ctx: RunContext[RunDeps], *, ref: WorkspaceRef | None) -> WorkspaceBackend | None:
        deps = ctx.deps
        driver = SandboxDriver(deps.sandboxd_url, deps.sandboxd_token)
        backend = SandboxBackend(driver, str(deps.identity.tenant_id), str(deps.identity.user_id))
        if ref is not None and ref != backend.ref:
            # A reference from history never points the run at another sandbox.
            return None
        return backend
