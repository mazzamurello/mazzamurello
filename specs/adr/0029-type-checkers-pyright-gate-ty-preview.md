# ADR-0029: pyright as the type-checking gate, ty in preview until it matures

- **Status:** Accepted
- **Date:** 2026-10-30
- **Deciders:** @tapionx
- **Related:** ADR-0008, REPO-009

## Context

ADR-0008 makes strict type checking the substitute for a compiler: it is one
of the main ways mistakes in AI-written code are caught before review. REPO-009
requires CI to fail on any type-checking finding.

Astral's ty would fit the toolchain well: it comes from the makers of uv and
ruff, is configured in the same `pyproject.toml`, and is much faster than
pyright, which matters for agents that type-check many times per task. As of
2026-10-30, however, ty is beta software (version 0.0.95, "Development
Status :: 4 - Beta", releases almost daily). Its implementation of the typing
specification is not complete yet, and its rule set does not yet map
one-to-one onto pyright's strict mode.

## Decision

We will:

1. Keep **pyright in strict mode as the required type-checking gate** in CI
   (REPO-009).
2. Run **ty in CI as a non-blocking job**, and make it available locally, so
   its behavior on our code is visible over time.
3. **Monitor ty's maturity** and revisit this decision when ty publishes a
   stable 1.0 release, or earlier if a maintainer asks.
4. **Switch to ty as the gate**, through a new ADR, when all of the following
   hold:
   - ty has a stable release (1.0 or later);
   - it runs on the whole workspace with a configuration whose strictness is
     at least that of pyright's strict mode, verified by comparing the two on
     the same code;
   - its findings on our code over the previous weeks did not include
     false positives that required suppressions pyright did not.

## Consequences

- Both checkers run in CI; the non-blocking job costs a few seconds.
- Code is annotated for the stricter of the two; occasionally a false positive
  of one checker needs a targeted suppression.
- The switch, when it happens, changes CI configuration only, not code.

## Alternatives considered

- **ty as the only checker now:** fastest feedback, but beta-level stability
  and coverage on the project's main safety net.
- **pyright only, no ty:** loses the information needed to decide the switch.
