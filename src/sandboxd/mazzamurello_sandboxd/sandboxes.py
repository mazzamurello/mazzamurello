"""Sandboxes on Docker: one per user, commands executed in them (SBX-001, SBX-011, ADR-0022, ADR-0053).

A sandbox that stops is removed; the next command gets a new one from the
image, with only the user's workspace (SBX-018, ADR-0076).
"""

# aiodocker leaves some parameters untyped; only those checks are relaxed here.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
import codecs
import contextlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiodocker
from aiodocker.exceptions import DockerError

from mazzamurello_sandboxd.config import DriverConfiguration
from mazzamurello_sandboxd.policy import (
    LABEL,
    MIB,
    NETWORK,
    SCRATCH,
    WORKSPACE,
    container_config,
    container_name,
    network_config,
    volume_name,
)
from mazzamurello_sandboxd.workspaces import check_archive, workspace_entries

logger = logging.getLogger("mazzamurello.sandboxd")

STOP_GRACE_SECONDS = 2
# Time beyond a command's timeout before the driver stops waiting for it.
TIMEOUT_GRACE_SECONDS = 10
KILLED_EXIT_CODES = frozenset({124, 137})
NOT_FOUND = 404
ARCHIVE_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class Output:
    stream: str
    data: str


@dataclass(frozen=True)
class Exit:
    exit_code: int | None
    timed_out: bool
    truncated: bool
    duration_ms: int
    # The workspace's size after the command, and its quota (SBX-019).
    workspace_bytes: int
    workspace_quota_bytes: int


class Sandboxes:
    def __init__(self, docker: aiodocker.Docker, configuration: DriverConfiguration) -> None:
        self.docker = docker
        self.configuration = configuration
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_used: dict[str, float] = {}

    async def ensure_network(self) -> dict[str, Any]:
        """The sandbox bridge, created on first use; returns its inspection."""
        try:
            network = await self.docker.networks.get(NETWORK)
        except DockerError as error:
            if error.status != NOT_FOUND:
                raise
            network = await self.docker.networks.create(network_config())
        return await network.show()

    async def start_container(self, name: str, volume: str | None, labels: dict[str, str]) -> Any:
        """Create and start a container with the fixed policy, then point it at the instance's resolver."""
        await self.ensure_network()
        if volume is not None:
            await self.docker.volumes.create({"Name": volume, "Labels": {LABEL: "workspace"} | labels})
        container = await self.docker.containers.create(container_config(self.configuration, volume, labels), name=name)
        await container.start()
        await self._write_resolver(container)
        return container

    async def _write_resolver(self, container: Any) -> None:
        # gVisor cannot use Docker's embedded resolver (ADR-0021).
        line = f"nameserver {self.configuration.resolver}\n"
        await self._run_quietly(container, ["sh", "-c", f"printf '{line}' > /etc/resolv.conf"])

    async def _run_quietly(self, container: Any, argv: Sequence[str]) -> int:
        return (await self._run(container, argv))[0]

    async def _run(self, container: Any, argv: Sequence[str]) -> tuple[int, str]:
        """Run a command of the driver's own in the container: its exit code and standard output."""
        execute = await container.exec(cmd=list(argv), stdout=True, stderr=True, stdin=False, user="root")
        output: list[bytes] = []
        async with execute.start(detach=False) as stream:
            while (message := await stream.read_out()) is not None:
                if message.stream == 1:
                    output.append(message.data)
        return int((await execute.inspect())["ExitCode"] or 0), b"".join(output).decode(errors="replace")

    async def _workspace_bytes(self, container: Any) -> int:
        """The workspace's size, measured inside the sandbox (SBX-019)."""
        try:
            code, output = await self._run(container, ["du", "-sb", WORKSPACE])
            return int(output.split()[0]) if code == 0 and output else 0
        except (DockerError, ValueError, IndexError):
            logger.warning("the workspace of %s could not be measured", container.id)
            return 0

    async def ensure(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
        """The user's sandbox, created or started if needed (idempotent)."""
        name = container_name(tenant_id, user_id)
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            container: Any = None
            try:
                container = await self.docker.containers.get(name)
                if not (await container.show())["State"]["Running"]:
                    # A sandbox that stopped is never started again: a new one is (SBX-018).
                    await container.delete(force=True)
                    container = None
            except DockerError as error:
                if error.status != NOT_FOUND:
                    raise
            if container is None:
                labels = {f"{LABEL}.tenant": str(tenant_id), f"{LABEL}.user": str(user_id)}
                container = await self.start_container(name, volume_name(tenant_id, user_id), labels)
            info = await container.show()
            self._last_used[name] = time.monotonic()
        return {"state": "running", "started_at": info["State"]["StartedAt"], "working_dir": SCRATCH}

    async def stop(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        name = container_name(tenant_id, user_id)
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            await self._remove(name)
        self._last_used.pop(name, None)

    async def _remove(self, name: str) -> None:
        """Stop a sandbox and remove its container, keeping its workspace (SBX-018)."""
        try:
            container = await self.docker.containers.get(name)
            with contextlib.suppress(DockerError):
                await container.stop(t=STOP_GRACE_SECONDS)
            await container.delete(force=True)
        except DockerError as error:
            if error.status != NOT_FOUND:
                raise

    async def stop_all(self) -> int:
        """Stop every running sandbox, as when the egress rules disappear (SBX-015)."""
        containers = await self.docker.containers.list(filters=json.dumps({"label": [f"{LABEL}=sandbox"]}))
        await asyncio.gather(*(container.delete(force=True) for container in containers), return_exceptions=True)
        self._last_used.clear()
        return len(containers)

    async def stop_idle(self) -> None:
        limit = self.configuration.idle_minutes * 60
        now = time.monotonic()
        for name, last in list(self._last_used.items()):
            if now - last > limit:
                with contextlib.suppress(DockerError):
                    await self._remove(name)
                self._last_used.pop(name, None)
                logger.info("stopped idle sandbox %s", name)

    async def execute(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        workdir: str | None,
        timeout_seconds: int | None,
        max_output_bytes: int | None,
    ) -> AsyncIterator[Output | Exit]:
        """Run a command in the user's sandbox: its output, then exactly one exit."""
        await self.ensure(tenant_id, user_id)
        container = await self.docker.containers.get(container_name(tenant_id, user_id))
        timeout = min(
            timeout_seconds or self.configuration.command_timeout_seconds, self.configuration.command_timeout_seconds
        )
        limit = min(max_output_bytes or self.configuration.max_output_bytes, self.configuration.max_output_bytes)
        # `timeout` kills the command's whole process group when it runs out (ADR-0053).
        command = ["timeout", "--signal=KILL", str(timeout), *argv]
        started = time.monotonic()
        execute = await container.exec(
            cmd=command,
            stdout=True,
            stderr=True,
            stdin=False,
            user="root",
            workdir=workdir or SCRATCH,
            environment={key: value for key, value in env.items()},
        )
        decoders = {
            1: codecs.getincrementaldecoder("utf-8")(errors="replace"),
            2: codecs.getincrementaldecoder("utf-8")(errors="replace"),
        }
        sent = 0
        truncated = False
        finished_in_time = True
        try:
            async with asyncio.timeout(timeout + TIMEOUT_GRACE_SECONDS), execute.start(detach=False) as stream:  # ty: ignore[invalid-context-manager]
                while (message := await stream.read_out()) is not None:
                    data: bytes = message.data
                    if truncated:
                        continue
                    if sent + len(data) > limit:
                        data = data[: limit - sent]
                        truncated = True
                    sent += len(data)
                    text = decoders[message.stream].decode(data)
                    if text:
                        yield Output("stdout" if message.stream == 1 else "stderr", text)
        except TimeoutError:
            finished_in_time = False
        for number, decoder in decoders.items():
            tail = decoder.decode(b"", final=True)
            if tail and not truncated:
                yield Output("stdout" if number == 1 else "stderr", tail)
        exit_code: int | None = None
        if finished_in_time:
            exit_code = (await execute.inspect()).get("ExitCode")
        elapsed = time.monotonic() - started
        timed_out = not finished_in_time or (exit_code in KILLED_EXIT_CODES and elapsed >= timeout)
        self._last_used[container_name(tenant_id, user_id)] = time.monotonic()
        yield Exit(
            exit_code=None if timed_out else exit_code,
            timed_out=timed_out,
            truncated=truncated,
            duration_ms=int(elapsed * 1000),
            workspace_bytes=await self._workspace_bytes(container),
            workspace_quota_bytes=self.configuration.workspace_quota_mb * MIB,
        )

    async def export_workspace(self, tenant_id: uuid.UUID, user_id: uuid.UUID, destination: Path) -> None:
        """Write the user's workspace to `destination` as a tar archive of paths relative to it (SBX-020)."""
        await self.ensure(tenant_id, user_id)
        container = await self.docker.containers.get(container_name(tenant_id, user_id))
        raw = destination.with_name(f"{destination.name}.docker")
        try:
            async with self.docker._query(  # pyright: ignore[reportPrivateUsage]
                f"containers/{container.id}/archive", params={"path": WORKSPACE}
            ) as response:
                with raw.open("wb") as file:
                    async for chunk in response.content.iter_chunked(ARCHIVE_CHUNK_BYTES):
                        await asyncio.to_thread(file.write, chunk)
            await asyncio.to_thread(workspace_entries, raw, destination, WORKSPACE)
        finally:
            raw.unlink(missing_ok=True)

    async def import_workspace(self, tenant_id: uuid.UUID, user_id: uuid.UUID, source: Path) -> None:
        """Replace the user's workspace with the archive at `source`, unpacked by Docker, run by no one (SBX-020).

        The workspace is emptied first; an archive that would write outside it
        is refused whole, leaving it empty. The sandbox is removed afterwards,
        so that the next command sees the workspace as unpacked.
        """
        name = container_name(tenant_id, user_id)
        await self.ensure(tenant_id, user_id)
        container = await self.docker.containers.get(name)
        try:
            await self._run_quietly(container, ["find", WORKSPACE, "-mindepth", "1", "-delete"])
            await asyncio.to_thread(check_archive, source)
            with source.open("rb") as file:
                async with self.docker._query(  # pyright: ignore[reportPrivateUsage]
                    f"containers/{container.id}/archive",
                    method="PUT",
                    params={"path": WORKSPACE},
                    data=file,
                    headers={"content-type": "application/x-tar"},
                ) as response:
                    await response.read()
        finally:
            await self.stop(tenant_id, user_id)
