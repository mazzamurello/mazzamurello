# MOD — Models and data egress

How the assistant reaches language models, and what may leave the house.
Background: ADR-0017, ADR-0036, ADR-0042.

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
- **Phase:** 2
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

## MOD-008: Models configured by administrators

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The instance admin MUST be able to configure models for the whole instance,
and a tenant admin models for their tenant, through the public API, and mark
one of them as the default. Credentials of a model configuration MUST be
write-only in the API and stored only encrypted (MOD-002).

## MOD-007: Live usage reporting

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

During a run, the server MUST send clients, after each model response, the
context window size of the model, the tokens the context uses, and the
tokens and cost of the run so far. The API MUST provide the total cost per
message, per conversation, per day and per month for the requesting user.

Rationale: journey J12.
