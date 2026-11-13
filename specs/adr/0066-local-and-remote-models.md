# ADR-0066: Local and remote models

- **Status:** Proposed
- **Date:** 2026-11-02
- **Deciders:** @tapionx
- **Related:** ADR-0017, ADR-0051, ADR-0057, MOD-003, MOD-010

## Context

Running capable models at home needs hardware many households cannot
afford, so many will use a remote provider such as OpenRouter for some or all
conversations. That is a choice the household can make knowingly only if
Sibillo tells them, every time, whether their words stay in the house.

## Decision

1. **Every model configuration states where its inference runs:** `local`, on
   the household's hardware, or `remote`, at a provider. The admin who
   configures it says so; the endpoint's address is only a hint, since a
   provider can sit behind a local proxy.
2. **Clients show it.** A conversation shows whether it uses a local or a
   remote model, and warns before data would leave the household.
3. **The data egress policy (MOD-003) uses the same statement,** so that
   "local models only" refuses every model configured as `remote`.

## Consequences

- Choosing a remote provider stays possible and becomes visible.
- An admin who mislabels a remote model as local defeats the policy; the
  label is theirs to get right, as the model's endpoint is.

## Alternatives considered

- **Deciding from the endpoint's address:** automatic, but wrong for proxies
  and for local servers reached through a public name.
- **No distinction:** simpler, and leaves the household unaware of where its
  data goes.
