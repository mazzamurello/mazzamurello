# ADR-0036: The model gateway as a Pydantic AI capability

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0017, ADR-0027, ADR-0030, MOD-001, MOD-002, MOD-003, MOD-004, MOD-005

## Context

ADR-0027 decided to build the model gateway as our own layer on Pydantic AI.
Pydantic AI's extension point for behavior around model requests is the
capability: capabilities bundle hooks (such as before each model request),
model settings and tools. Pydantic AI also provides `FallbackModel`,
`UsageLimits` (including a cost limit per run), OpenAI-compatible providers
for self-hosted servers, and the harness provides spend limits per period with
a PostgreSQL store.

## Decision

We will implement the model gateway **as a Pydantic AI capability** attached to
every agent:

1. Model selection resolves providers configured by the instance admin
   (OpenAI-compatible providers for local servers, OpenRouter and others).
2. The data egress policy (MOD-003) is checked in the hook that runs before
   each model request, so no request reaches a model the policy forbids.
3. Per-run limits use `UsageLimits`; per-user and per-tenant budgets over time
   (MOD-004) use the harness spend limits, or our own store if they do not
   meet the requirement.
4. Fallbacks use `FallbackModel`.
5. Provider credentials stay in the gateway configuration (MOD-002).

This amends ADR-0027 on where the gateway lives; its other decisions stand.

## Consequences

- The gateway composes with other capabilities and with durable execution.
- Its behavior is tested as a capability, with Pydantic AI's test models.

## Alternatives considered

- **A module wrapping agent calls:** works, but sits outside the framework's
  hooks and composes poorly with durable execution.
