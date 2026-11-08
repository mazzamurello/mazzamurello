"""The API and worker processes under test, started as the test harness contract prescribes.

See specs/contracts/test-harness.md ("Server") and ADR-0050, ADR-0052: the real
processes, configured by environment variables, the API called over HTTP.
"""

from __future__ import annotations

import ipaddress
import json
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
from typing import Any

import httpx
import pytest

from tests.support.contract import response_hook
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
    # The API's environment, for tests that start another API process like it.
    api_environment: Mapping[str, str] = field(repr=False, default_factory=dict[str, str])
    # Where the API and the worker record their outbound connections (OBS-006).
    outbound_log: Path | None = None

    def outbound(self) -> list[dict[str, Any]]:
        """Every connection and name lookup the API and the worker made so far."""
        if self.outbound_log is None or not self.outbound_log.exists():
            return []
        return [json.loads(line) for line in self.outbound_log.read_text().splitlines() if line]

    def client(self, token: str | None = None, source: str | None = None) -> httpx.Client:
        """An HTTP client for the API, authenticated by `token`, from source address `source`."""
        headers = {"X-Forwarded-For": source or fresh_source()}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return httpx.Client(
            base_url=self.base_url, headers=headers, timeout=30, event_hooks={"response": [response_hook]}
        )

    def start_twin_api(self, **overrides: str) -> tuple[Process, str]:
        """Another API process on the same database, driver and secret key, with `overrides`.

        Returns the process, already serving, and its origin; the caller closes it.
        """
        port = _free_port()
        api = Process("api-twin", {**self.api_environment, "MZM_HTTP_PORT": str(port), **overrides}, command="api")
        origin = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        while True:
            try:
                if httpx.get(f"{origin}/v1/me", timeout=2).status_code == 401:
                    return api, origin
            except httpx.TransportError:
                pass
            if api.exited() is not None or time.monotonic() > deadline:
                output = api.output()
                api.close()
                raise RuntimeError(f"the twin API did not start:\n{output}")
            time.sleep(0.2)

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


def start_server(config: pytest.Config, database: Database, sandbox_driver: tuple[str, str], search_url: str) -> Server:
    """Start the API and the worker once per test session; later calls return the same server.

    `sandbox_driver` is the URL and the secret of the session's sandbox driver,
    `search_url` the address of the search service the tests serve.
    """
    cached = config.stash.get(_SERVER, None)
    if isinstance(cached, BaseException):
        raise cached
    if cached is not None:
        return cached

    port = _free_port()
    # Only the variables of the harness: the server refuses unknown MZM_* ones.
    base = {name: value for name, value in os.environ.items() if not name.startswith("MZM_")}
    # Record outbound connections (tests/support/outbound/sitecustomize.py).
    outbound_log = Path(tempfile.mkstemp(prefix="mzm-outbound-", suffix=".jsonl")[1])
    config.add_cleanup(lambda: outbound_log.unlink(missing_ok=True))
    hook = str(ROOT / "tests" / "support" / "outbound")
    base |= {
        "PYTHONPATH": os.pathsep.join(filter(None, [hook, base.get("PYTHONPATH")])),
        "TEST_OUTBOUND_LOG": str(outbound_log),
    }
    driver_url, driver_token = sandbox_driver
    shared = {
        "MZM_DATABASE_URL": database.app_url,
        "MZM_SECRET_KEY": secrets.token_urlsafe(32),
        "MZM_SANDBOXD_URL": driver_url,
        "MZM_SANDBOXD_TOKEN": driver_token,
    }
    try:
        api_environment = (
            base
            | shared
            | {"MZM_HTTP_HOST": "127.0.0.1", "MZM_HTTP_PORT": str(port), "MZM_TRUSTED_PROXIES": "127.0.0.1"}
        )
        api = Process("api", api_environment, command="api")
        config.add_cleanup(api.close)
        # Temporary conversations are swept every second, so that their tests need not wait (ADR-0082).
        worker_environment = {"MZM_SEARCH_URL": search_url, "MZM_TEMPORARY_SWEEP_SECONDS": "1"}
        worker = Process("worker", base | shared | worker_environment, command="worker")
        config.add_cleanup(worker.close)
        server = Server(
            base_url=f"http://127.0.0.1:{port}/v1",
            api=api,
            worker=worker,
            api_environment=api_environment,
            outbound_log=outbound_log,
        )
        _wait_until_ready(api, worker, server.base_url)
    except BaseException as exc:
        config.stash[_SERVER] = exc
        raise
    config.stash[_SERVER] = server
    return server
