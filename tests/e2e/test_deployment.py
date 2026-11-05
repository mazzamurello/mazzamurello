"""A fresh deployment, installed as the README says (OPS-001, OPS-002, OPS-003, AUTH-007, ADR-0054).

The deployment runs with its own Compose project and an env file in a
temporary directory, so that nothing of the operator's own `deploy/.env` is
used or touched (specs/contracts/test-harness.md, "End-to-end").
"""

from __future__ import annotations

import json
import secrets
from typing import Any, cast

import httpx
import pytest

from tests.support.database import uuid7
from tests.support.deployment import Deployment, admin_token, log_in
from tests.support.model import ModelServer
from tests.support.runs import parse_events


@pytest.mark.spec("AUTH-007", "OPS-001")
def test_init_writes_fresh_secrets_once(deployment: Deployment) -> None:
    values = dict(
        line.split("=", 1) for line in deployment.env_file.read_text().splitlines() if line and not line.startswith("#")
    )
    secrets_written = (
        "MZM_POSTGRES_PASSWORD",
        "MZM_OWNER_PASSWORD",
        "MZM_APP_PASSWORD",
        "MZM_SECRET_KEY",
        "MZM_SANDBOXD_TOKEN",
        "MZM_BACKUP_KEY",
    )
    for name in secrets_written:
        assert len(values.get(name, "")) >= 32, name
    assert len({values[name] for name in secrets_written}) == len(secrets_written)
    before = deployment.env_file.read_text()
    refused = deployment.compose("run", "--rm", "--no-deps", "init", check=False)
    assert deployment.env_file.read_text() == before, refused


@pytest.mark.spec("OPS-003")
def test_only_the_api_is_published(deployment: Deployment) -> None:
    listed = [
        cast(dict[str, Any], json.loads(line))
        for line in deployment.compose("ps", "--all", "--format", "json").splitlines()
        if line.startswith("{")
    ]
    assert listed
    publishers = {item["Service"]: cast(list[dict[str, Any]], item.get("Publishers") or []) for item in listed}
    published = {service for service, ports in publishers.items() if any(port.get("PublishedPort") for port in ports)}
    assert published == {"api"}
    hosts = {port["URL"] for port in publishers["api"] if port.get("PublishedPort")}
    assert hosts <= {"127.0.0.1"}


SEARCH_PROBE = (
    "import urllib.request\n"
    "try:\n"
    "    urllib.request.urlopen('http://search:8080/healthz', timeout=5)\n"
    "    print('search: reached')\n"
    "except OSError:\n"
    "    print('search: not reached')\n"
)


@pytest.mark.spec("AGT-020")
def test_only_the_worker_reaches_the_search_service(deployment: Deployment) -> None:
    for service, reachable in (("worker", True), ("api", False)):
        result = deployment.compose("exec", "-T", service, "python", "-c", SEARCH_PROBE)
        assert ("search: reached" in result) is reachable, f"{service}: {result}"


@pytest.mark.spec("AUTH-007")
def test_the_first_administrator_is_created_once_and_no_default_works(deployment: Deployment) -> None:
    token = admin_token(deployment)
    me = httpx.get(f"{deployment.base_url}/me", headers={"Authorization": f"Bearer {token}"}, timeout=30).json()
    assert (me["username"], me["role"], me["instance_admin"]) == (deployment.admin_username, "tenant_admin", True)
    again = deployment.compose(
        "run",
        "--rm",
        "--no-TTY",
        "setup",
        stdin=f"Other\nsecond-admin\nSecond\n{secrets.token_urlsafe(18)}\n",
        check=False,
    )
    assert log_in(deployment, "second-admin", "x").status_code == 401, again
    for username, password in (
        ("admin", "admin"),
        ("admin", "password"),
        ("root", "root"),
        ("mazzamurello", "mazzamurello"),
    ):
        assert log_in(deployment, username, password).status_code == 401


@pytest.mark.spec("OPS-002", "OPS-009")
def test_health_reports_the_platform_and_a_missing_model(deployment: Deployment) -> None:
    anonymous = httpx.get(f"{deployment.base_url}/health", timeout=30)
    assert anonymous.status_code == 200, anonymous.text
    assert anonymous.json() == {"status": "degraded"}
    detailed = httpx.get(
        f"{deployment.base_url}/health", headers={"Authorization": f"Bearer {admin_token(deployment)}"}, timeout=30
    ).json()
    assert detailed["status"] == "degraded"
    checks = detailed["checks"]
    for name in ("database", "platform", "sandbox_driver", "isolation_runtime", "egress_table", "backups"):
        assert checks[name] == "ok", (name, detailed)
    assert checks["model_gateway"] == "degraded"


@pytest.mark.spec("OPS-001", "AGT-011", "MOD-008", "MOD-009")
def test_a_conversation_runs_a_command_in_the_sandbox(deployment: Deployment, reachable_model: ModelServer) -> None:
    headers = {"Authorization": f"Bearer {admin_token(deployment)}"}
    with httpx.Client(base_url=deployment.base_url, headers=headers, timeout=120) as client:
        # The first administrator is also the instance admin, so the connection may use a private address.
        connection = client.post(
            "/tenant/connections",
            json={
                "name": "Served by the tests",
                "kind": "openai",
                "base_url": reachable_model.url,
                "location": "local",
            },
        )
        assert connection.status_code == 201, connection.text
        default = {"connection_id": connection.json()["id"], "model": "test-model"}
        assert client.put("/tenant/default-model", json=default).status_code == 200
        assert client.get("/health").json()["status"] == "ok"
        conversation = client.post("/conversations", json={"title": "First conversation"}).json()
        payload = {
            "threadId": conversation["id"],
            "runId": str(uuid7()),
            "messages": [{"id": "m1", "role": "user", "content": "run:echo hello from $(uname -m)"}],
        }
        lines: list[str] = []
        with client.stream("POST", f"/conversations/{conversation['id']}/runs", json=payload) as response:
            assert response.status_code == 200, response.read().decode()
            lines = list(response.iter_lines())
    events = parse_events(lines)
    assert events[-1].type == "RUN_FINISHED", events[-1]
    text = "".join(str(event.data.get("delta", "")) for event in events if event.type == "TEXT_MESSAGE_CONTENT")
    assert "hello from" in text
