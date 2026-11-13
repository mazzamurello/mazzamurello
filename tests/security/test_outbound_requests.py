"""The API and the worker connect only to declared destinations (OBS-006, ADR-0072, T-32).

The harness records every connection and name lookup the two processes make
(tests/support/outbound/sitecustomize.py). The test looks only at what the
processes do while it runs, since other tests test connections to addresses
of their own: it starts another API process and restarts the worker, signs
a user in and completes runs. In the test session, every declared
destination is on the loopback address: the database, the sandbox driver and
the model the tests serve. So nothing may leave it, and only the names of
the session's own services and of the households' connections may be looked
up.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse

import pytest

from tests.support.accounts import create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, start_run, wait_for_run
from tests.support.server import Server


def _addresses(name: str) -> set[str]:
    try:
        return {str(info[4][0]) for info in socket.getaddrinfo(name, None)}
    except socket.gaierror:
        return set()


def _is_loopback(address: str) -> bool:
    try:
        return ipaddress.ip_address(address.split("%")[0]).is_loopback
    except ValueError:
        return False


@pytest.mark.spec("OBS-006")
def test_the_api_and_the_worker_connect_only_to_declared_destinations(
    database: Database, server: Server, default_model: HarnessModel
) -> None:
    account = create_account(database, create_tenant(database))
    default_model.connect(account.tenant_id)
    before = len(server.outbound())
    api, _ = server.start_twin_api()
    api.close()
    server.crash_and_restart_worker()
    token = login(server, account)
    conversation = create_conversation(server, token)
    for text in ("hello", "run:echo outbound"):
        run_id, _ = start_run(server, token, conversation["id"], text)
        assert wait_for_run(server, token, run_id)["status"] == "completed"
    entries = server.outbound()[before:]
    assert any("connect" in entry for entry in entries), "the harness recorded no connection"
    with database.superuser() as conn:
        addresses = [str(row[0]) for row in conn.execute("SELECT base_url FROM connections").fetchall()]
    declared: set[str] = {"localhost", database.host}
    declared |= {urllib.parse.urlsplit(url).hostname or "" for url in addresses}
    for url in (server.base_url, server.api_environment["SIBILLO_SANDBOXD_URL"]):
        declared.add(urllib.parse.urlsplit(url).hostname or "")
    # The addresses of declared names, such as the database's, may be outside the loopback range.
    resolved = {address for name in declared if name for address in _addresses(name)}
    connections = sorted(
        {
            entry["connect"]
            for entry in entries
            if "connect" in entry and not _is_loopback(entry["connect"]) and entry["connect"] not in resolved
        }
    )
    lookups = sorted(
        {entry["resolve"] for entry in entries if "resolve" in entry}
        - declared
        - {entry["resolve"] for entry in entries if "resolve" in entry and _is_loopback(entry["resolve"])}
    )
    assert connections == [], f"connections to undeclared destinations: {connections}"
    assert lookups == [], f"lookups of undeclared names: {lookups}"
