"""The sandbox driver's API (specs/contracts/sandbox-driver.yaml, ADR-0022, ADR-0053)."""

from __future__ import annotations

import time
from typing import Any

import pytest

from tests.support.database import uuid7
from tests.support.sandbox import Driver


def _user() -> tuple[str, str]:
    return str(uuid7()), str(uuid7())


@pytest.mark.spec("SBX-003", "SBX-015", "SBX-017")
def test_the_driver_reports_verified_isolation(sandboxes: Driver) -> None:
    with sandboxes.client() as client:
        response = client.get("/health")
    assert response.status_code == 200, response.text
    health = response.json()
    assert health["ready"] is True
    assert health["runtime_version"].startswith("release-")
    assert set(health["checks"]) >= {"isolation_runtime", "runtime_version", "egress_table", "canary"}
    assert all(check["ok"] is True for check in health["checks"].values())


@pytest.mark.spec("SBX-009")
@pytest.mark.parametrize("token", [None, "wrong-token-of-sufficient-length-0123456789"], ids=["missing", "wrong"])
def test_every_request_needs_the_control_plane_secret(sandboxes: Driver, token: str | None) -> None:
    tenant_id, user_id = _user()
    with sandboxes.client() as client:
        headers = {"Authorization": ""} if token is None else {"Authorization": f"Bearer {token}"}
        for method, path, body in (
            ("GET", "/health", None),
            ("POST", f"/sandboxes/{tenant_id}/{user_id}/ensure", None),
            ("POST", f"/sandboxes/{tenant_id}/{user_id}/exec", {"argv": ["true"]}),
            ("POST", f"/sandboxes/{tenant_id}/{user_id}/stop", None),
        ):
            response = client.request(method, path, json=body, headers=headers)
            assert response.status_code == 401, (path, response.text)
            assert response.json()["code"] == "driver.unauthenticated"


@pytest.mark.spec("SBX-001", "SBX-002")
def test_ensure_starts_one_sandbox_per_user(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    with sandboxes.client() as client:
        first = client.post(f"/sandboxes/{tenant_id}/{user_id}/ensure")
        again = client.post(f"/sandboxes/{tenant_id}/{user_id}/ensure")
    assert first.status_code == 200, first.text
    assert again.status_code == 200, again.text
    assert first.json()["state"] == "running"
    assert first.json()["working_dir"] == again.json()["working_dir"] == "/workspace"
    assert first.json()["started_at"] == again.json()["started_at"]


@pytest.mark.spec("AGT-011")
def test_commands_return_output_and_exit_codes(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    argv = sandboxes.exec(tenant_id, user_id, {"argv": ["sh", "-c", "echo out; echo err >&2; exit 3"]})
    assert (argv.exit_code, argv.stdout, argv.stderr, argv.timed_out, argv.truncated) == (
        3,
        "out\n",
        "err\n",
        False,
        False,
    )
    shell = sandboxes.sh(tenant_id, user_id, "pwd; echo $GREETING", env={"GREETING": "hello"})
    assert (shell.exit_code, shell.stdout) == (0, "/workspace\nhello\n")
    elsewhere = sandboxes.sh(tenant_id, user_id, "mkdir -p sub && cd sub && pwd")
    assert elsewhere.stdout == "/workspace/sub\n"
    workdir = sandboxes.exec(tenant_id, user_id, {"argv": ["pwd"], "workdir": "/workspace/sub"})
    assert workdir.stdout == "/workspace/sub\n"


@pytest.mark.spec("AGT-011")
def test_commands_get_end_of_file_on_stdin(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    result = sandboxes.sh(tenant_id, user_id, "cat; echo done", timeout_seconds=10)
    assert (result.exit_code, result.stdout, result.timed_out) == (0, "done\n", False)


@pytest.mark.spec("SBX-011")
def test_commands_are_stopped_at_their_timeout(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    started = time.monotonic()
    result = sandboxes.sh(tenant_id, user_id, "echo started; sleep 60", timeout_seconds=2)
    assert time.monotonic() - started < 20
    assert (result.timed_out, result.exit_code) == (True, None)
    assert result.stdout == "started\n"
    # Nothing of the command keeps running.
    assert "sleep 60" not in sandboxes.sh(tenant_id, user_id, "ps -eo args").stdout


@pytest.mark.spec("SBX-011")
def test_timeouts_are_capped_by_the_configuration(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    started = time.monotonic()
    # The test configuration caps commands at 20 seconds.
    result = sandboxes.sh(tenant_id, user_id, "sleep 120", timeout_seconds=3600)
    assert result.timed_out is True
    assert time.monotonic() - started < 60


@pytest.mark.spec("AGT-011", "AGT-014")
def test_output_beyond_the_limit_is_truncated(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    result = sandboxes.sh(tenant_id, user_id, "head -c 100000 /dev/zero | tr '\\0' a", max_output_bytes=1000)
    assert result.truncated is True
    assert len(result.stdout.encode()) <= 1000
    assert result.exit_code == 0


@pytest.mark.spec("SBX-010")
def test_the_workspace_survives_stopping_the_sandbox(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    sandboxes.sh(tenant_id, user_id, "echo kept > notes.txt")
    with sandboxes.client() as client:
        assert client.post(f"/sandboxes/{tenant_id}/{user_id}/stop").status_code == 204
        # Stopping a stopped sandbox is fine too.
        assert client.post(f"/sandboxes/{tenant_id}/{user_id}/stop").status_code == 204
    assert sandboxes.sh(tenant_id, user_id, "cat notes.txt").stdout == "kept\n"


@pytest.mark.spec("AGT-011")
@pytest.mark.parametrize(
    "request_body",
    [
        {},
        {"argv": ["true"], "shell_command": "true"},
        {"argv": []},
        {"shell_command": ""},
        {"argv": ["true"], "privileged": True},
        {"argv": ["true"], "timeout_seconds": 0},
    ],
    ids=["nothing", "both", "empty-argv", "empty-shell", "unknown-field", "zero-timeout"],
)
def test_invalid_exec_requests_are_rejected(sandboxes: Driver, request_body: dict[str, Any]) -> None:
    tenant_id, user_id = _user()
    with sandboxes.client() as client:
        response = client.post(f"/sandboxes/{tenant_id}/{user_id}/exec", json=request_body)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "driver.validation_failed"


@pytest.mark.spec("SBX-001")
@pytest.mark.parametrize("path", ["not-a-uuid/" + str(uuid7()), str(uuid7()) + "/../x"], ids=["tenant", "user"])
def test_sandboxes_are_addressed_only_by_identifiers(sandboxes: Driver, path: str) -> None:
    with sandboxes.client() as client:
        response = client.post(f"/sandboxes/{path}/ensure")
    assert response.status_code in {404, 422}, response.text
