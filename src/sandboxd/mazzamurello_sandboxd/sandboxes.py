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
import tarfile
import time
import uuid
import zipfile
from collections.abc import AsyncGenerator, AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiodocker
from aiodocker.exceptions import DockerError

from mazzamurello_sandboxd.config import DriverConfiguration
from mazzamurello_sandboxd.files import (
    HELPER,
    FileOperationError,
    file_header,
    padding,
    relative,
    tar_member_content,
)
from mazzamurello_sandboxd.policy import (
    LABEL,
    MIB,
    NETWORK,
    SCRATCH,
    WORKSPACE,
    SandboxId,
    container_config,
    network_config,
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
        # When each sandbox last ran a command, as a run uses it: a file operation leaves those running.
        self._commanded: dict[str, float] = {}

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
            # Labelled with the image too, so that what a driver created can be told from another's.
            image = {f"{LABEL}.image": self.configuration.image}
            await self.docker.volumes.create({"Name": volume, "Labels": {LABEL: "workspace"} | labels | image})
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

    async def ensure(self, sandbox: SandboxId) -> dict[str, Any]:
        """The conversation's sandbox, created if needed (idempotent)."""
        name = sandbox.container
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
                container = await self.start_container(name, sandbox.volume, sandbox.labels)
            info = await container.show()
            self._last_used[name] = time.monotonic()
        return {"state": "running", "started_at": info["State"]["StartedAt"], "working_dir": SCRATCH}

    async def stop(self, sandbox: SandboxId) -> None:
        name = sandbox.container
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
        """Stop and remove every sandbox of this driver's image, running or not.

        As when the egress rules disappear (SBX-015), and when the driver starts,
        so that no sandbox is left that the driver does not track (SBX-018,
        ADR-0078). Another driver's sandboxes, of another image, are left alone.
        """
        filters = {"label": [f"{LABEL}=sandbox"], "ancestor": [self.configuration.image]}
        containers = await self.docker.containers.list(all=True, filters=json.dumps(filters))
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
        sandbox: SandboxId,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        workdir: str | None,
        timeout_seconds: int | None,
        max_output_bytes: int | None,
    ) -> AsyncIterator[Output | Exit]:
        """Run a command in the conversation's sandbox: its output, then exactly one exit."""
        await self.ensure(sandbox)
        container = await self.docker.containers.get(sandbox.container)
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
        self._last_used[sandbox.container] = time.monotonic()
        self._commanded[sandbox.container] = time.monotonic()
        yield Exit(
            exit_code=None if timed_out else exit_code,
            timed_out=timed_out,
            truncated=truncated,
            duration_ms=int(elapsed * 1000),
            workspace_bytes=await self._workspace_bytes(container),
            workspace_quota_bytes=self.configuration.workspace_quota_mb * MIB,
        )

    async def export_workspace(self, sandbox: SandboxId, destination: Path) -> None:
        """Write the conversation's workspace to `destination` as a tar archive of paths relative to it (SBX-020)."""
        await self.ensure(sandbox)
        container = await self.docker.containers.get(sandbox.container)
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

    async def import_workspace(self, sandbox: SandboxId, source: Path) -> None:
        """Replace the conversation's workspace with the archive at `source`, unpacked by Docker (SBX-020).

        Nothing from the archive is run.

        The workspace is emptied first; an archive that would write outside it
        is refused whole, leaving it empty. The sandbox is removed afterwards,
        so that the next command sees the workspace as unpacked.
        """
        await self.ensure(sandbox)
        container = await self.docker.containers.get(sandbox.container)
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
            await self.stop(sandbox)

    async def delete_workspace(self, sandbox: SandboxId) -> None:
        """Remove the conversation's sandbox and delete its workspace, as the conversation is deleted (SBX-010)."""
        await self.stop(sandbox)
        try:
            await (await self.docker.volumes.get(sandbox.volume)).delete()
        except DockerError as error:
            if error.status != NOT_FOUND:
                raise

    async def copy_workspace(self, sandbox: SandboxId, source: SandboxId, folder: Path) -> None:
        """Replace the conversation's workspace with a copy of `source`'s, for a fork (SBX-010, CNV-005)."""
        archive = folder / "workspace.tar"
        await self.export_workspace(source, archive)
        await self.import_workspace(sandbox, archive)

    # --- Files of the workspace (SBX-014, ADR-0079) ---

    async def _helper(self, container: Any, *args: str) -> dict[str, Any]:
        """Run the driver's file helper in the sandbox; its answer, or the refusal it reports."""
        code, output = await self._run(container, ["python3", "-I", "-c", HELPER, *args])
        try:
            answer: dict[str, Any] = json.loads(output.strip().splitlines()[-1])
        except (ValueError, IndexError) as error:
            raise FileOperationError(503, f"the file helper failed ({code})") from error
        if "error" in answer:
            raise FileOperationError(int(answer["status"]), str(answer["error"]))
        return answer

    async def _borrow(self, sandbox: SandboxId) -> tuple[Any, bool, float]:
        """The sandbox's container for a file operation: whether it was running, and when the operation began."""
        running = False
        with contextlib.suppress(DockerError):
            running = bool((await (await self.docker.containers.get(sandbox.container)).show())["State"]["Running"])
        began = time.monotonic()
        await self.ensure(sandbox)
        return await self.docker.containers.get(sandbox.container), running, began

    async def _give_back(self, sandbox: SandboxId, running: bool, began: float) -> None:
        """Remove a sandbox started for a file operation, unless a command used it meanwhile (SBX-018)."""
        if running or self._commanded.get(sandbox.container, 0.0) > began:
            return
        await self.stop(sandbox)

    @contextlib.asynccontextmanager
    async def _borrowed(self, sandbox: SandboxId) -> AsyncGenerator[Any]:
        container, running, began = await self._borrow(sandbox)
        try:
            yield container
        finally:
            await self._give_back(sandbox, running, began)

    async def workspace_size(self, sandbox: SandboxId) -> dict[str, int]:
        async with self._borrowed(sandbox) as container:
            used = await self._workspace_bytes(container)
        return {"bytes": used, "quota_bytes": self.configuration.workspace_quota_mb * MIB}

    async def list_folder(self, sandbox: SandboxId, path: str) -> dict[str, Any]:
        async with self._borrowed(sandbox) as container:
            return await self._helper(container, "list", relative(path))

    async def delete_entry(self, sandbox: SandboxId, path: str) -> None:
        async with self._borrowed(sandbox) as container:
            await self._helper(container, "delete", relative(path))

    async def create_folder(self, sandbox: SandboxId, path: str) -> dict[str, Any]:
        async with self._borrowed(sandbox) as container:
            return await self._helper(container, "mkdir", relative(path))

    async def move_entry(self, sandbox: SandboxId, source: str, target: str) -> dict[str, Any]:
        async with self._borrowed(sandbox) as container:
            return await self._helper(container, "move", relative(source), relative(target))

    async def read_file(self, sandbox: SandboxId, path: str) -> tuple[dict[str, Any], AsyncIterator[bytes]]:
        """A regular file's entry, and its content as a stream that gives the sandbox back when it ends."""
        container, running, began = await self._borrow(sandbox)
        try:
            item = await self._helper(container, "stat", relative(path), "regular")
        except BaseException:
            await self._give_back(sandbox, running, began)
            raise

        async def content() -> AsyncIterator[bytes]:
            try:
                async with self.docker._query(  # pyright: ignore[reportPrivateUsage]
                    f"containers/{container.id}/archive", params={"path": f"{WORKSPACE}/{item['path']}"}
                ) as response:
                    async for piece in tar_member_content(response.content.iter_chunked(ARCHIVE_CHUNK_BYTES)):
                        yield piece
            finally:
                await self._give_back(sandbox, running, began)

        return item, content()

    async def write_file(
        self, sandbox: SandboxId, path: str, length: int, body: AsyncIterator[bytes]
    ) -> dict[str, Any]:
        """Write a new file of `length` bytes from `body`, complete or not at all (SBX-014, SBX-019)."""
        target = relative(path)
        if not target:
            raise FileOperationError(422, "the workspace itself")
        quota = self.configuration.workspace_quota_mb * MIB
        temporary = f".mzm-upload-{uuid.uuid4().hex}"
        async with self._borrowed(sandbox) as container:
            await self._helper(container, "prepare", target, str(length), str(quota))
            received = 0

            async def stream() -> AsyncIterator[bytes]:
                nonlocal received
                yield file_header(temporary, length)
                async for chunk in body:
                    received += len(chunk)
                    if received > length:
                        raise FileOperationError(422, "more than Content-Length")
                    yield chunk
                if received != length:
                    raise FileOperationError(422, "less than Content-Length")
                yield padding(length)

            try:
                async with self.docker._query(  # pyright: ignore[reportPrivateUsage]
                    f"containers/{container.id}/archive",
                    method="PUT",
                    params={"path": WORKSPACE},
                    data=stream(),
                    headers={"content-type": "application/x-tar"},
                ) as response:
                    await response.read()
                if received != length:
                    raise FileOperationError(422, "less than Content-Length")
            except BaseException:
                with contextlib.suppress(Exception):
                    await self._helper(container, "discard", temporary)
                raise
            return await self._helper(container, "commit", temporary, target)

    async def zip_folder(self, sandbox: SandboxId, path: str, destination: Path) -> None:
        """Write a folder of the workspace to `destination` as a zip archive, links left out."""
        folder = relative(path)
        source = f"{WORKSPACE}/{folder}" if folder else WORKSPACE
        raw = destination.with_name(f"{destination.name}.tar")
        async with self._borrowed(sandbox) as container:
            await self._helper(container, "folder", folder)
            try:
                async with self.docker._query(  # pyright: ignore[reportPrivateUsage]
                    f"containers/{container.id}/archive", params={"path": source}
                ) as response:
                    with raw.open("wb") as file:
                        async for chunk in response.content.iter_chunked(ARCHIVE_CHUNK_BYTES):
                            await asyncio.to_thread(file.write, chunk)
                await asyncio.to_thread(zip_from_tar, raw, destination)
            finally:
                raw.unlink(missing_ok=True)


def zip_from_tar(source: Path, destination: Path) -> None:
    """Rewrite Docker's tar of a folder as a zip of its regular files, named relative to that folder."""
    with tarfile.open(source, "r:") as archive, zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as result:
        for member in archive:
            if not member.isreg():
                continue
            name = member.name.split("/", 1)[1] if "/" in member.name else member.name
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            with extracted, result.open(name, "w") as target:
                while chunk := extracted.read(ARCHIVE_CHUNK_BYTES):
                    target.write(chunk)
