"""Sandboxes under test, set up as the test harness contract prescribes ("Sandboxes", ADR-0053).

The images are built from `deploy/images/`, the network guard runs as a
container with host networking and `NET_ADMIN`, and the sandbox driver as a
process with access to Docker. Everything the session creates is removed at
its end.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

import httpx
import pytest

from tests.support.database import ROOT
from tests.support.server import Process

READY_TIMEOUT_SECONDS = 120
BUILD_TIMEOUT_SECONDS = 900
SANDBOX_NETWORK = "mazzamurello-sandboxes"
EGRESS_TABLE = "inet mazzamurello"
# Small limits, so that tests can reach them (SBX-011).
TEST_LIMITS = {
    "MZM_SANDBOX_CPUS": "0.5",
    "MZM_SANDBOX_MEMORY_MB": "256",
    "MZM_SANDBOX_PROCESSES": "64",
    "MZM_SANDBOX_COMMAND_TIMEOUT_SECONDS": "8",
    "MZM_SANDBOX_MAX_OUTPUT_BYTES": "65536",
    "MZM_SANDBOX_IDLE_MINUTES": "30",
}


def docker(*args: str, timeout: float = 120, check: bool = True) -> str:
    result = subprocess.run(  # noqa: S603 - the Docker CLI, with arguments from the tests
        ["docker", *args],  # noqa: S607 - Docker from the PATH, as an operator runs it
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout


@dataclass(frozen=True)
class ExecResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool


@dataclass(frozen=True)
class Driver:
    """The sandbox driver of the test session, and what the session built for it."""

    url: str
    token: str
    image: str
    netguard: str
    process: Process

    def client(self, token: str | None = None) -> httpx.Client:
        return httpx.Client(base_url=self.url, headers={"Authorization": f"Bearer {token or self.token}"}, timeout=120)

    def exec(self, tenant_id: str, user_id: str, request: Mapping[str, Any]) -> ExecResult:
        """Run a command in a user's sandbox and collect its streamed output."""
        stdout: list[str] = []
        stderr: list[str] = []
        exit_object: dict[str, Any] | None = None
        with (
            self.client() as client,
            client.stream("POST", f"/sandboxes/{tenant_id}/{user_id}/exec", json=dict(request)) as response,
        ):
            assert response.status_code == 200, response.read().decode()
            for line in response.iter_lines():
                if not line:
                    continue
                item = cast(dict[str, Any], json.loads(line))
                if item["kind"] == "output":
                    (stdout if item["stream"] == "stdout" else stderr).append(item["data"])
                else:
                    assert exit_object is None, "more than one exit object"
                    exit_object = item
        assert exit_object is not None, "the stream ended without an exit object"
        return ExecResult(
            exit_object["exit_code"],
            "".join(stdout),
            "".join(stderr),
            exit_object["timed_out"],
            exit_object["truncated"],
        )

    def sh(self, tenant_id: str, user_id: str, command: str, **options: Any) -> ExecResult:
        return self.exec(tenant_id, user_id, {"shell_command": command} | options)

    def sandbox_containers(self) -> list[dict[str, Any]]:
        """`docker inspect` of every container of the session's sandbox image."""
        ids = docker("ps", "-aq", "--filter", f"ancestor={self.image}").split()
        if not ids:
            return []
        return cast(list[dict[str, Any]], json.loads(docker("inspect", *ids)))

    def wait_until_ready(self, timeout: float = READY_TIMEOUT_SECONDS) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: Any = None
        while time.monotonic() < deadline:
            if self.process.exited() is not None:
                raise RuntimeError(f"the sandbox driver exited:\n{self.process.output()}")
            try:
                with self.client() as client:
                    response = client.get("/health")
                last = response.text
                if response.status_code == 200:
                    return cast(dict[str, Any], response.json())
            except httpx.TransportError as error:
                last = repr(error)
            time.sleep(0.5)
        raise RuntimeError(f"the sandbox driver was not ready: {last}\n{self.process.output()}")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _build(name: str, tag: str) -> None:
    # From the repository root, so that an image may include project code.
    dockerfile = ROOT / "deploy" / "images" / name / "Dockerfile"
    docker("build", "--quiet", "--tag", tag, "--file", str(dockerfile), str(ROOT), timeout=BUILD_TIMEOUT_SECONDS)


def _wait_healthy(container: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    status = ""
    while time.monotonic() < deadline:
        status = docker("inspect", "--format", "{{.State.Health.Status}}", container, check=False).strip()
        if status == "healthy":
            return
        time.sleep(0.5)
    logs = docker("logs", container, check=False)
    raise RuntimeError(f"the network guard is {status or 'missing'}:\n{logs}")


def start_driver_process(environment: Mapping[str, str]) -> Process:
    base = {name: value for name, value in os.environ.items() if not name.startswith("MZM_")}
    return Process("sandboxd", base | dict(environment), module="mazzamurello_sandboxd", command=None)


def driver_environment(token: str, image: str, netguard: str, port: int, **overrides: str) -> dict[str, str]:
    return {
        "MZM_SANDBOXD_HOST": "127.0.0.1",
        "MZM_SANDBOXD_PORT": str(port),
        "MZM_SANDBOXD_TOKEN": token,
        "MZM_SANDBOX_IMAGE": image,
        "MZM_NETGUARD_CONTAINER": netguard,
        **TEST_LIMITS,
        **overrides,
    }


def _cleanup(image: str, guard_image: str, netguard: str, driver: Process | None) -> None:
    if driver is not None:
        driver.close()
    # Stopped, not killed: the guard removes its table from the host as it stops.
    docker("stop", "--time", "15", netguard, check=False)
    docker("rm", "-f", netguard, check=False)
    ids = docker("ps", "-aq", "--filter", f"ancestor={image}", check=False).split()
    if ids:
        volumes = {
            mount["Name"]
            for container in cast(list[dict[str, Any]], json.loads(docker("inspect", *ids, check=False) or "[]"))
            for mount in container.get("Mounts", [])
            if mount.get("Type") == "volume"
        }
        docker("rm", "-f", *ids, check=False)
        if volumes:
            docker("volume", "rm", "-f", *volumes, check=False)
    docker("network", "rm", SANDBOX_NETWORK, check=False)
    docker("rmi", "-f", image, guard_image, check=False)


_DRIVER = pytest.StashKey[Driver | BaseException]()


def start_sandboxes(config: pytest.Config) -> Driver:
    """Build the images, start the network guard and the sandbox driver, once per test session."""
    cached = config.stash.get(_DRIVER, None)
    if isinstance(cached, BaseException):
        raise cached
    if cached is not None:
        return cached

    suffix = secrets.token_hex(4)
    image, guard_image = f"mazzamurello-test/sandbox:{suffix}", f"mazzamurello-test/netguard:{suffix}"
    netguard = f"mazzamurello-test-netguard-{suffix}"
    holder: dict[str, Process] = {}
    config.add_cleanup(lambda: _cleanup(image, guard_image, netguard, holder.get("driver")))
    try:
        _build("sandbox", image)
        _build("netguard", guard_image)
        docker("run", "--detach", "--name", netguard, "--network", "host", "--cap-add", "NET_ADMIN", guard_image)
        _wait_healthy(netguard)
        token, port = secrets.token_urlsafe(32), _free_port()
        holder["driver"] = start_driver_process(driver_environment(token, image, netguard, port))
        driver = Driver(f"http://127.0.0.1:{port}/v1", token, image, netguard, holder["driver"])
        driver.wait_until_ready()
    except BaseException as exc:
        config.stash[_DRIVER] = exc
        raise
    config.stash[_DRIVER] = driver
    return driver


def free_port() -> int:
    return _free_port()
