# ADR-0004: Instruct agents with AGENTS.md and enforce rules in CI

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** ADR-0003, REPO-001, REPO-002, REPO-003, REPO-005

## Context

Every new agent session starts without the project's context. Repeating the
rules by hand is not sustainable, and instructions alone are not reliable:
agents follow them most of the time, not always. The project should also not
depend on a single AI vendor's tooling.

## Decision

We will use a layered approach, from guidance to enforcement:

1. **Instructions — `AGENTS.md`** at the repository root, the tool-neutral
   convention read by many coding agents. It is short and points to the specs
   instead of repeating them. Tools that read a different file get a
   one-line pointer (e.g. `CLAUDE.md` containing `@AGENTS.md`); such files
   hold no content of their own.
2. **Procedures — documented workflows** in
   `docs/development/workflow.md`, and later reusable agent skills using
   open formats where available.
3. **Local guardrails — optional and tool-specific** (e.g. editor or agent
   hooks). They improve feedback but are never the only enforcement.
4. **CI — the authoritative gate,** identical for every agent and human:
   pull request types and allowed paths, DCO sign-off, spec format and
   cross-references, traceability, tests, types, linters and design tests.

Rules files (`AGENTS.md`, `.github/`, `tools/`, governance files) change only
through `rules/*` pull requests approved by a maintainer, so that an agent
blocked by a rule cannot "fix" the rule.

## Consequences

- Any compliant agent can work on the project; the rules do not live in a
  vendor's configuration format.
- CI must stay fast and its messages must explain how to comply.

## Alternatives considered

- **Vendor-specific instruction files only:** ties the project to one tool.
- **Instructions without enforcement:** fails silently when an agent drifts.
