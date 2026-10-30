# ADR-0024: Phase 0 delivers the API only; the web client starts in phase 1

- **Status:** Accepted
- **Date:** 2026-10-30
- **Deciders:** @tapionx
- **Related:** ADR-0016, API-001, API-003, API-004, I18N-001

## Context

Phase 0 is a walking skeleton: it must prove that authentication,
conversations, the agent, the sandbox with its egress restrictions and
streaming work together, securely. ADR-0016 plans an installable web app as
the first client. Building it in phase 0 would roughly double the work without
proving anything more about the architecture.

## Decision

We will deliver **no user interface in phase 0**. The public API is the
product of phase 0; it is exercised by end-to-end tests and can be used by
hand with HTTP tools.

The web client (installable PWA) starts in phase 1. Externalized UI strings
(I18N-001) move to phase 1 with it. The API returns stable, machine-readable
error codes, which clients translate.

## Consequences

- Phase 0 stays small and focused on the security-critical core.
- The maintainer starts daily use in phase 1, not phase 0.
- The API is designed for clients from the start, without shortcuts for a
  bundled UI (API-001).

## Alternatives considered

- **Minimal web UI in phase 0:** earlier hands-on use, at the cost of a UI
  framework decision and UI work before the core is proven.
