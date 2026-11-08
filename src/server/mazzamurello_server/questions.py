"""Questions the assistant asks the user, as AG-UI interrupts (AGT-015, ADR-0033, ADR-0083).

A run whose model calls `ask_user_question` ends with the calls deferred; the
conversation keeps them, serialized, until a resume run answers them. The
answers are built here, from the stored question and the user's choice, never
from what the client says the question was.
"""

from __future__ import annotations

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

from mazzamurello_server import errors

INTERRUPT_PREFIX = "int-"
# The most of the user's own words one answer carries.
CUSTOM_ANSWER_CHARS = 2000

REQUESTS: TypeAdapter[DeferredToolRequests] = TypeAdapter(DeferredToolRequests)


def asks_user(requests: DeferredToolRequests) -> bool:
    """Whether the run ended to ask the user, and for nothing else."""
    return bool(requests.calls) and not requests.approvals and all(c.tool_name == TOOL_NAME for c in requests.calls)


def interrupts(stored: Any) -> list[dict[str, Any]]:
    """The AG-UI interrupts of the stored requests: the questions, as the model asked them."""
    if stored is None:
        return []
    return [
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
        for call in REQUESTS.validate_python(stored).calls
    ]


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


def answer(stored: Any, resume: list[dict[str, Any]]) -> dict[str, Any]:
    """What the model receives for each pending question, by tool call ID; refused unless every one fits."""
    if stored is None:
        raise _invalid("No question is pending")
    calls = REQUESTS.validate_python(stored).calls
    entries = {str(entry.get("interruptId")): entry for entry in resume}
    expected = {f"{INTERRUPT_PREFIX}{call.tool_call_id}" for call in calls}
    if set(entries) != expected or len(entries) != len(resume):
        raise _invalid("Answer every pending question, and nothing else")
    results: dict[str, Any] = {}
    for call in calls:
        request = AskUserRequest.from_tool_call(call)
        response = _response(entries[f"{INTERRUPT_PREFIX}{call.tool_call_id}"])
        try:
            check_response(request, response)
            results[call.tool_call_id] = ask_user_result(request, response)
        except ValueError:
            raise _invalid("The answer does not fit its question") from None
    return results
