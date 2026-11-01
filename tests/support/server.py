"""The API and worker processes under test, started as the test harness contract prescribes.

See specs/contracts/test-harness.md ("Server") and ADR-0050, ADR-0052: the real
processes, configured by environment variables, the API called over HTTP.
"""

from __future__ import annotations

import ipaddress
import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

from tests.support.database import ROOT, Database, uuid7

READY_TIMEOUT_SECONDS = 30
STOP_TIMEOUT_SECONDS = 10


class Process:
    """A server process, with its output in a log file."""

    def __init__(
        self,
        name: str,
        environment: Mapping[str, str],
        *,
        module: str = "mazzamurello_server",
        command: str | None = None,
    ) -> None:
        self.command = name
        self.argv = [sys.executable, "-m", module, *([] if command is None else [command])]
        self.environment = dict(environment)
        self._log = tempfile.NamedTemporaryFile("w+", prefix=f"mzm-{name}-", suffix=".log", delete=False)  # noqa: SIM115
        self._process: subprocess.Popen[str] | None = None
        self.start()

    def start(self) -> None:
        self._process = subprocess.Popen(  # noqa: S603 - the server entry point, not user input
            self.argv,
            cwd=ROOT,
            env=self.environment,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def output(self) -> str:
        self._log.flush()
        return Path(self._log.name).read_text(errors="replace")

    def exited(self) -> int | None:
        return None if self._process is None else self._process.poll()

    def kill(self) -> None:
        """Stop the process at once, as a crash would (AGT-010)."""
        if self._process is not None and self._process.poll() is None:
            self._process.send_signal(signal.SIGKILL)
            self._process.wait()

    def stop(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(STOP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                self.kill()

    def close(self) -> None:
        self.stop()
        self._log.close()


@dataclass(frozen=True)
class Server:
    base_url: str
    api: Process = field(repr=False)
    worker: Process = field(repr=False)

    def client(self, token: str | None = None, source: str | None = None) -> httpx.Client:
        """An HTTP client for the API, authenticated by `token`, from source address `source`."""
        headers = {"X-Forwarded-For": source or fresh_source()}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return httpx.Client(base_url=self.base_url, headers=headers, timeout=30)

    def crash_and_restart_worker(self) -> None:
        self.worker.kill()
        self.worker.start()


def fresh_source() -> str:
    """A source address no other request has used, in the documentation range 2001:db8::/32."""
    return str(ipaddress.IPv6Address(int(ipaddress.IPv6Address("2001:db8::")) + uuid7().int % (1 << 96)))


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wait_until_ready(api: Process, worker: Process, base_url: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        for process in (api, worker):
            if process.exited() is not None:
                raise RuntimeError(f"the {process.command} exited with {process.exited()}:\n{process.output()}")
        try:
            if httpx.get(f"{base_url}/me", timeout=2).status_code == 401:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"the API was not ready within {READY_TIMEOUT_SECONDS} seconds:\n{api.output()}")


_SERVER = pytest.StashKey[Server | BaseException]()


def start_server(config: pytest.Config, database: Database, sandbox_driver: tuple[str, str]) -> Server:
    """Start the API and the worker once per test session; later calls return the same server.

    `sandbox_driver` is the URL and the secret of the session's sandbox driver.
    """
    cached = config.stash.get(_SERVER, None)
    if isinstance(cached, BaseException):
        raise cached
    if cached is not None:
        return cached

    port = _free_port()
    # Only the variables of the harness: the server refuses unknown MZM_* ones.
    base = {name: value for name, value in os.environ.items() if not name.startswith("MZM_")}
    driver_url, driver_token = sandbox_driver
    shared = {
        "MZM_DATABASE_URL": database.app_url,
        "MZM_SECRET_KEY": secrets.token_urlsafe(32),
        "MZM_SANDBOXD_URL": driver_url,
        "MZM_SANDBOXD_TOKEN": driver_token,
    }
    try:
        api = Process(
            "api",
            base
            | shared
            | {"MZM_HTTP_HOST": "127.0.0.1", "MZM_HTTP_PORT": str(port), "MZM_TRUSTED_PROXIES": "127.0.0.1"},
            command="api",
        )
        config.add_cleanup(api.close)
        worker = Process("worker", base | shared, command="worker")
        config.add_cleanup(worker.close)
        server = Server(base_url=f"http://127.0.0.1:{port}/v1", api=api, worker=worker)
        _wait_until_ready(api, worker, server.base_url)
    except BaseException as exc:
        config.stash[_SERVER] = exc
        raise
    config.stash[_SERVER] = server
    return server
