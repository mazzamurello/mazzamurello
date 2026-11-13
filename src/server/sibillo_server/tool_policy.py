"""What each tool may do, and when a call needs the user's approval (AGT-002 to AGT-006, ADR-0012, ADR-0090).

Every tool declares its capability classes and its approval default. A
tenant admin's tool permissions change the default, or take the tool away.
A call needs approval for its classes, its permission or its default, or,
once the conversation has untrusted content, because it communicates
externally; allowances the user gave in the conversation, or for the turn,
cover some of these.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart, UserPromptPart

type CapabilityClass = Literal[
    "reads_private_data", "ingests_untrusted", "external_communication", "irreversible", "physical"
]
type Setting = Literal["allow", "ask", "deny"]
type ApprovalReason = Literal["untrusted_content", "tool_default", "permission", "consequential", "device"]
type Scope = Literal["once", "turn", "conversation"]

CLASSES: tuple[CapabilityClass, ...] = (
    "reads_private_data",
    "ingests_untrusted",
    "external_communication",
    "irreversible",
    "physical",
)
SETTINGS: tuple[Setting, ...] = ("allow", "ask", "deny")
STRICTNESS: dict[Setting, int] = {"allow": 0, "ask": 1, "deny": 2}
# The classes whose every call is approved, one by one (AGT-006).
CONSEQUENTIAL: frozenset[CapabilityClass] = frozenset({"irreversible", "physical"})
# The classes whose calls have effects outside Sibillo, and record an idempotency key (AGT-008).
EXTERNAL_EFFECTS: frozenset[CapabilityClass] = frozenset({"external_communication", "irreversible", "physical"})
# The tools that one approval covers together under the trifecta rule (AGT-004, ADR-0090).
WEB_AND_COMMANDS = frozenset({"web_search", "read_page", "run_command", "start_command"})
# Labels the part of a user's message that lists its attachments (CNV-017).
ATTACHMENTS_ORIGIN = "sibillo.attachments"
# What the model is told of a call the user did not approve.
DENIED = "The user denied this call, so it did not run. Do not try it again unless the user asks."
EXPIRED = "Nobody approved this call within a day, so it was denied and did not run."


@dataclass(frozen=True)
class Declaration:
    """A tool's capability classes and its approval default (AGT-005)."""

    classes: frozenset[CapabilityClass]
    approval_default: Literal["allow", "ask"] = "allow"


def _declare(*classes: CapabilityClass) -> Declaration:
    return Declaration(frozenset(classes))


_COMMAND = _declare("reads_private_data", "ingests_untrusted", "external_communication")
_READS = _declare("reads_private_data", "ingests_untrusted")
_WRITES = _declare("reads_private_data")
_OWN = _declare()

# Every tool of the assistant, in the order of the API contract's `ToolName` (ADR-0090). Web and command
# tools are allowed by default: the trifecta rule guards them where it matters.
DECLARATIONS: Mapping[str, Declaration] = {
    "web_search": _declare("ingests_untrusted", "external_communication"),
    "read_page": _declare("ingests_untrusted", "external_communication"),
    "run_command": _COMMAND,
    "start_command": _COMMAND,
    "check_command": _READS,
    "stop_command": _WRITES,
    "read_file": _READS,
    "write_file": _WRITES,
    "edit_file": _WRITES,
    "create_directory": _WRITES,
    "list_directory": _READS,
    "find_files": _READS,
    "search_files": _READS,
    "file_info": _READS,
    "offer_download": _WRITES,
    "ask_user_question": _OWN,
    "write_plan": _OWN,
    "read_plan": _OWN,
    "add_task": _OWN,
    "update_task_status": _OWN,
    "update_task_statuses": _OWN,
    "remove_task": _OWN,
    # The output limits' own tool, which reads back a large result set aside (AGT-014): no switch (ADR-0087).
    "read_tool_result": _READS,
}


def ingests_untrusted(tool: str) -> bool:
    declaration = DECLARATIONS.get(tool)
    # A tool without a declaration is treated as the most cautious one would be.
    return declaration is None or "ingests_untrusted" in declaration.classes


def has_external_effects(tool: str) -> bool:
    declaration = DECLARATIONS.get(tool)
    return declaration is None or bool(EXTERNAL_EFFECTS & declaration.classes)


def has_untrusted_content(messages: Sequence[ModelMessage]) -> bool:
    """Whether the messages hold untrusted content: results of tools that ingest it, or attachments (AGT-003)."""
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, ToolReturnPart) and ingests_untrusted(part.tool_name):
                return True
            if isinstance(part, UserPromptPart) and not isinstance(part.content, str):
                for item in part.content:
                    metadata: Any = getattr(item, "metadata", None)
                    if isinstance(metadata, dict) and cast(dict[str, Any], metadata).get("origin") == (
                        ATTACHMENTS_ORIGIN
                    ):
                        return True
    return False


@dataclass(frozen=True)
class Permissions:
    """A user's tool permissions: settings by tool and by capability class (AGT-002)."""

    tools: Mapping[str, Setting] = field(default_factory=dict[str, Setting])
    classes: Mapping[str, Setting] = field(default_factory=dict[str, Setting])

    def to_json(self) -> dict[str, dict[str, str]]:
        return {"tools": dict(self.tools), "classes": dict(self.classes)}

    @classmethod
    def from_json(cls, value: Any) -> Permissions:
        data = cast(dict[str, dict[str, Setting]], value or {})
        return cls(tools=dict(data.get("tools") or {}), classes=dict(data.get("classes") or {}))


@dataclass(frozen=True)
class Effective:
    """What applies to a tool for a user, and where it comes from: a permission's subject, or the default."""

    setting: Setting
    subject: str | None = None


def effective(tool: str, permissions: Permissions) -> Effective:
    """A tool's setting wins over its classes'; among its classes the strictest wins (AGT-002)."""
    if tool in permissions.tools:
        return Effective(permissions.tools[tool], tool)
    declaration = DECLARATIONS[tool]
    found: list[tuple[Setting, str]] = [
        (permissions.classes[name], name)
        for name in CLASSES
        if name in declaration.classes and name in permissions.classes
    ]
    if found:
        setting, subject = max(found, key=lambda item: STRICTNESS[item[0]])
        return Effective(setting, subject)
    return Effective(declaration.approval_default)


def denied(permissions: Permissions) -> frozenset[str]:
    """The tools a user's permissions take away."""
    return frozenset(name for name in DECLARATIONS if effective(name, permissions).setting == "deny")


@dataclass(frozen=True)
class Allowances:
    """What the user allowed: the web and commands for the turn or the conversation, and tools in it (AGT-006)."""

    turn_web_and_commands: bool = False
    web_and_commands: bool = False
    tools: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Request:
    """Why a call needs approval, and which scopes the user may approve it with (ADR-0090)."""

    reason: ApprovalReason
    scopes: tuple[Scope, ...]


@dataclass(frozen=True)
class Decision:
    """A call runs (`allowed` when an allowance let it), or needs approval (`request`)."""

    request: Request | None = None
    allowed: Scope | None = None


def decide(tool: str, permissions: Permissions, untrusted: bool, allowances: Allowances) -> Decision:
    """Whether a call of `tool`, in a run with or without untrusted content, needs approval."""
    declaration = DECLARATIONS.get(tool)
    if declaration is None:
        return Decision(Request("consequential", ("once",)))
    if CONSEQUENTIAL & declaration.classes:
        return Decision(Request("consequential", ("once",)))
    allowed: Scope | None = None
    setting = effective(tool, permissions)
    if setting.setting == "ask":
        if tool not in allowances.tools:
            reason: ApprovalReason = "tool_default" if setting.subject is None else "permission"
            return Decision(Request(reason, ("once", "conversation")))
        allowed = "conversation"
    if untrusted and "external_communication" in declaration.classes:
        if tool in WEB_AND_COMMANDS:
            if allowances.turn_web_and_commands:
                return Decision(allowed="turn")
            if allowances.web_and_commands:
                return Decision(allowed="conversation")
            return Decision(Request("untrusted_content", ("once", "turn", "conversation")))
        return Decision(Request("untrusted_content", ("once",)))
    return Decision(allowed=allowed)


def describe(tool: str, arguments: Mapping[str, Any]) -> tuple[str, str, str]:
    """What a call does, the data it sends, and where it goes, for the user to approve (AGT-007)."""
    if tool == "web_search":
        return (
            "Search the web",
            str(arguments.get("query", "")),
            "The household's search service, which asks public search engines",
        )
    if tool == "read_page":
        address = str(arguments.get("url", ""))
        host = urlsplit(address).hostname or address
        return "Read a web page", address, f"{host}, from the conversation's sandbox"
    if tool in ("run_command", "start_command"):
        command = str(arguments.get("command", ""))
        purpose = str(arguments.get("description", "") or arguments.get("purpose", ""))
        action = "Run a command in the sandbox" if tool == "run_command" else "Start a command in the sandbox"
        return (f"{action}: {purpose}" if purpose else action), command, "The internet, from the conversation's sandbox"
    rendered = ", ".join(f"{key}: {value}" for key, value in arguments.items())
    return f"Use {tool}", rendered, "Wherever the tool sends it"
