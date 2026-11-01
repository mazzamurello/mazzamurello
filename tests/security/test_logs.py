"""No process logs passwords, API keys or content (AUTH-001, MOD-002, OBS-003, ADR-0058).

The harness keeps the output of the API, the worker and the sandbox driver,
at their default log level. This test makes each kind of secret and content
pass through them, marked so that it can be found, and looks for the marks.
"""

from __future__ import annotations

import secrets

import pytest

from tests.support.accounts import create_account, create_tenant, login
from tests.support.database import Database
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, start_run, text_of, wait_for_run
from tests.support.sandbox import Driver
from tests.support.server import Server


@pytest.mark.spec("AUTH-001", "MOD-002", "OBS-003")
def test_logs_carry_no_passwords_keys_or_content(
    database: Database, server: Server, sandboxes: Driver, default_model: HarnessModel
) -> None:
    mark = secrets.token_hex(8)
    account = create_account(database, create_tenant(database))
    wrong_password = f"wrong-password-{mark}"
    with server.client() as client:
        refused = client.post(
            "/auth/login", json={"username": account.username, "password": wrong_password, "device_name": "logs"}
        )
    assert refused.status_code == 401
    token = login(server, account)
    api_key = f"sk-key-{mark}"
    with server.client(default_model.admin_token) as client:
        assert client.patch(f"/instance/models/{default_model.id}", json={"api_key": api_key}).status_code == 200
    try:
        message = f"message-text-{mark}"
        conversation = create_conversation(server, token)
        run_id, events = start_run(server, token, conversation["id"], message)
        assert message in text_of(events)
        # The tool's argument holds `argument-<mark>-$((6*7))`; only its output holds `-42`.
        argument, output = f"argument-{mark}", f"argument-{mark}-42"
        run_id, events = start_run(server, token, conversation["id"], f"run:echo {argument}-$((6*7))")
        assert wait_for_run(server, token, run_id)["status"] == "completed"
        assert output in text_of(events)
    finally:
        with server.client(default_model.admin_token) as client:
            client.patch(f"/instance/models/{default_model.id}", json={"api_key": None})
    logs = {"api": server.api.output(), "worker": server.worker.output(), "sandbox driver": sandboxes.process.output()}
    found = [
        f"{what} in the output of the {process}"
        for process, text in logs.items()
        for what, secret in (
            ("a password", account.password),
            ("a wrong password", wrong_password),
            ("an API key", api_key),
            ("message text", message),
            ("tool arguments", argument),
            ("tool output", output),
        )
        if secret in text
    ]
    assert found == []
