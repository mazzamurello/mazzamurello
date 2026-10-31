# AGT — Agent and tools

How the agent acts, and the controls around it. Background: ADR-0012, threat
model T-08 to T-10.

## AGT-001: All actions through mediated tools

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

The agent MUST act only by invoking mediated tools executed by the control
plane. There MUST NOT be any other way for the model to act on the outside
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
conversation, approval outcome) that the user it acted for can view. Tools
with external effects MUST record an idempotency key for each call, so that a
call that may have run twice after a crash (ADR-0034) is visible as such.

## AGT-009: Durable runs

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

A run MUST execute independently of the client connection that started it,
and every event of the run MUST be persisted in order, so that a client can
disconnect and later receive everything that happened (ADR-0034).

## AGT-010: Runs are never silently lost

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

If the process executing a run stops before the run completes, the run MUST
be either resumed, retried or marked as failed with an event visible to the
user.

## AGT-011: Command execution tool

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The agent MUST have mediated workspace tools that run commands and read,
write and edit files in the sandbox of the user it acts for, returning
command output and exit codes (ADR-0035). The tools MUST NOT be able to target
any other user's sandbox.

## AGT-012: Approvals verified against stored requests

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security

Approval decisions MUST be applied only to approval requests the server
stored for that conversation and that are still pending. Decisions referring
to unknown, already resolved or expired requests MUST be rejected, and the
tool, arguments and destination shown to the user MUST come from the stored
request (ADR-0033).

## AGT-013: No host-side execution through framework capabilities

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

Framework capabilities that execute commands, fetch URLs, search the web
locally or connect to MCP servers MUST NOT run in the control plane. They MUST
run in the user's sandbox or use provider-native tools (ADR-0030, ADR-0035).

## AGT-014: Bounded tool output

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

A tool result larger than a configured limit MUST NOT be sent to the model in
full. The model MUST receive a bounded excerpt and a way to read the rest,
which is kept in the user's workspace (ADR-0043).

Rationale: command output and web pages can fill the context window in one
call.

## AGT-015: Questions to the user

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** integration

The agent SHOULD be able to ask the user structured questions with choices
during a run. A question MUST end the run with an interrupt, like an approval,
and the answer MUST start a new run (ADR-0033, ADR-0043). Answers are user
input, not tool output.

Rationale: journey J7.

## AGT-016: Automatic compaction

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, eval

When a conversation approaches the context window of the model in use, the
system MUST compact the history sent to the model, using the strategy
configured for that model: compaction by the provider when the model supports
it, otherwise local strategies that drop or summarize the oldest content
first. Compaction MUST NOT change the stored conversation, which the user can
still read, rewind and fork in full (ADR-0041).

Rationale: journeys J7 and J12.

## AGT-017: Skills

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

A user MUST be able to create, edit, import, enable and delete skills in the
open Agent Skills format: a folder with a `SKILL.md` file and optional
bundled files. Skills MUST be private to their owner. Enabled skills MUST be
available in all the user's conversations, with only their names and
descriptions in the context until the model loads one. Imported skills MUST
be treated as untrusted content (AGT-003), and their scripts MUST run only in
the user's sandbox (ADR-0044).

Rationale: journey J13.
