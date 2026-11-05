"""A persistent workspace in an ephemeral sandbox (SBX-010, SBX-018, SBX-019, SBX-020, AGT-022, ADR-0076, ADR-0077).

The driver's tests use its API directly; the agent's, runs with the model the
tests serve (tests/support/model.py).
"""

from __future__ import annotations

import io
import tarfile
from typing import Any

import pytest

from tests.support.accounts import Account, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, start_run, wait_for_run
from tests.support.sandbox import WORKSPACE_QUOTA_BYTES, Driver
from tests.support.server import Server


def _user() -> tuple[str, str]:
    return str(uuid7()), str(uuid7())


@pytest.mark.spec("SBX-018")
def test_commands_start_in_the_scratch_folder(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    with sandboxes.client() as client:
        response = client.post(f"/sandboxes/{tenant_id}/{user_id}/ensure")
    assert response.status_code == 200, response.text
    assert response.json()["working_dir"] == "/scratch"
    assert sandboxes.sh(tenant_id, user_id, "pwd").stdout == "/scratch\n"


@pytest.mark.spec("SBX-010", "SBX-018")
def test_a_stopped_sandbox_comes_back_new_with_only_its_workspace(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    before = sandboxes.sh(
        tenant_id,
        user_id,
        "echo kept > /workspace/kept.txt; echo scratch > /scratch/scratch.txt;"
        " echo planted > /usr/local/bin/planted; (setsid sleep 1234 >/dev/null 2>&1 &)",
    )
    assert before.exit_code == 0, before
    sandboxes.stop(tenant_id, user_id)
    after = sandboxes.sh(
        tenant_id,
        user_id,
        "cat /workspace/kept.txt; ls /scratch/scratch.txt /usr/local/bin/planted 2>&1 | wc -l;"
        # The pattern does not match the shell running it.
        " ls /scratch; pgrep -f '[s]leep 1234' || echo no-process",
    )
    lines = after.stdout.splitlines()
    assert lines[0] == "kept"
    # A new container: nothing planted outside the workspace, no process left running.
    assert not any(line.endswith(("scratch.txt", "planted")) for line in lines[2:]), after.stdout
    assert lines[-1] == "no-process"


@pytest.mark.spec("SBX-019")
def test_every_command_reports_the_workspace_size_and_quota(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    result = sandboxes.sh(tenant_id, user_id, "head -c 1048576 /dev/zero > /workspace/one-mib")
    assert result.workspace_quota_bytes == WORKSPACE_QUOTA_BYTES
    assert result.workspace_bytes is not None
    assert result.workspace_bytes >= 1048576
    # The scratch folder is not the workspace.
    scratch = sandboxes.sh(tenant_id, user_id, "head -c 3145728 /dev/zero > /scratch/three-mib")
    assert scratch.workspace_bytes is not None
    assert scratch.workspace_bytes < 2 * 1048576


def _export(sandboxes: Driver, tenant_id: str, user_id: str) -> bytes:
    with sandboxes.client() as client:
        response = client.get(f"/sandboxes/{tenant_id}/{user_id}/workspace")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/x-tar")
    return response.content


def _import(sandboxes: Driver, tenant_id: str, user_id: str, archive: bytes) -> Any:
    with sandboxes.client() as client:
        return client.put(
            f"/sandboxes/{tenant_id}/{user_id}/workspace",
            content=archive,
            headers={"Content-Type": "application/x-tar"},
        )


@pytest.mark.spec("SBX-020")
def test_a_workspace_is_exported_and_imported(sandboxes: Driver) -> None:
    tenant_id, user_id = _user()
    sandboxes.sh(
        tenant_id,
        user_id,
        "mkdir -p /workspace/budget && echo 'month,total' > /workspace/budget/2026.csv"
        " && ln -s 2026.csv /workspace/budget/latest.csv && chmod 600 /workspace/budget/2026.csv",
    )
    archive = _export(sandboxes, tenant_id, user_id)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        names = {member.name.removeprefix("./") for member in tar.getmembers()}
    assert {"budget/2026.csv", "budget/latest.csv"} <= names
    other_tenant, other_user = _user()
    sandboxes.sh(other_tenant, other_user, "echo replaced > /workspace/old.txt")
    response = _import(sandboxes, other_tenant, other_user, archive)
    assert response.status_code == 204, response.text
    restored = sandboxes.sh(
        other_tenant,
        other_user,
        "cat /workspace/budget/latest.csv; stat -c %a /workspace/budget/2026.csv; ls /workspace/old.txt 2>&1 | wc -l",
    )
    lines = restored.stdout.splitlines()
    assert lines[0] == "month,total"
    assert lines[1] == "600"
    assert "No such file" not in lines[0]
    assert sandboxes.sh(other_tenant, other_user, "test -e /workspace/old.txt || echo gone").stdout == "gone\n"


def _tar(*members: tuple[tarfile.TarInfo, bytes | None]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for info, data in members:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return buffer.getvalue()


def _file(name: str, data: bytes = b"x") -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    return info, data


def _special(name: str, kind: bytes, target: str = "") -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = target
    return info, None


@pytest.mark.spec("SBX-020")
@pytest.mark.parametrize(
    "entry",
    [
        _file("../escaped"),
        _file("/escaped"),
        _file("folder/../../escaped"),
        _special("passwd", tarfile.SYMTYPE, "/etc/passwd"),
        _special("up", tarfile.SYMTYPE, "../../etc"),
        _special("hard", tarfile.LNKTYPE, "/etc/passwd"),
        _special("device", tarfile.CHRTYPE),
        _special("pipe", tarfile.FIFOTYPE),
    ],
    ids=["parent", "absolute", "nested-parent", "link-out", "relative-link-out", "hard-link", "device", "fifo"],
)
def test_an_archive_that_leaves_the_workspace_is_refused(
    sandboxes: Driver, entry: tuple[tarfile.TarInfo, bytes | None]
) -> None:
    tenant_id, user_id = _user()
    sandboxes.sh(tenant_id, user_id, "echo before > /workspace/before.txt")
    response = _import(sandboxes, tenant_id, user_id, _tar(_file("fine.txt"), entry))
    assert response.status_code == 422, response.text
    listed = sandboxes.sh(tenant_id, user_id, "ls -A /workspace; ls /escaped /tmp/escaped 2>/dev/null | wc -l")
    # The workspace is left empty, and nothing was written outside it.
    assert listed.stdout.splitlines() == ["0"], listed.stdout


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
    return login(server, account)


def _tool_result(model: HarnessModel, text: str) -> str:
    (content,) = [
        str(message.get("content", ""))
        for request in model.endpoint.requests_with(text)[-1:]
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]
    return content


@pytest.mark.spec("SBX-019")
@pytest.mark.parametrize(
    ("size", "words"), [(7_000_000, "quota"), (9_000_000, "exceeds")], ids=["near-quota", "over-quota"]
)
def test_the_agent_is_told_when_the_workspace_nears_its_quota(
    server: Server, token: str, default_model: HarnessModel, size: int, words: str
) -> None:
    conversation = create_conversation(server, token)
    text = f"run:head -c {size} /dev/zero > /workspace/big-{size}"
    run_id, _ = start_run(server, token, conversation["id"], text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    result = _tool_result(default_model, text).lower()
    assert "workspace" in result
    assert words in result


@pytest.mark.spec("SBX-019")
def test_a_small_workspace_says_nothing_about_its_quota(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, token)
    text = "run:echo small > /workspace/small.txt"
    run_id, _ = start_run(server, token, conversation["id"], text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert "quota" not in _tool_result(default_model, text).lower()


@pytest.mark.spec("AGT-022")
def test_the_agent_is_told_what_the_workspace_keeps(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)
    text = f"instructions {uuid7()}"
    run_id, _ = start_run(server, token, conversation["id"], text)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    (request,) = default_model.endpoint.requests_with(text)[:1]
    messages = request.body.get("messages", [])
    system = " ".join(str(message.get("content", "")) for message in messages if message.get("role") == "system")
    for phrase in ("/scratch", "/workspace", "README.md"):
        assert phrase in system, f"the instructions do not mention {phrase}"
