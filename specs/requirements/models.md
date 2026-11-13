# MOD — Models and data egress

How the assistant reaches language models, and what may leave the house.
Background: ADR-0017, ADR-0036, ADR-0042, ADR-0057, ADR-0066, ADR-0069, ADR-0091.

## MOD-001: Provider-agnostic model gateway

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Every model call MUST go through the model gateway, which MUST support at
least one local provider through an OpenAI-compatible API (e.g. Ollama,
llama.cpp) and at least one remote provider (e.g. OpenRouter).

## MOD-002: Provider credentials stay in the control plane

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security

Model provider credentials MUST be held only by the model gateway. They MUST
NOT be exposed to sandboxes, clients or logs.

## MOD-003: Data egress policy

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

The model gateway MUST enforce a data egress policy, which allows any model
(`any`) or only models whose inference runs locally (`local_only`, MOD-010).
A tenant admin MUST be able to set the policy of the household and of each
user, and each user MUST be able to choose `local_only` for themself; the
policy that applies to a user MUST be the strictest of the three, `any` when
none is set. A tenant admin MUST NOT be able to read or change a user's own
choice.

Every model request the gateway makes for a user, for any purpose (MOD-006),
MUST be checked against the policy that applies to them just before it is
sent, so that a change applies from the next request, also during a run. A
request the policy refuses, or one whose policy cannot be read, MUST be
refused before any data leaves the instance, with the code
`model.egress_refused`: a run fails with it, and the server MUST NOT use
another model instead (MOD-012). The policy of a shared space is MOD-016
(ADR-0017, ADR-0091).

## MOD-004: Budgets for paid providers

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 3
- **Verification:** integration

The model gateway SHOULD enforce spending limits per user and per tenant for
paid providers, checked before each request.

## MOD-005: Model attribution

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** e2e

The system SHOULD record which provider and model produced each assistant
message and show it to the user.

## MOD-006: Cost ledger

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Every model request the gateway makes MUST add an entry to the cost ledger of
the user it was made for, with the provider, the model, the purpose (a run,
a title, a compaction, speech), the conversation and run when there is one,
the input, cached and output tokens, and the cost. Requests to providers that
are not paid per token MUST be recorded with their tokens and a cost of zero.
Ledger entries MUST NOT contain message content (ADR-0042).

Rationale: journey J12.

## MOD-008: Connections managed by household admins

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A tenant admin MUST be able to manage the connections of their tenant through
the public API, and choose the tenant's default model among the models they
offer. The instance MUST NOT have models of its own. Credentials of a
connection MUST be write-only in the API and stored only encrypted (MOD-002,
ADR-0069).

## MOD-009: Connections reach only public addresses

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security

A request of the model gateway, or a connection test (MOD-013), MUST connect
only to public internet addresses, over `https`, checked when the connection
is made and not only when the address is saved, and MUST NOT follow
redirects, unless the connection's address was set by a user who is the
instance admin. A tenant admin can choose the address, and the request leaves
from the control plane, so anything else would let them reach the
household's network (ADR-0061, ADR-0069).

## MOD-010: Where inference runs

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

Every connection MUST state whether its inference runs locally, on hardware
of the household, or remotely, at a provider. Clients MUST show which kind a
conversation uses, and warn when its data would leave the household; the data
egress policy (MOD-003) relies on the same statement (ADR-0066, ADR-0069).

## MOD-007: Live usage reporting

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

During a run, the server MUST send clients, after each model response, the
context window size of the model, the tokens the context uses, and the
tokens and cost of the run so far. The API MUST provide the cost of each
message and conversation, and the requesting user's spend over the last 24
hours and the last 30 days (ADR-0073).

Rationale: journey J12.

## MOD-011: A connection offers all its models

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A connection MUST offer every model its provider lists that answers with
text, without models being configured one by one, and say for each whether
it can call tools when the provider tells. OpenRouter's models MUST be
ordered by their use in the past week, most used first (ADR-0069).

## MOD-012: The model of a conversation

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A new conversation MUST start with its user's default model, or the tenant's
default model when the user has none or theirs is no longer offered
(CNV-013). When a tenant without a default model gets a working connection,
the default model MUST become one of its models: for OpenRouter, its most
used free model that can call tools; for another server, the first model it
lists. A user MUST be able to choose, for a conversation, any model offered by the connections
of their tenant; the choice applies from the conversation's next run. When
the conversation's model is no longer offered, a run MUST fail instead of
using another model. For a user, a model their data egress policy refuses
MUST count as not offered when a new conversation chooses its model, and the
conversation MUST start without a model when both defaults are refused
(ADR-0069, ADR-0091).

## MOD-013: Testing a connection

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

A tenant admin MUST be able to test a connection, saved or not, and the
server MUST test a connection before saving a new address or new
credentials, refusing to save it when the test fails. The result MUST give
each step of the test with its outcome and duration, and for a failure a
reason from a documented list: the name was not found, the connection was
refused, the server did not answer in time, its certificate is not trusted,
the address is not allowed, the server answered with an HTTP error, the
credentials were rejected, or the answer is not a model list. Technical
details MUST NOT contain the credentials (ADR-0069).

## MOD-014: Models without tools

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, e2e

A run with a model known not to call tools MUST run without tools, answering
from the conversation alone, and clients MUST say so when the model is
chosen and while the conversation uses it. When a model's server refuses
tools that it was given, the run MUST fail with that reason instead of
continuing without them (ADR-0069).

## MOD-015: Requests a model refuses

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, e2e

When a model or its provider refuses to answer a request, for example
because a content filter flagged it, the run MUST fail with the code
`model.refused` and the reason the provider gave, if any, and clients MUST
show both to the user in the conversation, also after it is reloaded
(UX-014). The conversation MUST stay usable: the user can rephrase the
message or choose another model.

Rationale: a refusal is the model's decision, not a fault of the system,
and the user can only act on it if they see it.

## MOD-016: Data egress policy of a shared space

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A tenant admin MUST be able to set the data egress policy of a shared space
(TEN-007), and a model request carrying data of a shared space MUST follow
the strictest of the space's policy and the policy that applies to the user
(MOD-003, ADR-0091).
