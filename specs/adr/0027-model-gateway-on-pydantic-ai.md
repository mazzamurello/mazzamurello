# ADR-0027: Build the model gateway as our own layer on Pydantic AI

- **Status:** Accepted
- **Date:** 2026-10-30
- **Deciders:** @tapionx
- **Related:** ADR-0008, ADR-0017, MOD-001, MOD-002, MOD-003, MOD-004, MOD-005

## Context

ADR-0017 requires a model gateway through which every model call passes,
applying the data egress policy, budgets and attribution. ADR-0008 named
LiteLLM as the initial candidate. Since then:

- Pydantic AI, our agent framework, already supports the providers we need
  natively: Ollama and any OpenAI-compatible server (llama.cpp, DwarfStar),
  OpenRouter, and the major remote APIs.
- What the gateway adds on top of provider access — egress policy per tenant,
  user and shared space, budgets, attribution — is domain logic, easier to
  specify and test in our own code than in an external proxy's configuration.
- LiteLLM's proxy would add a separate service with its own database and
  administration interface on the critical path of every request.
- On 2026-03-24, malicious LiteLLM releases (1.82.7 and 1.82.8) were published
  to PyPI after a maintainer credential was compromised, and harvested
  credentials from the machines that installed them. The project responded,
  but the incident illustrates the cost of every additional dependency sitting
  next to all provider credentials.

## Decision

We will implement the model gateway as **a module of the server**, built on
Pydantic AI's model and provider abstractions. It:

1. resolves which provider and model to use for a request;
2. enforces the data egress policy before any request leaves the instance
   (MOD-003);
3. enforces budgets for paid providers (MOD-004);
4. records the provider and model of every response (MOD-005);
5. holds provider credentials, which are never passed to agents' tools,
   sandboxes or clients (MOD-002).

This decision amends ADR-0008 on the model access row: LiteLLM is no longer
the planned gateway.

## Consequences

- No additional service; the gateway is tested like the rest of the server.
- New providers arrive through Pydantic AI; exotic ones may need small
  adapters of our own.
- Dependencies are pinned with hashes in `uv.lock`, as for every dependency.

## Alternatives considered

- **LiteLLM proxy:** broad provider coverage and built-in budgets, at the cost
  of an extra service, a second configuration language for our policies, and a
  large dependency on the most sensitive path.
- **Calling provider SDKs directly from the agent code:** scatters credentials
  and policy, contrary to ADR-0017.
