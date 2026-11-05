# AGT — Agent and tools

How the agent acts, and the controls around it. Background: ADR-0012, threat
model T-08 to T-10.

## AGT-001: All actions through mediated tools

- **Status:** implemented
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

- **Status:** implemented
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

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

Framework capabilities that execute commands, fetch URLs, search the web
locally or connect to MCP servers MUST NOT run in the control plane. They MUST
run in the user's sandbox or use provider-native tools (ADR-0030, ADR-0035).
There are two exceptions. Remote MCP servers over HTTP added by a tenant admin
(AGT-019): the control plane calls them as a client, through the address
rules of ADR-0064, and never starts MCP programs. Web search (AGT-020): the
worker sends queries to the instance's search service, and nothing else
(ADR-0075).

## AGT-014: Bounded tool output

- **Status:** implemented
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

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, eval

When the history of a run would exceed 80% of the context window of the
conversation's model, the system MUST compact the history sent to the model:
the conversation's model summarizes the oldest turns, and the most recent
ones stay as they are. The context window comes from the provider or, for a
connection to the household's own server, from the connection, which a
tenant admin can set. Compaction MUST NOT change the stored conversation,
which the user can still read, rewind and fork in full (ADR-0041, ADR-0073).

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

## AGT-018: Every call to a device or an MCP server is approved

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

Every invocation of a tool of a connected device (DEV-003) or of a remote MCP
server (AGT-019) MUST require the user's explicit approval, whatever its
capability classes, in addition to AGT-006. The run MUST wait for the answer.
Tools of the sandbox and Mazzamurello's own tools follow AGT-006 alone
(ADR-0063, ADR-0064).

## AGT-019: Remote MCP servers of a household

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

A tenant admin MUST be able to add remote MCP servers, reached over HTTP, to
their tenant; their tools MUST be available to every user of that tenant and
to no other tenant. Each server MUST have at most one credential, stored
encrypted and never returned by the API or sent to sandboxes or clients
(MOD-002). Only a tenant admin who is also the instance admin MAY use a
private or local address; other tenant admins MUST use public `https`
addresses, checked at connection time (ADR-0061). Results and tool
descriptions from these servers MUST be treated as untrusted content
(AGT-003) (ADR-0064).

## AGT-020: Web search

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

The agent MUST be able to search the web with a `web_search` tool, for every
model that can call tools. The tool MUST send only the query, to the
instance's search service, and return at most ten results, each with its
title, address and excerpt, as untrusted content (AGT-003) bounded like other
tool output (AGT-014). It MUST NOT fetch any address itself, and MUST NOT use
a model provider's web search (ADR-0074). When the search service fails, the
tool MUST tell the model so, and the run MUST go on. Queries MUST NOT be
logged (OBS-001) (ADR-0075).

## AGT-021: Reading web pages

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

The agent MUST be able to read a web page with a `read_page` tool, which
fetches one `http` or `https` address from the user's sandbox, under its
egress rules, and returns the page's title, final address and main text as
Markdown, as untrusted content (AGT-003) bounded like other tool output
(AGT-014). Other addresses MUST be refused. When the page cannot be read,
the tool MUST tell the model why, and the run MUST go on (ADR-0075).
