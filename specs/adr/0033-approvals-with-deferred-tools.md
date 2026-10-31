# ADR-0033: Approvals with Pydantic AI deferred tools, ending runs with an interrupt

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0012, ADR-0030, ADR-0031, ADR-0032, ADR-0034, AGT-004, AGT-005, AGT-006, AGT-007, AGT-012

## Context

ADR-0012 requires approvals for consequential tools and, once untrusted
content is in a run, for tools that communicate externally (the lethal
trifecta). Pydantic AI provides deferred tools: tools marked
`requires_approval`, or wrapped in an `ApprovalRequiredToolset` whose
predicate decides per call, make the run end with `DeferredToolRequests`; the
answers are passed to a new run as `DeferredToolResults`. Its documentation
warns that "approval is not an authorization boundary against an untrusted
client".

The durable execution spike (2026-10-31) tested two designs: a workflow that
waits for the answer, and a run that ends and is resumed by a new run. Both
work.

## Decision

We will implement approvals with deferred tools, and **end the run when
approval is needed** (the run is "interrupted"):

1. Approval rules are **predicates on toolsets**: static rules from
   capability classes (AGT-005, AGT-006) and the trifecta rule (AGT-004),
   which needs approval for `external_communication` tools once untrusted
   content is part of the run.
2. A run that needs approval ends with `DeferredToolRequests`. The server
   stores the pending requests with the conversation (ADR-0031), marks the run
   `interrupted`, and emits an AG-UI interrupt (ADR-0032).
3. The user's answer starts a **new run** in the same conversation, carrying
   `DeferredToolResults`. The server builds them **only from its own stored
   requests**: decisions for unknown, already resolved or expired requests are
   rejected (AGT-012).
4. Pending approvals block new input in the conversation until answered or
   expired, as AG-UI requires.
5. Each pending approval has an **expiry**. When it passes without an answer,
   a scheduled job resumes the conversation with all pending calls denied
   (fail closed, AGT-007).

## Consequences

- The protocol, the framework and the durable engine all model approvals the
  same way: a run ends, a later run resumes.
- No long-lived workflow per pending approval.
- Approval prompts must show the tool, its arguments and destination, from the
  stored request, not from client input.

## Alternatives considered

- **A workflow waiting for the answer (durable receive with timeout):** works
  and has a native timeout, but keeps one suspended workflow per pending
  approval and diverges from AG-UI's and Pydantic AI's model of resumption.
