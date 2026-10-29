# AGT — Agent and tools

How the agent acts, and the controls around it. Background: ADR-0012, threat
model T-08 to T-10.

## AGT-001: All actions through mediated tools

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

The agent MUST act only by invoking mediated tools executed by the control
plane. There MUST NOT be any other channel from the model to the outside
world.

## AGT-002: Per-user tool permissions

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A tenant admin MUST be able to allow or deny each tool, or tool capability
class, for each user of the tenant. A denied tool MUST NOT be offered to the
model for that user.

## AGT-003: Content provenance

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** unit

Every piece of content entering a run MUST be labeled as trusted (written by
the user or the system) or untrusted (web content, received messages,
external files, sandbox output, connector data from third parties).

## AGT-004: Breaking the lethal trifecta

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, eval

Once untrusted content is part of a run, every invocation of a tool in the
`external_communication` class during that run MUST require explicit user
approval.

## AGT-005: Capability classes

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** design

Every tool MUST declare its capability classes among `reads_private_data`,
`ingests_untrusted`, `external_communication`, `irreversible` and `physical`.
A design test MUST fail when a registered tool declares none.

## AGT-006: Approval for consequential actions

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

Tools in the `irreversible` or `physical` classes MUST require explicit user
approval for every invocation. Tools in the `external_communication` class
MUST require approval by default.

## AGT-007: Approvals fail closed

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

An approval request that is not answered within its timeout, or that cannot
be delivered, MUST be treated as denied. The approval request MUST show the
action, the data involved and its destination.

## AGT-008: Audit events visible to the user

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

Every tool invocation MUST produce an audit event (tool, time, run,
conversation, approval outcome) that the user it acted for can view.
