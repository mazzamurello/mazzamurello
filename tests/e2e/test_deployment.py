"""A fresh deployment, installed as the README says (OPS-001, OPS-002, OPS-003, AUTH-007, ADR-0054).

The deployment runs with its own Compose project and an env file in a
temporary directory, so that nothing of the operator's own `deploy/.env` is
used or touched (specs/contracts/test-harness.md, "End-to-end").
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from tests.support.database import ROOT, uuid7
from tests.support.model import ModelServer, start_model_server
from tests.support.runs import parse_events
from tests.support.sandbox import free_port

COMPOSE_FILE = ROOT / "deploy" / "compose.yaml"
UP_TIMEOUT_SECONDS = 1800
SANDBOX_LABEL = "dev.mazzamurello.sandbox"


@dataclass(frozen=True)
class Deployment:
    project: str
    config_dir: Path
    base_url: str
    admin_username: str
    admin_password: str

    @property
    def env_file(self) -> Path:
        return self.config_dir / ".env"

    def compose(self, *args: str, stdin: str | None = None, timeout: float = 600, check: bool = True) -> str:
        return compose(self.project, self.config_dir, *args, stdin=stdin, timeout=timeout, check=check)


def compose(
    project: str, config_dir: Path, *args: str, stdin: str | None = None, timeout: float = 600, check: bool = True
) -> str:
    env_file = config_dir / ".env"
    command = ["docker", "compose", "--file", str(COMPOSE_FILE), "--project-name", project]
    if env_file.exists():
        command += ["--env-file", str(env_file)]
    result = subprocess.run(  # noqa: S603 - Docker Compose with arguments from the test
        [*command, *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env={**os.environ, "MZM_CONFIG_DIR": str(config_dir)},
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"docker compose {' '.join(args)} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout + result.stderr


def _docker(*args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["docker", *args],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    ).stdout


def _remove_sandboxes() -> None:
    """Sandboxes are created by the driver, not by Compose: remove them, their volumes and their bridge."""
    containers = _docker("ps", "-aq", "--filter", f"label={SANDBOX_LABEL}").split()
    if containers:
        _docker("rm", "-f", *containers)
    volumes = _docker("volume", "ls", "-q", "--filter", f"label={SANDBOX_LABEL}").split()
    if volumes:
        _docker("volume", "rm", "-f", *volumes)
    _docker("network", "rm", "mazzamurello-sandboxes")


@pytest.fixture(scope="module")
def deployment(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Deployment]:
    config_dir = tmp_path_factory.mktemp("deployment")
    project = f"mzm-e2e-{secrets.token_hex(3)}"
    port = free_port()
    username, password = f"admin-{secrets.token_hex(3)}", secrets.token_urlsafe(18)
    deployment = Deployment(project, config_dir, f"http://127.0.0.1:{port}/v1", username, password)
    try:
        # The README's steps: generate the secrets, start, create the first admin.
        deployment.compose("run", "--rm", "--no-deps", "init")
        with deployment.env_file.open("a") as env:
            env.write(f"MZM_PUBLISH=127.0.0.1:{port}\n")
        deployment.compose("up", "--detach", "--build", "--wait", timeout=UP_TIMEOUT_SECONDS)
        answers = f"Family\n{username}\nAdministrator\n{password}\n"
        deployment.compose("run", "--rm", "--no-TTY", "setup", stdin=answers)
        yield deployment
    finally:
        # The driver's sandboxes first, so that nothing holds the deployment's images.
        compose(project, config_dir, "stop", "sandboxd", check=False)
        _remove_sandboxes()
        compose(project, config_dir, "down", "--volumes", "--rmi", "all", "--timeout", "20", check=False, timeout=600)


@pytest.fixture(scope="module")
def reachable_model(deployment: Deployment) -> Iterator[ModelServer]:
    """The model the tests serve, at the host's address on the deployment's network."""
    networks = cast(
        list[dict[str, Any]],
        json.loads(_docker("network", "inspect", f"{deployment.project}_internal") or "[]"),
    )
    assert networks, "the deployment's internal network is missing"
    gateway = networks[0]["IPAM"]["Config"][0]["Gateway"]
    model, http = start_model_server(host="0.0.0.0", advertised=gateway)  # noqa: S104 - reached from containers
    yield model
    http.shutdown()


def _login(deployment: Deployment, username: str, password: str) -> httpx.Response:
    return httpx.post(
        f"{deployment.base_url}/auth/login",
        json={"username": username, "password": password, "device_name": "e2e"},
        timeout=60,
    )


def _token(deployment: Deployment) -> str:
    response = _login(deployment, deployment.admin_username, deployment.admin_password)
    assert response.status_code == 201, response.text
    return str(response.json()["token"])


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


@pytest.mark.spec("AUTH-007")
def test_the_first_administrator_is_created_once_and_no_default_works(deployment: Deployment) -> None:
    token = _token(deployment)
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
    assert _login(deployment, "second-admin", "x").status_code == 401, again
    for username, password in (
        ("admin", "admin"),
        ("admin", "password"),
        ("root", "root"),
        ("mazzamurello", "mazzamurello"),
    ):
        assert _login(deployment, username, password).status_code == 401


@pytest.mark.spec("OPS-002", "OPS-009")
def test_health_reports_the_platform_and_a_missing_model(deployment: Deployment) -> None:
    anonymous = httpx.get(f"{deployment.base_url}/health", timeout=30)
    assert anonymous.status_code == 200, anonymous.text
    assert anonymous.json() == {"status": "degraded"}
    detailed = httpx.get(
        f"{deployment.base_url}/health", headers={"Authorization": f"Bearer {_token(deployment)}"}, timeout=30
    ).json()
    assert detailed["status"] == "degraded"
    checks = detailed["checks"]
    for name in ("database", "platform", "sandbox_driver", "isolation_runtime", "egress_table"):
        assert checks[name] == "ok", (name, detailed)
    assert checks["model_gateway"] == "degraded"


@pytest.mark.spec("OPS-001", "AGT-011", "MOD-008")
def test_a_conversation_runs_a_command_in_the_sandbox(deployment: Deployment, reachable_model: ModelServer) -> None:
    headers = {"Authorization": f"Bearer {_token(deployment)}"}
    with httpx.Client(base_url=deployment.base_url, headers=headers, timeout=120) as client:
        model = client.post(
            "/instance/models",
            json={
                "name": "Served by the tests",
                "base_url": reachable_model.url,
                "model": "test-model",
                "paid": False,
                "is_default": True,
            },
        )
        assert model.status_code == 201, model.text
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
