"""The input of a run's durable workflow, shared by the API and the worker (ADR-0034).

It carries the tenant and user of the run, from which the worker sets the
request context, and nothing secret: workflow inputs are stored without
row-level security (TEN-009).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass


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
    model_scope: str
    model_id: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, value: str) -> RunWorkflowInput:
        return cls(**json.loads(value))
