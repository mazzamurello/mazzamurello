"""The agent's tools, through runs: its workspace, questions to the user and its task list (AGT-011, AGT-014,
AGT-015, CNV-018, SBX-001, UX-009, ADR-0035, ADR-0053, ADR-0083).

The model the tests serve calls the agent's command tool when the user's
message is `run:<command>` (tests/support/model.py).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.support.accounts import Account, assert_problem, body, create_account, create_tenant, login
from tests.support.database import Database, uuid7
from tests.support.fixtures import HarnessModel
from tests.support.runs import (
    Event,
    create_conversation,
    get_run,
    messages,
    parse_events,
    run_input,
    start_run,
    text_of,
    wait_for_run,
)
from tests.support.sandbox import Driver
from tests.support.server import Server


@pytest.fixture
def account(database: Database) -> Account:
    return create_account(database, create_tenant(database))


@pytest.fixture
def token(server: Server, account: Account, default_model: HarnessModel) -> str:
    default_model.connect(account.tenant_id)
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
def test_commands_run_in_the_sandbox_of_the_conversation_they_act_in(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    secret = f"secret-{uuid7()}"
    conversation = create_conversation(server, token)
    sandboxes.sh(str(account.tenant_id), str(account.id), conversation["id"], f"echo {secret} > /workspace/mine.txt")
    command = f"run:cat /workspace/mine.txt # {uuid7()}"
    start_run(server, token, conversation["id"], command)
    (result,) = _tool_results(default_model, command)
    assert secret in result


@pytest.mark.spec("AGT-011", "SBX-001")
@pytest.mark.parametrize("whose", ["another-user", "another-conversation"])
def test_the_agent_never_reaches_another_sandbox(
    database: Database,
    server: Server,
    sandboxes: Driver,
    account: Account,
    token: str,
    default_model: HarnessModel,
    whose: str,
) -> None:
    other = create_account(database, create_tenant(database)) if whose == "another-user" else account
    secret = f"theirs-{uuid7()}"
    sandboxes.sh(str(other.tenant_id), str(other.id), str(uuid7()), f"echo {secret} > /workspace/theirs.txt")
    conversation = create_conversation(server, token)
    command = f"run:cat /workspace/theirs.txt; ls -a /workspace # {uuid7()}"
    start_run(server, token, conversation["id"], command)
    (result,) = _tool_results(default_model, command)
    assert secret not in result


@pytest.mark.spec("AGT-014")
def test_large_tool_output_reaches_the_model_bounded_and_stays_in_the_scratch_folder(
    server: Server, sandboxes: Driver, account: Account, token: str, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, token)
    size = 60_000
    # Two commands in one answer: the sandbox, and the scratch folder, end with it (ADR-0076, ADR-0078).
    command = (
        f"runs:head -c {size} /dev/zero | tr '\\0' a"
        " ||| find /scratch -type f -size +50k | wc -l; find /workspace -type f -size +50k | wc -l"
    )
    run_id, _ = start_run(server, token, conversation["id"], command)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    (last,) = default_model.endpoint.requests_with(command)[-1:]
    first, second = [str(m.get("content", "")) for m in last.body.get("messages", []) if m.get("role") == "tool"]
    assert first.count("a") < size
    # The rest is in the scratch folder, not in the workspace.
    counts = [line.strip() for line in second.splitlines() if line.strip().isdigit()]
    assert counts[:2] == ["1", "0"], second


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


@pytest.mark.spec("AGT-011")
def test_the_agent_can_delete_files_in_its_workspace(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)
    name = f"delete-{uuid7()}.txt"
    command = f"run:echo gone > {name} && rm {name} && ls {name} || echo removed-{name}"
    run_id, _ = start_run(server, token, conversation["id"], command)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    (result,) = _tool_results(default_model, command)
    # The sandbox, not a list of command names, decides what a command can do (ADR-0062).
    assert f"removed-{name}" in result, result


@pytest.mark.spec("CNV-018")
def test_a_tool_result_with_a_nul_character_is_kept(server: Server, token: str) -> None:
    conversation = create_conversation(server, token)
    # As `cat` of a binary file prints it.
    run_id, events = start_run(server, token, conversation["id"], "run:printf 'before\\000after'")
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert "before" in text_of(events)
    history = messages(server, token, conversation["id"])["items"]
    results = [str(message.get("content", "")) for message in history if message.get("role") == "tool"]
    assert any("before\ufffdafter" in result for result in results), results


@pytest.mark.spec("CNV-018")
def test_the_message_after_a_run_stopped_mid_tool_is_answered(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, token)
    payload = run_input(conversation["id"], "run:sleep 30")
    stopped = payload["runId"]
    # Stopped while the command runs: once the call is complete, its result is 30 seconds away.
    with (
        server.client(token) as client,
        client.stream("POST", f"/conversations/{conversation['id']}/runs", json=payload, timeout=60) as response,
    ):
        lines: list[str] = []
        for line in response.iter_lines():
            lines.append(line)
            if line == "" and any(event.type == "TOOL_CALL_END" for event in parse_events(lines)):
                break
    with server.client(token) as client:
        assert client.post(f"/runs/{stopped}/cancel").status_code == 200
    assert wait_for_run(server, token, stopped)["status"] == "cancelled"
    run_id, events = start_run(server, token, conversation["id"], "after the stop")
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    assert "Echo: after the stop" in text_of(events)
    # The call the stopped run left reaches the model with a result, as interrupted.
    (request,) = default_model.endpoint.requests_with("after the stop")
    assert any(message.get("role") == "tool" for message in request.body.get("messages", []))


def _ask(header: str, *labels: str, multi_select: bool = False) -> str:
    """A message on which the model asks the user one question, with `labels` as its choices."""
    question = {
        "header": header,
        "question": f"Which {header.lower()}?",
        "options": [{"label": label} for label in labels],
        "multi_select": multi_select,
    }
    return f"tool:ask_user_question {json.dumps({'questions': [question]})}"


def _interrupts(events: list[Event]) -> list[dict[str, Any]]:
    """The interrupts the run finished with; none when it finished otherwise."""
    (finished,) = [event for event in events if event.type == "RUN_FINISHED"]
    outcome: dict[str, Any] = finished.data.get("outcome") or {}
    interrupts: list[dict[str, Any]] = outcome.get("interrupts", [])
    return interrupts if outcome.get("type") == "interrupt" else []


def _answered(interrupt_id: str, header: str, **answer: Any) -> list[dict[str, Any]]:
    """A `resume` that answers one question of the interrupt."""
    return [{"interruptId": interrupt_id, "status": "resolved", "payload": {"answers": [{"header": header, **answer}]}}]


def _resume(server: Server, token: str, conversation_id: str, entries: list[dict[str, Any]]) -> Any:
    """Answer the pending interrupts: the response, streamed in full."""
    payload = {"threadId": conversation_id, "runId": str(uuid7()), "messages": [], "resume": entries}
    with server.client(token) as client:
        return client.post(f"/conversations/{conversation_id}/runs", json=payload, timeout=60)


def _conversation(server: Server, token: str, conversation_id: str) -> dict[str, Any]:
    with server.client(token) as client:
        return body(client.get(f"/conversations/{conversation_id}"))


@pytest.mark.spec("AGT-015")
def test_a_question_interrupts_the_run_until_the_user_answers(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, token)
    header = f"Colour {uuid7().hex[:6]}"
    asked = _ask(header, "Red", "Blue")
    run_id, events = start_run(server, token, conversation["id"], asked)
    (interrupt,) = _interrupts(events)
    assert interrupt["reason"] == "ask_user"
    assert interrupt["id"] == f"int-{interrupt['toolCallId']}"
    (question,) = interrupt["metadata"]["questions"]
    assert (question["header"], [o["label"] for o in question["options"]]) == (header, ["Red", "Blue"])
    assert get_run(server, token, run_id)["status"] == "interrupted"
    # The conversation keeps it, and takes nothing else until it is answered.
    assert _conversation(server, token, conversation["id"])["interrupts"] == [interrupt]
    with server.client(token) as client:
        another = client.post(
            f"/conversations/{conversation['id']}/runs", json=run_input(conversation["id"], "something else")
        )
        assert_problem(another, 409, "run.interrupt_pending")
        fork = client.post(f"/conversations/{conversation['id']}/fork", json={"run_id": run_id})
        assert_problem(fork, 409, "run.interrupt_pending")
    # Only answers that fit the stored question are taken.
    wrong_answers: list[list[dict[str, Any]]] = [
        _answered("int-unknown", header, selected=["Red"]),
        _answered(interrupt["id"], header, selected=["Green"]),
        _answered(interrupt["id"], header, selected=["Red", "Blue"]),
        _answered(interrupt["id"], header, custom_answer="x" * 2001),
        [],
    ]
    for wrong in wrong_answers:
        assert_problem(_resume(server, token, conversation["id"], wrong), 422, "approval.invalid")
    answer = _answered(interrupt["id"], header, selected=["Blue"])
    response = _resume(server, token, conversation["id"], answer)
    assert response.status_code == 200, response.text
    resumed_events = parse_events(response.text.splitlines())
    resumed = resumed_events[0].data["runId"]
    run = wait_for_run(server, token, resumed)
    assert (run["kind"], run["parent_run_id"], run["status"]) == ("resume", run_id, "completed")
    # The model gets the user's choice as the question's answer, and goes on.
    results = [
        str(message.get("content", ""))
        for request in default_model.endpoint.requests_with(asked)
        for message in request.body.get("messages", [])
        if message.get("role") == "tool"
    ]
    assert any(header in result and "Blue" in result for result in results), results
    assert "Tool said:" in text_of(resumed_events)
    assert _conversation(server, token, conversation["id"])["interrupts"] == []


@pytest.mark.spec("AGT-015")
def test_a_question_is_answered_in_the_users_words_or_declined(
    server: Server, token: str, default_model: HarnessModel
) -> None:
    conversation = create_conversation(server, token)
    # In their own words, then declined.
    for own_words, expected in (("Green, please", "Green, please"), (None, "declined")):
        header = f"Colour {uuid7().hex[:6]}"
        asked = _ask(header, "Red", "Blue")
        _, events = start_run(server, token, conversation["id"], asked)
        (interrupt,) = _interrupts(events)
        entry: dict[str, Any] = {"interruptId": interrupt["id"], "status": "cancelled"}
        if own_words is not None:
            answers = [{"header": header, "custom_answer": own_words}]
            entry = {"interruptId": interrupt["id"], "status": "resolved", "payload": {"answers": answers}}
        response = _resume(server, token, conversation["id"], [entry])
        assert response.status_code == 200, response.text
        resumed = parse_events(response.text.splitlines())[0].data["runId"]
        assert wait_for_run(server, token, resumed)["status"] == "completed"
        results = [
            str(message.get("content", ""))
            for request in default_model.endpoint.requests_with(asked)
            for message in request.body.get("messages", [])
            if message.get("role") == "tool"
        ]
        assert any(expected in result for result in results), results


@pytest.mark.spec("UX-009")
def test_the_task_list_lasts_from_run_to_run(server: Server, token: str, default_model: HarnessModel) -> None:
    conversation = create_conversation(server, token)
    # Every run with tools can ask and plan.
    first = f"plain {uuid7()}"
    run_id, _ = start_run(server, token, conversation["id"], first)
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    (request,) = default_model.endpoint.requests_with(first)
    assert {"ask_user_question", "write_plan"} <= request.tool_names()
    steps = [
        {"id": "find", "content": "Find the file", "status": "in_progress"},
        {"id": "sum", "content": "Summarize it", "status": "pending"},
    ]
    run_id, events = start_run(server, token, conversation["id"], f"tool:write_plan {json.dumps({'items': steps})}")
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    # It is streamed as it changes, and kept with the conversation.
    (announced,) = [e for e in events if e.type == "CUSTOM" and e.data.get("name") == "mzm.plan"]
    shown = [(step["id"], step["content"], step["status"]) for step in announced.data["value"]["steps"]]
    assert shown == [("find", "Find the file", "in_progress"), ("sum", "Summarize it", "pending")]
    kept = _conversation(server, token, conversation["id"])["plan"]
    assert [(step["id"], step["content"], step["status"]) for step in kept] == shown
    update = {"task_id": "find", "status": "completed"}
    run_id, _ = start_run(server, token, conversation["id"], f"tool:update_task_status {json.dumps(update)}")
    assert wait_for_run(server, token, run_id)["status"] == "completed"
    kept = _conversation(server, token, conversation["id"])["plan"]
    assert [step["status"] for step in kept] == ["completed", "pending"]
    # A fork takes it along.
    with server.client(token) as client:
        fork = body(client.post(f"/conversations/{conversation['id']}/fork", json={"run_id": run_id}))
    assert [step["status"] for step in fork["plan"]] == ["completed", "pending"]
