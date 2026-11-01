"""The agent's workspace tools, through runs (AGT-011, AGT-014, SBX-001, ADR-0035, ADR-0053).

The model the tests serve calls the agent's command tool when the user's
message is `run:<command>` (tests/support/model.py).
"""

from __future__ import annotations

import pytest

from tests.support.accounts import Account, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel
from tests.support.runs import create_conversation, start_run, text_of, wait_for_run
from tests.support.sandbox import Driver
from tests.support.server import Server


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    return login(server, account)


def _tool_results(model: HarnessModel, text: str) -> list[str]:
    """What the model received as results of the command tool, for the run of `text`."""
    return [
        str(message.get("content", ""))
        for request in model.endpoint.requests_with(text)
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]


@pytest.mark.spec("AGT-011")
def test_the_agent_runs_commands_in_the_sandbox(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)
    marker = f"marker-{uuid7()}"
    run_id, events = start_run(server, token, conversation["id"], f"run:echo {marker}; exit 3")
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    types = [event.type for event in events]
    assert {"TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT"} <= set(types)
    (result,) = _tool_results(default_model, f"run:echo {marker}; exit 3")
    # The output and the exit code reach the model.
    assert marker in result
    assert "3" in result
    assert marker in text_of(events)


@pytest.mark.spec("AGT-011", "SBX-001")
def test_commands_run_in_the_sandbox_of_the_user_they_act_for(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    secret = f"secret-{uuid7()}"
    sandboxes.sh(str(account.tenant_id), str(account.id), f"echo {secret} > mine.txt")
    conversation = create_conversation(server, token)
    start_run(server, token, conversation["id"], "run:cat mine.txt")
    (result,) = _tool_results(default_model, "run:cat mine.txt")
    assert secret in result


@pytest.mark.spec("AGT-011", "SBX-001")
def test_the_agent_never_reaches_another_users_sandbox(
    database: Database, server: Server, sandboxes: Driver, token: str, default_model: HarnessModel
) -> None:
    other = create_account(database, create_tenant(database))
    secret = f"theirs-{uuid7()}"
    sandboxes.sh(str(other.tenant_id), str(other.id), f"echo {secret} > theirs.txt")
    conversation = create_conversation(server, token)
    command = "run:cat theirs.txt; ls -a /workspace"
    start_run(server, token, conversation["id"], command)
    (result,) = _tool_results(default_model, command)
    assert secret not in result


@pytest.mark.spec("AGT-014")
def test_large_tool_output_reaches_the_model_bounded_and_stays_in_the_workspace(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, token)
    size = 60_000
    command = f"run:head -c {size} /dev/zero | tr '\\0' a"
    run_id, _ = start_run(server, token, conversation["id"], command)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    (result,) = _tool_results(default_model, command)
    assert result.count("a") < size
    kept = sandboxes.sh(
        str(account.tenant_id), str(account.id), "find /workspace -type f -size +50k -exec wc -c {} + | tail -1"
    )
    assert kept.stdout.strip(), "the full output is not in the workspace"


@pytest.mark.spec("AGT-010", "MOD-001")
@pytest.mark.parametrize("script", ["status:429", "drop:3"], ids=["rate-limited", "dropped-stream"])
def test_model_failures_end_the_run_visibly(server: Server, token: str, script: str) -> None:
    conversation = create_conversation(server, token)
    run_id, events = start_run(server, token, conversation["id"], script)
    run = wait_for_run(server, token, run_id)
    assert run["status"] in {"completed", "failed"}
    assert events[-1].type in {"RUN_FINISHED", "RUN_ERROR"}
    if run["status"] == "failed":
        assert run["error_code"] in {"model.request_failed", "model.unavailable"}
        assert events[-1].data.get("code") == run["error_code"]
