# MOD — Models and data egress

How the assistant reaches language models, and what may leave the house.
Background: ADR-0017.

## MOD-001: Provider-agnostic model gateway

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Every model call MUST go through the model gateway, which MUST support at
least one local provider through an OpenAI-compatible API (e.g. Ollama,
llama.cpp) and at least one remote provider (e.g. OpenRouter).

## MOD-002: Provider credentials stay in the control plane

- **Status:** accepted
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

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** e2e

The system SHOULD record which provider and model produced each assistant
message and show it to the user.
