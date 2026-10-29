# ADR-0015: Measure agent behavior with evals

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** ADR-0003, ADR-0012, EVL-001, EVL-002, EVL-003, EVL-004, EVL-005

## Context

Unit, integration and end-to-end tests verify deterministic code. A large
part of the product is not deterministic: whether the agent picks the right
tool, respects approvals, resists prompt injection, and behaves acceptably on
a small local model as well as on a large remote one. A prompt change or a
model upgrade can degrade the assistant without breaking a single test.

## Decision

We will maintain an **eval suite**: versioned, repeatable scenarios with
synthetic data, each with explicit pass criteria, runnable against several
model configurations, including at least one small local model.

- Evals include **adversarial scenarios** (prompt injection, exfiltration
  attempts, approval bypass) whose pass criterion is that nothing leaves.
- Results are reported per scenario and per model.
- Thresholds on the eval suite **gate releases**. Pull requests run a fast
  subset when they touch prompts, tools or the agent.
- Evals never use real user data.

## Consequences

- Evals cost model calls; budgets and caching are needed in CI.
- The project gains an objective way to say which local models are
  "good enough" for which features.

## Alternatives considered

- **Manual testing of the assistant:** not repeatable, misses regressions.
