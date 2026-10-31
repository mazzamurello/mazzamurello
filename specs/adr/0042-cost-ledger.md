# ADR-0042: A cost ledger for every model request

- **Status:** Proposed
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0017, ADR-0036, ADR-0041, MOD-004, MOD-005, MOD-006, MOD-007, UX-008

## Context

Journey J12 of the [product description](../product.md) asks to see, in real
time, what each message, each conversation and each month cost on
pay-per-token providers. Model calls happen not only for answers but also for
titles, compaction, speech and memory.

Pydantic AI reports usage per response (input, cached and output tokens) and
prices responses with genai-prices, Pydantic's catalog of model prices. Some
providers, such as OpenRouter, also report the actual cost of each request.
The harness `SpendLimits` capability adds each response's price to counters
per run, conversation, day and month, with a PostgreSQL store, and can refuse
requests when a budget is spent (MOD-004).

## Decision

We will keep **a cost ledger**: one entry per model request, written by the
model gateway (ADR-0036) after each response.

1. An entry records the user, the conversation and run when there is one, the
   purpose (`run`, `title`, `compaction`, `speech`, `memory`), the provider
   and model, the token counts (input, cached input, cache writes, output),
   the cost, the currency and the **price source**. It never contains
   content (MOD-006).
2. The price comes, in order, from: the cost reported by the provider; a price
   set by the instance admin for that provider and model; the genai-prices
   catalog. Models that are not paid per token have cost zero. An entry whose
   price is unknown is recorded with its tokens and flagged, never dropped.
3. Costs are decimal numbers in the provider's currency, never floating
   point.
4. After each model response the run emits a usage event to clients, carrying
   the run's tokens and cost so far and the context in use (MOD-007).
5. Totals per message, conversation, day and month are computed from the
   ledger. Budgets (MOD-004) use the harness `SpendLimits` counters, kept
   consistent with the ledger.
6. Ledger entries are private data of the user. A tenant admin sees totals per
   user, never per conversation. Deleting a conversation keeps its ledger
   entries, detached from it, so that spending totals stay correct.

## Consequences

- Phase 0 records the ledger from the first remote provider; display arrives
  with the web client in phase 1.
- Prices from the catalog are estimates; the price source tells the user how
  reliable each entry is.
- The genai-prices catalog is a dependency to keep up to date, reviewed with
  framework upgrades (REPO-010).

## Alternatives considered

- **Only aggregate counters (`SpendLimits` alone):** cheaper, but cannot show
  the cost of a single message.
- **Reading the provider's billing API:** authoritative, but delayed, per
  provider, and unavailable for most.
