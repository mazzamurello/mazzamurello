"""The input of a run's durable workflow, shared by the API and the worker (ADR-0034).

It carries the tenant and user of the run, from which the worker sets the
request context, and nothing secret: workflow inputs are stored without
row-level security (TEN-009).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RunWorkflowInput:
    tenant_id: str
    user_id: str
    role: str
    instance_admin: bool
    conversation_id: str
    run_id: str
    parent_run_id: str | None
    user_text: str
    # The connection and the model that answer (MOD-012).
    connection_id: str
    model: str
    # The files attached to the message, as `{path, size}` (CNV-017).
    attachments: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    # The conversation's settings, and its instructions or else its user's, as the run starts (CNV-013,
    # CNV-014, ADR-0081): null base instructions are the built-in ones.
    reasoning: str = "on"
    disabled_tools: list[str] = field(default_factory=list[str])
    base_instructions: str | None = None
    additional_instructions: str | None = None
    # A temporary conversation gets no title (CNV-011, ADR-0082).
    temporary: bool = False
    # For a run that answers questions: what the model receives, by tool call ID (AGT-015, ADR-0083).
    answers: dict[str, Any] | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, value: str) -> RunWorkflowInput:
        return cls(**json.loads(value))
