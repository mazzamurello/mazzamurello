# MOD — Models and data egress

How the assistant reaches language models, and what may leave the house.
Background: ADR-0017, ADR-0036, ADR-0042, ADR-0057, ADR-0066, ADR-0069.

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

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

The model gateway MUST enforce a data egress policy configurable per tenant,
per user and per shared space, including at least a "local models only"
setting. A request that violates the policy MUST be refused before any data
leaves the instance.

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

- **Status:** accepted
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

A new conversation MUST start with the tenant's default model. When a tenant
without a default model gets a working connection, the default model MUST
become one of its models: for OpenRouter, its most used free model that can
call tools; for another server, the first model it lists. A user MUST
be able to choose, for a conversation, any model offered by the connections
of their tenant; the choice applies from the conversation's next run. When
the conversation's model is no longer offered, a run MUST fail instead of
using another model (ADR-0069).

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
