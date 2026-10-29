# ADR-0003: Spec-driven development with AI implementation and review

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** ADR-0001, ADR-0004, ADR-0015, REPO-001, REPO-004

## Context

The code of Mazzamurello is written and reviewed by AI agents. This makes
code cheap to produce and to regenerate, but raises three risks:

- natural-language specs are ambiguous, and agents resolve ambiguity
  silently;
- when the same system writes specs, tests, code and review, errors are
  correlated: the loop converges, but on the wrong thing;
- the easiest way for an agent to make CI pass is to weaken a test.

## Decision

We will treat the artifacts of the project with different levels of
authority:

1. **Specifications are the source of truth** — requirements with IDs, ADRs,
   contracts, glossary, threat model. They are approved by humans.
2. **Tests are the executable form of the specs.** They reference the
   requirement IDs they verify and are written from the specs, before the
   implementation, by an agent that does not see the implementation.
3. **Code is ephemeral.** It may be rewritten or regenerated at any time,
   provided it satisfies the tests.
4. **Contracts are not ephemeral:** database schema and migrations, public
   API, on-disk formats and security invariants survive any rewrite and
   change only through spec changes.

The workflow for a feature is: `spec/*` → `test/*` → `impl/*` pull requests
(REPO-001). Implementation pull requests cannot modify tests. AI review runs
in a loop with automatic fixes, with a bounded number of iterations, after
which a human decides. Reviews use separate roles (correctness, security,
simplicity) and, where possible, different models.

Test quality is measured, not assumed: mutation testing on critical modules,
property-based testing where inputs are large, and architecture ("design")
tests that enforce structural rules. Agent behavior is measured by evals
(ADR-0015). Security invariants are attacked by a dedicated red-team role.

The human role is to approve specifications, critical tests and rule
changes — not to review every line of code.

## Consequences

- Specifications must be precise; vague requirements are rejected in review.
- Code quality still matters — for debugging and for the agents themselves —
  but it is enforced by machines (types, linters, design tests).
- More process than a typical hobby project, deliberately.
- Details live in [docs/development/workflow.md](../../docs/development/workflow.md).

## Alternatives considered

- **Code as the source of truth with human line-by-line review:** does not
  scale to AI-generated volume and is not where human judgment adds most.
- **Unconstrained "vibe coding":** fast at first, then drifts away from any
  coherent design and cannot be trusted with security-critical isolation.
