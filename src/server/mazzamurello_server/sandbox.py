"""The conversation's sandbox, as the agent's workspace (AGT-011, SBX-001, SBX-009, ADR-0035, ADR-0078).

The control plane never talks to the container runtime: it calls the sandbox
driver's API (specs/contracts/sandbox-driver.yaml) with the shared secret.
The sandbox is derived from the run's authenticated tenant and user and its
conversation; a workspace reference that names any other sandbox is declined.
"""

from __future__ import annotations

import json
import logging
import math
import uuid
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

from mazzamurello_server import errors
from mazzamurello_server.database import Identity
from mazzamurello_server.gateway import RunDeps

logger = logging.getLogger(__name__)

PROVIDER = "mazzamurello-sandbox"
# Commands start in the scratch folder; only /workspace persists (SBX-018, ADR-0076).
WORKING_DIR = "/scratch"
REQUEST_GRACE_SECONDS = 30
# How long deleting or copying a workspace may take.
DRIVER_TIMEOUT_SECONDS = 600
# The share of its quota above which the agent is told how full the workspace is (SBX-019).
QUOTA_WARNING_SHARE = 0.8


@dataclass(frozen=True)
class SandboxDriver:
    """Where the sandbox driver listens, and the secret it expects."""

    url: str
    token: str


class SandboxBackend:
    """A workspace backend on one conversation's sandbox, through the driver."""

    def __init__(self, driver: SandboxDriver, tenant_id: str, user_id: str, conversation_id: str) -> None:
        self._driver = driver
        self._path = f"/sandboxes/{tenant_id}/{user_id}/{conversation_id}"
        self._ref = sandbox_ref(tenant_id, user_id, conversation_id)

    @property
    def ref(self) -> WorkspaceRef | None:
        return self._ref

    @property
    def path(self) -> str:
        """The sandbox's path in the driver's API."""
        return self._path

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
        if note := _quota_note(exit_object.get("workspace_bytes"), exit_object.get("workspace_quota_bytes")):
            stderr.append(note)
        return CommandResult(
            exit_code=137 if exit_code is None else int(exit_code), stdout="".join(stdout), stderr="".join(stderr)
        )


def _quota_note(used: object, quota: object) -> str | None:
    """What the agent is told about a workspace near or over its quota (SBX-019), or nothing."""
    if not isinstance(used, int) or not isinstance(quota, int) or quota <= 0 or used <= quota * QUOTA_WARNING_SHARE:
        return None
    sizes = f"{used / 1_048_576:.1f} MiB of its {quota / 1_048_576:.1f} MiB quota"
    if used > quota:
        return (
            f"\n[The workspace, /workspace, exceeds its quota: {sizes}. Remove what the user does not need there,"
            " or ask the user what to remove.]\n"
        )
    return (
        f"\n[The workspace, /workspace, uses {sizes}. Keep there only what the user needs; remove what can be"
        " made or fetched again.]\n"
    )


def sandbox_ref(tenant_id: str, user_id: str, conversation_id: str) -> WorkspaceRef:
    """The reference of a conversation's sandbox, as the history records it."""
    return WorkspaceRef(provider=PROVIDER, id=f"{tenant_id}/{user_id}/{conversation_id}")


def backend_for(deps: RunDeps) -> SandboxBackend:
    """The sandbox of the run's conversation, for the user it acts for (SBX-001)."""
    return SandboxBackend(
        SandboxDriver(deps.sandboxd_url, deps.sandboxd_token),
        str(deps.identity.tenant_id),
        str(deps.identity.user_id),
        str(deps.conversation_id),
    )


async def workspace_request(
    driver: SandboxDriver,
    identity: Identity,
    conversation_id: uuid.UUID,
    method: str,
    json: dict[str, str] | None = None,
) -> None:
    """Delete or copy a conversation's workspace through the driver (SBX-010, ADR-0078); refused as unavailable."""
    path = f"/sandboxes/{identity.tenant_id}/{identity.user_id}/{conversation_id}/workspace"
    try:
        async with httpx.AsyncClient(
            base_url=driver.url, headers={"Authorization": f"Bearer {driver.token}"}, timeout=DRIVER_TIMEOUT_SECONDS
        ) as client:
            response = await client.request(method, path if json is None else f"{path}/copy", json=json)
    except httpx.HTTPError as error:
        raise errors.ApiError(503, "sandbox.unavailable", "The sandbox is unavailable") from error
    if response.status_code != 204:
        raise errors.ApiError(503, "sandbox.unavailable", "The sandbox is unavailable")


async def stop_conversation_sandbox(driver: SandboxDriver, identity: Identity, conversation_id: uuid.UUID) -> None:
    """Remove a conversation's sandbox, as its run is stopped (SBX-018); the driver's idle limit is the safety net."""
    path = f"/sandboxes/{identity.tenant_id}/{identity.user_id}/{conversation_id}/stop"
    try:
        async with httpx.AsyncClient(
            base_url=driver.url, headers={"Authorization": f"Bearer {driver.token}"}, timeout=30
        ) as client:
            await client.post(path)
    except httpx.HTTPError:
        logger.warning("the sandbox of conversation %s could not be stopped", conversation_id)


async def stop_sandbox(deps: RunDeps) -> None:
    """Remove the conversation's sandbox, as its answer ends: what it started ends with it (SBX-018, ADR-0078)."""
    backend = backend_for(deps)
    async with httpx.AsyncClient(
        base_url=deps.sandboxd_url, headers={"Authorization": f"Bearer {deps.sandboxd_token}"}, timeout=30
    ) as client:
        await client.post(f"{backend.path}/stop")


def _argv(command: Sequence[str]) -> Sequence[str]:
    if not command:
        raise ValueError("an argv command needs a program")
    return command


@dataclass
class SandboxWorkspace(AbstractCapability[RunDeps]):
    """Gives each run the sandbox of the user it acts for (SBX-001, ADR-0035)."""

    def get_workspace(self, ctx: RunContext[RunDeps], *, ref: WorkspaceRef | None) -> WorkspaceBackend | None:
        backend = backend_for(ctx.deps)
        if ref is not None and ref != backend.ref:
            # A reference from history never points the run at another sandbox.
            return None
        return backend
