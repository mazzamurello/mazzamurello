"""Backing a deployment up, installing it again, and restoring it (OPS-006, SBX-020, ADR-0077).

A module of its own, with a deployment of its own, so that CI runs it
beside the other tests (specs/contracts/test-harness.md, "End-to-end").
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

import httpx
import pytest

from tests.support.database import uuid7
from tests.support.deployment import (
    UP_TIMEOUT_SECONDS,
    Deployment,
    admin_token,
    compose,
    configure,
    env_values,
    remove_sandboxes,
    run_text,
)
from tests.support.model import ModelServer


@dataclass(frozen=True)
class Restored:
    """What the household had before its server was lost and its backup restored (OPS-006)."""

    conversation_id: str
    last_run_id: str
    api_key: str


@pytest.fixture(scope="module")
def restored(deployment: Deployment, reachable_model: ModelServer) -> Restored:
    api_key = f"sk-{secrets.token_hex(16)}"
    headers = {"Authorization": f"Bearer {admin_token(deployment)}"}
    with httpx.Client(base_url=deployment.base_url, headers=headers, timeout=120) as client:
        connection = client.post(
            "/tenant/connections",
            json={
                "name": "With a key",
                "kind": "openai",
                "base_url": reachable_model.url,
                "api_key": api_key,
                "location": "local",
            },
        )
        assert connection.status_code == 201, connection.text
        default = {"connection_id": connection.json()["id"], "model": "test-model"}
        assert client.put("/tenant/default-model", json=default).status_code == 200
        conversation = client.post("/conversations", json={"title": "Kept across a restore"}).json()
        keep = "run:mkdir -p /workspace/notes && echo kept > /workspace/notes/a.txt"
        last, _ = run_text(client, conversation["id"], keep)

    # The README's backup command, while the instance runs.
    deployment.compose("exec", "-T", "backup", "python", "-m", "sibillo_server", "backup", timeout=600)
    archives = sorted((deployment.config_dir / "backups").glob("sibillo-*.tar.age"))
    assert archives, "no archive was written"
    key = env_values(deployment)["SIBILLO_BACKUP_KEY"]

    # The server is lost: everything goes but the archive and the backup key.
    port = int(deployment.base_url.split(":")[-1].split("/")[0])
    compose(deployment.project, deployment.config_dir, "stop", "sandboxd", check=False)
    remove_sandboxes(deployment)
    deployment.compose("down", "--volumes", "--timeout", "20", timeout=600)
    deployment.env_file.unlink()

    # A new installation, with the household's backup key, then the README's restore command.
    deployment.compose("run", "--rm", "--no-deps", "init")
    new_key = env_values(deployment)["SIBILLO_BACKUP_KEY"]
    deployment.env_file.write_text(deployment.env_file.read_text().replace(new_key, key))
    configure(deployment, port)
    deployment.compose("up", "--detach", "--wait", timeout=UP_TIMEOUT_SECONDS)
    deployment.compose("run", "--rm", "--no-TTY", "restore", f"/backups/{archives[-1].name}", timeout=600)
    deployment.compose("up", "--detach", "--wait", timeout=UP_TIMEOUT_SECONDS)
    return Restored(conversation["id"], last, api_key)


@pytest.mark.spec("OPS-006")
def test_a_restored_installation_has_the_household_and_its_conversations(
    deployment: Deployment, restored: Restored
) -> None:
    headers = {"Authorization": f"Bearer {admin_token(deployment)}"}
    with httpx.Client(base_url=deployment.base_url, headers=headers, timeout=60) as client:
        conversation = client.get(f"/conversations/{restored.conversation_id}")
    assert conversation.status_code == 200, conversation.text
    assert conversation.json()["title"] == "Kept across a restore"


@pytest.mark.spec("OPS-006", "SBX-020")
def test_a_restored_installation_has_the_workspaces_and_the_connection_keys(
    deployment: Deployment, restored: Restored, reachable_model: ModelServer
) -> None:
    headers = {"Authorization": f"Bearer {admin_token(deployment)}"}
    marker = f"run:cat /workspace/notes/a.txt # {uuid7()}"
    with httpx.Client(base_url=deployment.base_url, headers=headers, timeout=120) as client:
        _, answer = run_text(client, restored.conversation_id, marker, parent=restored.last_run_id)
    assert "kept" in answer
    (request,) = reachable_model.requests_with(marker)[:1]
    assert request.authorization == f"Bearer {restored.api_key}"
