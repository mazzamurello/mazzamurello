# ADR-0041: Compaction as a view for the model, chosen per model

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0030, ADR-0031, ADR-0036, ADR-0037, ADR-0042, AGT-016, CNV-002, CNV-004, CNV-005, MOD-007

## Context

Long conversations and sandbox work outgrow a model's context window
(journey J7), and context windows differ widely between local and remote
models. Pydantic AI offers two families of compaction:

- **provider compaction**, in core, for providers that summarize history on
  their side;
- **local strategies**, in the harness, that work with every model: clearing
  old tool results, removing superseded file reads, sliding windows,
  summaries by a model, and `TieredCompaction`, which runs the cheap passes
  first and summarizes only when still over the target. All strategies keep
  tool calls and their results together. `ReportContextUsage` reports the
  context in use without changing history.

Harness compaction rewrites the run's message history in place. Our stored
messages are the source of truth (ADR-0031), and users rewind and fork from
any turn (ADR-0037), so the stored history must stay complete.

## Decision

We will treat compaction as **a view of the history that only the model
sees**:

1. The stored conversation is never compacted. Users read, rewind and fork the
   complete history (CNV-004, CNV-005).
2. When compaction runs, its result for the path is stored as a **compaction
   checkpoint** attached to the run at which it happened: the compacted
   messages that replace the path up to that run. The history a run receives
   is the latest checkpoint on its path, followed by the stored messages after
   it (CNV-002). Rewinding or forking to a turn before a checkpoint simply
   stops using it on that path.
3. The strategy is configured **per model** by the instance admin, with
   defaults: provider compaction for models that support it, otherwise
   `TieredCompaction` with a summary made by a configurable model. The
   trigger is a fraction of the model's context window.
4. Every compaction that calls a model is recorded in the cost ledger with
   the purpose `compaction` (ADR-0042), and the summary model is subject to
   the data egress policy (MOD-003).
5. `ReportContextUsage` feeds the live context gauge (MOD-007).

## Consequences

- Compaction never loses information for the user, only for the model.
- One more stored object per compacted path; it is private data with the same
  row-level security as messages, and is deleted with the conversation.
- Summaries can carry instructions injected earlier in the conversation; they
  keep the provenance of the content they summarize (AGT-003).

## Alternatives considered

- **Let compaction rewrite stored history:** simplest with the harness, but
  rewinding and forking would no longer see the original turns.
- **Recompute compaction on every run:** no stored checkpoints, but repeats
  the summary model call, and its cost, on every turn.
- **One strategy for all models:** simpler, but wastes the provider compaction
  that remote models offer and the large windows some local models have.
