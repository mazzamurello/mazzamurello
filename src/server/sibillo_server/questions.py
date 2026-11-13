"""Questions and approval requests, as AG-UI interrupts (AGT-012, AGT-015, ADR-0033, ADR-0083, ADR-0090).

A run whose model calls `ask_user_question`, or calls a tool that needs
approval, ends with the calls deferred; the conversation keeps them,
serialized, until a resume run answers them. The answers are built here, from
the stored request and the user's choice, never from what the client says the
request was.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import TypeAdapter
from pydantic_ai import DeferredToolRequests
from pydantic_ai_harness.ask_user import (
    TOOL_NAME,
    AskUserAnswer,
    AskUserRequest,
    AskUserResponse,
    ask_user_result,
    check_response,
)

from sibillo_server import errors
from sibillo_server.tool_policy import describe

INTERRUPT_PREFIX = "int-"
APPROVAL_PREFIX = "apr-"
# The most of the user's own words one answer carries.
CUSTOM_ANSWER_CHARS = 2000

REQUESTS: TypeAdapter[DeferredToolRequests] = TypeAdapter(DeferredToolRequests)


def asks_user(requests: DeferredToolRequests) -> bool:
    """Whether the run ended only to ask the user, or for approvals: for nothing it cannot answer."""
    return all(c.tool_name == TOOL_NAME for c in requests.calls) and all(
        isinstance(requests.metadata.get(c.tool_call_id), dict) for c in requests.approvals
    )


def _rfc3339(value: datetime.datetime) -> str:
    return value.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")


def approval_request(requests: DeferredToolRequests, call: Any) -> dict[str, Any]:
    """What the user is asked to approve, from the stored call and why it needs approval (AGT-007, ADR-0090)."""
    metadata: dict[str, Any] = requests.metadata.get(call.tool_call_id) or {}
    arguments = call.args_as_dict()
    action, data, destination = describe(call.tool_name, arguments)
    return {
        "tool": call.tool_name,
        "arguments": arguments,
        "action": action,
        "data": data,
        "destination": destination,
        "reason": metadata.get("reason", "consequential"),
        "scopes": list(metadata.get("scopes") or ["once"]),
    }


def interrupts(stored: Any, expires_at: datetime.datetime | None = None) -> list[dict[str, Any]]:
    """The AG-UI interrupts of the stored requests: the questions, as the model asked them, and the approvals."""
    if stored is None:
        return []
    requests = REQUESTS.validate_python(stored)
    found: list[dict[str, Any]] = [
        {
            "id": f"{INTERRUPT_PREFIX}{call.tool_call_id}",
            "reason": "ask_user",
            "toolCallId": call.tool_call_id,
            "metadata": {
                "questions": [
                    question.model_dump(mode="json") for question in AskUserRequest.from_tool_call(call).questions
                ]
            },
        }
        for call in requests.calls
    ]
    for call in requests.approvals:
        interrupt: dict[str, Any] = {
            "id": f"{APPROVAL_PREFIX}{call.tool_call_id}",
            "reason": "approval",
            "toolCallId": call.tool_call_id,
            "metadata": {"approval": approval_request(requests, call)},
        }
        if expires_at is not None:
            interrupt["expiresAt"] = _rfc3339(expires_at)
        found.append(interrupt)
    return found


def _invalid(detail: str) -> errors.ApiError:
    return errors.ApiError(422, "approval.invalid", detail)


def _response(entry: dict[str, Any]) -> AskUserResponse:
    """The user's answer to one question call, from its `resume` entry."""
    if entry.get("status") == "cancelled":
        return AskUserResponse(cancelled=True)
    if entry.get("status") != "resolved":
        raise _invalid("An answer is resolved or cancelled")
    payload: Any = entry.get("payload")
    raw: Any = cast(dict[str, Any], payload).get("answers") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        raise _invalid("A resolved question carries its answers")
    answers: list[AskUserAnswer] = []
    for item in cast(list[Any], raw):
        if not isinstance(item, dict):
            raise _invalid("An answer is an object")
        answer = cast(dict[str, Any], item)
        header, selected, custom = answer.get("header"), answer.get("selected", []), answer.get("custom_answer")
        if not isinstance(header, str) or not isinstance(selected, list):
            raise _invalid("An answer names its question and the choices picked")
        if custom is not None and (not isinstance(custom, str) or len(custom) > CUSTOM_ANSWER_CHARS):
            raise _invalid(f"An answer in the user's words is text of at most {CUSTOM_ANSWER_CHARS} characters")
        labels = tuple(str(label) for label in cast(list[Any], selected))
        answers.append(AskUserAnswer(header=header, selected=labels, custom_answer=custom))
    return AskUserResponse(answers=tuple(answers))


@dataclass(frozen=True)
class Decision:
    """The user's answer to one approval request: approved with a scope, or denied (ADR-0090)."""

    tool_call_id: str
    tool: str
    reason: str
    approved: bool
    scope: str | None = None


@dataclass(frozen=True)
class Answers:
    """What the model receives for each pending question, and the decision on each approval request."""

    calls: dict[str, Any] = field(default_factory=dict[str, Any])
    approvals: list[Decision] = field(default_factory=list[Decision])


def _decision(requests: DeferredToolRequests, call: Any, entry: dict[str, Any]) -> Decision:
    """The user's decision on one stored approval request; refused unless its scope was offered (AGT-012)."""
    offered = approval_request(requests, call)
    reason = str(offered["reason"])
    if entry.get("status") == "cancelled":
        return Decision(call.tool_call_id, call.tool_name, reason, approved=False)
    payload: Any = entry.get("payload")
    if entry.get("status") != "resolved" or not isinstance(payload, dict):
        raise _invalid("An approval is resolved with a decision, or cancelled")
    decided = cast(dict[str, Any], payload)
    approved = decided.get("approved")
    if not isinstance(approved, bool):
        raise _invalid("An approval says whether it is approved")
    if not approved:
        return Decision(call.tool_call_id, call.tool_name, reason, approved=False)
    scope = decided.get("scope")
    if scope not in offered["scopes"]:
        raise _invalid("Approve with one of the scopes the request offers")
    return Decision(call.tool_call_id, call.tool_name, reason, approved=True, scope=str(scope))


def answer(stored: Any, resume: list[dict[str, Any]], expires_at: datetime.datetime | None = None) -> Answers:
    """The answers to every pending question and approval request; refused unless every one fits (AGT-012)."""
    if stored is None:
        raise _invalid("Nothing is pending")
    requests = REQUESTS.validate_python(stored)
    if requests.approvals and expires_at is not None and expires_at <= datetime.datetime.now(datetime.UTC):
        raise _invalid("The approval request has expired")
    entries = {str(entry.get("interruptId")): entry for entry in resume}
    expected = {f"{INTERRUPT_PREFIX}{call.tool_call_id}" for call in requests.calls} | {
        f"{APPROVAL_PREFIX}{call.tool_call_id}" for call in requests.approvals
    }
    if set(entries) != expected or len(entries) != len(resume):
        raise _invalid("Answer every pending request, and nothing else")
    results: dict[str, Any] = {}
    for call in requests.calls:
        request = AskUserRequest.from_tool_call(call)
        response = _response(entries[f"{INTERRUPT_PREFIX}{call.tool_call_id}"])
        try:
            check_response(request, response)
            results[call.tool_call_id] = ask_user_result(request, response)
        except ValueError:
            raise _invalid("The answer does not fit its question") from None
    decisions = [
        _decision(requests, call, entries[f"{APPROVAL_PREFIX}{call.tool_call_id}"]) for call in requests.approvals
    ]
    return Answers(results, decisions)


def expired(stored: Any) -> Answers:
    """The answers of an expired interrupt: every approval denied, every question declined (AGT-007)."""
    requests = REQUESTS.validate_python(stored)
    results = {
        call.tool_call_id: ask_user_result(AskUserRequest.from_tool_call(call), AskUserResponse(cancelled=True))
        for call in requests.calls
    }
    decisions = [
        Decision(call.tool_call_id, call.tool_name, str(approval_request(requests, call)["reason"]), approved=False)
        for call in requests.approvals
    ]
    return Answers(results, decisions)
