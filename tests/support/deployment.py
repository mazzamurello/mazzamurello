"""A deployment installed as the README says, for end-to-end tests (specs/contracts/test-harness.md, "End-to-end").

The deployment runs with its own Compose project and an env file in a
temporary directory, so that nothing of the operator's own `deploy/.env` is
used or touched.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import subprocess
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

from tests.support.database import ROOT, uuid7
from tests.support.model import ModelServer, start_model_server
from tests.support.runs import parse_events
from tests.support.sandbox import free_port

COMPOSE_FILE = ROOT / "deploy" / "compose.yaml"
UP_TIMEOUT_SECONDS = 1800
# CI builds the deployment's images with its build cache; `up` then uses them (ADR-0059).
BUILD = [] if os.environ.get("TEST_DEPLOYMENT_IMAGES") == "built" else ["--build"]
SANDBOX_LABEL = "dev.sibillo.sandbox"
SANDBOX_NETWORK = "sibillo-sandboxes"


@dataclass(frozen=True)
class Deployment:
    project: str
    config_dir: Path
    base_url: str
    admin_username: str
    admin_password: str
    # The operator's own sandboxes, volumes and bridge, there before the deployment: never removed.
    others: frozenset[str] = frozenset()

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
        env={**os.environ, "SIBILLO_CONFIG_DIR": str(config_dir)},
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"docker compose {' '.join(args)} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout + result.stderr


def docker_cli(*args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["docker", *args],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    ).stdout


def sandbox_resources() -> frozenset[str]:
    """The sandbox containers, workspace volumes and sandbox bridge on this host, whoever made them."""
    containers = docker_cli("ps", "-aq", "--no-trunc", "--filter", f"label={SANDBOX_LABEL}").split()
    volumes = docker_cli("volume", "ls", "-q", "--filter", f"label={SANDBOX_LABEL}").split()
    networks = docker_cli("network", "ls", "-q", "--filter", f"name=^{SANDBOX_NETWORK}$").split()
    return frozenset([*containers, *volumes, *(SANDBOX_NETWORK for _ in networks)])


def remove_sandboxes(deployment: Deployment) -> None:
    """Sandboxes are created by the driver, not by Compose: remove the deployment's, their volumes and their bridge.

    Those of the operator's own installation on the same host stay.
    """
    containers = docker_cli("ps", "-aq", "--no-trunc", "--filter", f"label={SANDBOX_LABEL}").split()
    containers = [container for container in containers if container not in deployment.others]
    if containers:
        docker_cli("rm", "-f", *containers)
    volumes = docker_cli("volume", "ls", "-q", "--filter", f"label={SANDBOX_LABEL}").split()
    volumes = [volume for volume in volumes if volume not in deployment.others]
    if volumes:
        docker_cli("volume", "rm", "-f", *volumes)
    if SANDBOX_NETWORK not in deployment.others:
        docker_cli("network", "rm", SANDBOX_NETWORK)


def configure(deployment: Deployment, port: int) -> None:
    """Publish the API on `port`, and keep archives in the deployment's temporary directory."""
    (deployment.config_dir / "backups").mkdir(exist_ok=True)
    with deployment.env_file.open("a") as env:
        env.write(f"SIBILLO_PUBLISH=127.0.0.1:{port}\n")
        env.write(f"SIBILLO_BACKUP_DIR={deployment.config_dir / 'backups'}\n")


def env_values(deployment: Deployment) -> dict[str, str]:
    lines = deployment.env_file.read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def log_in(deployment: Deployment, username: str, password: str) -> httpx.Response:
    return httpx.post(
        f"{deployment.base_url}/auth/login",
        json={"username": username, "password": password, "device_name": "e2e"},
        timeout=60,
    )


def admin_token(deployment: Deployment) -> str:
    response = log_in(deployment, deployment.admin_username, deployment.admin_password)
    assert response.status_code == 201, response.text
    return str(response.json()["token"])


def run_text(client: httpx.Client, conversation_id: str, text: str, parent: str | None = None) -> tuple[str, str]:
    """Run `text` in the conversation; the run's ID and its answer."""
    run_id = str(uuid7())
    payload: dict[str, Any] = {
        "threadId": conversation_id,
        "runId": run_id,
        "messages": [{"id": "m1", "role": "user", "content": text}],
    }
    if parent is not None:
        payload["parentRunId"] = parent
    with client.stream("POST", f"/conversations/{conversation_id}/runs", json=payload) as response:
        assert response.status_code == 200, response.read().decode()
        events = parse_events(list(response.iter_lines()))
    assert events[-1].type == "RUN_FINISHED", events[-1]
    return run_id, "".join(str(event.data.get("delta", "")) for event in events if event.type == "TEXT_MESSAGE_CONTENT")


@contextlib.contextmanager
def installed(config_dir: Path) -> Generator[Deployment]:
    """A deployment installed in `config_dir`, removed with its volumes and images at the end."""
    project = f"sibillo-e2e-{secrets.token_hex(3)}"
    port = free_port()
    username, password = f"admin-{secrets.token_hex(3)}", secrets.token_urlsafe(18)
    deployment = Deployment(
        project, config_dir, f"http://127.0.0.1:{port}/v1", username, password, others=sandbox_resources()
    )
    try:
        # The README's steps: generate the secrets, start, create the first admin.
        deployment.compose("run", "--rm", "--no-deps", "init")
        configure(deployment, port)
        deployment.compose("up", "--detach", *BUILD, "--wait", timeout=UP_TIMEOUT_SECONDS)
        answers = f"Family\n{username}\nAdministrator\n{password}\n"
        deployment.compose("run", "--rm", "--no-TTY", "setup", stdin=answers)
        yield deployment
    finally:
        # The driver's sandboxes first, so that nothing holds the deployment's images.
        compose(project, config_dir, "stop", "sandboxd", check=False)
        remove_sandboxes(deployment)
        compose(project, config_dir, "down", "--volumes", "--rmi", "all", "--timeout", "20", check=False, timeout=600)


@contextlib.contextmanager
def reachable_model(deployment: Deployment) -> Generator[ModelServer]:
    """The model the tests serve, at the host's address on the deployment's network."""
    networks = cast(
        list[dict[str, Any]],
        json.loads(docker_cli("network", "inspect", f"{deployment.project}_internal") or "[]"),
    )
    assert networks, "the deployment's internal network is missing"
    gateway = networks[0]["IPAM"]["Config"][0]["Gateway"]
    model, http = start_model_server(host="0.0.0.0", advertised=gateway)  # noqa: S104 - reached from containers
    yield model
    http.shutdown()
