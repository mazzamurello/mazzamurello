"""Sandboxes on Docker: one per user, commands executed in them (SBX-001, SBX-011, ADR-0022, ADR-0053)."""

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
from typing import Any

import aiodocker
from aiodocker.exceptions import DockerError

from mazzamurello_sandboxd.config import DriverConfiguration
from mazzamurello_sandboxd.policy import (
    LABEL,
    NETWORK,
    WORKSPACE,
    container_config,
    container_name,
    network_config,
    volume_name,
)

logger = logging.getLogger("mazzamurello.sandboxd")

STOP_GRACE_SECONDS = 2
# Time beyond a command's timeout before the driver stops waiting for it.
TIMEOUT_GRACE_SECONDS = 10
KILLED_EXIT_CODES = frozenset({124, 137})
NOT_FOUND = 404


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
        execute = await container.exec(cmd=list(argv), stdout=True, stderr=True, stdin=False, user="root")
        async with execute.start(detach=False) as stream:
            while await stream.read_out() is not None:
                pass
        return int((await execute.inspect())["ExitCode"] or 0)

    async def ensure(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
        """The user's sandbox, created or started if needed (idempotent)."""
        name = container_name(tenant_id, user_id)
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            try:
                container = await self.docker.containers.get(name)
                info = await container.show()
                if not info["State"]["Running"]:
                    await container.start()
                    await self._write_resolver(container)
            except DockerError as error:
                if error.status != NOT_FOUND:
                    raise
                labels = {f"{LABEL}.tenant": str(tenant_id), f"{LABEL}.user": str(user_id)}
                container = await self.start_container(name, volume_name(tenant_id, user_id), labels)
            info = await container.show()
            self._last_used[name] = time.monotonic()
        return {"state": "running", "started_at": info["State"]["StartedAt"], "working_dir": WORKSPACE}

    async def stop(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
        name = container_name(tenant_id, user_id)
        try:
            container = await self.docker.containers.get(name)
            await container.stop(t=STOP_GRACE_SECONDS)
        except DockerError as error:
            if error.status != NOT_FOUND:
                raise
        self._last_used.pop(name, None)

    async def stop_all(self) -> int:
        """Stop every running sandbox, as when the egress rules disappear (SBX-015)."""
        containers = await self.docker.containers.list(filters=json.dumps({"label": [f"{LABEL}=sandbox"]}))
        await asyncio.gather(*(container.stop(t=0) for container in containers), return_exceptions=True)
        self._last_used.clear()
        return len(containers)

    async def stop_idle(self) -> None:
        limit = self.configuration.idle_minutes * 60
        now = time.monotonic()
        for name, last in list(self._last_used.items()):
            if now - last > limit:
                with contextlib.suppress(DockerError):
                    await (await self.docker.containers.get(name)).stop(t=STOP_GRACE_SECONDS)
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
            workdir=workdir or WORKSPACE,
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
        )
