# ADR-0017: A model gateway with local and remote providers and a data egress policy

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** ADR-0008, MOD-001, MOD-002, MOD-003, MOD-004, MOD-005

## Context

Households will use different mixes of models: fully local (Ollama,
llama.cpp, DwarfStar and other OpenAI-compatible servers), fully remote (e.g.
OpenRouter), or both — a local model for sensitive data and a remote one for
heavy tasks. Whatever is sent to a remote model leaves the house.

## Decision

We will route every model call through a **model gateway** that:

1. supports local and remote providers through OpenAI-compatible and native
   APIs, with fallbacks;
2. holds provider credentials, which never reach sandboxes or clients;
3. enforces a **data egress policy** per tenant, user and shared space —
   at minimum a "local models only" setting — before any request leaves;
4. enforces per-user budgets for paid providers;
5. records which model produced each response, so users can see it.

## Consequences

- One place to audit what leaves the house.
- The gateway is on the critical path and must be reliable and fast.

## Alternatives considered

- **Direct provider SDKs in the agent code:** scatters credentials and policy.
