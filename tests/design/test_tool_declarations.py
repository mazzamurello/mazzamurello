"""Every tool declares its capability classes and approval default; content is labeled by its provenance
(AGT-003, AGT-005, AGT-006, ADR-0090).
"""

from __future__ import annotations

from typing import Any, get_args

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextContent,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.toolsets import FunctionToolset

from sibillo_server import schemas, tool_policy, worker
from tests.support.approvals import DECLARED

CLASSES = {"reads_private_data", "ingests_untrusted", "external_communication", "irreversible", "physical"}


def _registered_tools() -> set[str]:
    """Every tool the agent can offer the model: its own, and those of its capabilities."""
    names = set(worker.agent._function_toolset.tools)  # pyright: ignore[reportPrivateUsage]
    for capability in worker.agent.root_capability.capabilities:
        toolset: Any = capability.get_toolset()
        if isinstance(toolset, FunctionToolset):
            names |= set(toolset.tools)  # pyright: ignore[reportUnknownArgumentType]
    return names


@pytest.mark.spec("AGT-005")
def test_every_registered_tool_has_a_declaration() -> None:
    registered = _registered_tools()
    assert registered == set(tool_policy.DECLARATIONS)
    # Every one is a tool the user can switch off (ADR-0087), but for the output limits' own (ADR-0090).
    assert registered - set(get_args(schemas.ToolName.__value__)) == {"read_tool_result"}


@pytest.mark.spec("AGT-005", "AGT-006")
def test_declarations_are_those_of_adr_0090() -> None:
    declared = {
        name: (set(declaration.classes), declaration.approval_default)
        for name, declaration in tool_policy.DECLARATIONS.items()
    }
    assert declared == DECLARED
    for declaration in tool_policy.DECLARATIONS.values():
        assert set(declaration.classes) <= CLASSES
        assert declaration.approval_default in {"allow", "ask"}
        # Consequential tools are always asked.
        if {"irreversible", "physical"} & set(declaration.classes):
            assert declaration.approval_default == "ask"


def _request(*parts: Any) -> ModelRequest:
    return ModelRequest(parts=list(parts))


def _call(name: str, call_id: str) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(tool_name=name, args={}, tool_call_id=call_id)])


def _result(name: str, call_id: str) -> ModelRequest:
    return _request(ToolReturnPart(tool_name=name, content="result", tool_call_id=call_id))


@pytest.mark.spec("AGT-003")
@pytest.mark.parametrize(
    ("messages", "untrusted"),
    [
        ([], False),
        ([_request(UserPromptPart("Plan my week")), ModelResponse(parts=[TextPart("Sure")])], False),
        # The results of tools that ingest untrusted content.
        ([_request(UserPromptPart("Search")), _call("web_search", "a"), _result("web_search", "a")], True),
        ([_request(UserPromptPart("Run")), _call("run_command", "a"), _result("run_command", "a")], True),
        ([_request(UserPromptPart("Read")), _call("read_file", "a"), _result("read_file", "a")], True),
        # Not those of tools that do not.
        ([_request(UserPromptPart("Plan")), _call("write_plan", "a"), _result("write_plan", "a")], False),
        ([_request(UserPromptPart("Write")), _call("write_file", "a"), _result("write_file", "a")], False),
        # The user's answers to questions are the user's own (AGT-015).
        ([_request(UserPromptPart("Ask")), _call("ask_user_question", "a"), _result("ask_user_question", "a")], False),
        # Files the user attaches come from elsewhere.
        (
            [
                _request(
                    UserPromptPart(
                        [
                            "Look at this",
                            TextContent("Files: report.pdf", metadata={"origin": worker.ATTACHMENTS_ORIGIN}),
                        ]
                    )
                )
            ],
            True,
        ),
    ],
    ids=[
        "nothing",
        "conversation",
        "search",
        "command",
        "file",
        "plan",
        "written file",
        "answer",
        "attachment",
    ],
)
def test_untrusted_content_is_recognized_by_its_provenance(messages: list[ModelMessage], untrusted: bool) -> None:
    assert tool_policy.has_untrusted_content(messages) is untrusted
