"""The API process under test, started as the test harness contract prescribes.

See specs/contracts/test-harness.md ("Server") and ADR-0050: the real
process, configured by environment variables, called over HTTP.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import httpx
import pytest

from tests.support.database import ROOT, Database, uuid7

READY_TIMEOUT_SECONDS = 30
STOP_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class Server:
    base_url: str

    def client(self, token: str | None = None, source: str | None = None) -> httpx.Client:
        """An HTTP client for the API, authenticated by `token`, from source address `source`."""
        headers = {"X-Forwarded-For": source or fresh_source()}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return httpx.Client(base_url=self.base_url, headers=headers, timeout=30)


def fresh_source() -> str:
    """A source address no other request has used, in the documentation range 2001:db8::/32."""
    return str(ipaddress.IPv6Address(int(ipaddress.IPv6Address("2001:db8::")) + uuid7().int % (1 << 96)))


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _output(log: IO[str]) -> str:
    log.flush()
    return Path(log.name).read_text(errors="replace")


def _stop(process: subprocess.Popen[str], log: IO[str]) -> None:
    process.terminate()
    try:
        process.wait(STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    log.close()


def _wait_until_ready(process: subprocess.Popen[str], log: IO[str], base_url: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"the server exited with {process.returncode}:\n{_output(log)}")
        try:
            if httpx.get(f"{base_url}/me", timeout=2).status_code == 401:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"the server was not ready within {READY_TIMEOUT_SECONDS} seconds:\n{_output(log)}")


_SERVER = pytest.StashKey[Server | BaseException]()


def start_server(config: pytest.Config, database: Database) -> Server:
    """Start the API once per test session; later calls return the same one."""
    cached = config.stash.get(_SERVER, None)
    if isinstance(cached, BaseException):
        raise cached
    if cached is not None:
        return cached

    port = _free_port()
    # Only the variables of the harness: the server refuses unknown MZM_* ones.
    environment = {name: value for name, value in os.environ.items() if not name.startswith("MZM_")}
    environment |= {
        "MZM_DATABASE_URL": database.app_url,
        "MZM_HTTP_HOST": "127.0.0.1",
        "MZM_HTTP_PORT": str(port),
        "MZM_TRUSTED_PROXIES": "127.0.0.1",
    }
    log = tempfile.NamedTemporaryFile("w+", prefix="mzm-server-", suffix=".log", delete=False)  # noqa: SIM115
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "mazzamurello_server", "api"],
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        config.add_cleanup(lambda: _stop(process, log))
        server = Server(base_url=f"http://127.0.0.1:{port}/v1")
        _wait_until_ready(process, log, server.base_url)
    except BaseException as exc:
        config.stash[_SERVER] = exc
        raise
    config.stash[_SERVER] = server
    return server
