# ADR-0014: Privacy-preserving observability

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** OBS-001, OBS-002, OBS-003, OBS-004, OBS-005

## Context

Detailed traces of agent runs (prompts, tool arguments, outputs) are
invaluable for debugging. They also contain the most private data in the
system. Collecting them by default, or sending them to an external service,
contradicts the project's core promise.

## Decision

We will:

1. Send **nothing** to external services by default: no telemetry, no
   analytics, no crash reporting, no remote tracing.
2. Collect **metrics without content** (counts, durations, error rates)
   locally.
3. **Redact content by default** in logs and traces: message text, tool
   arguments and outputs, memory items.
4. Offer a **per-user debug mode**, enabled by the user for themselves,
   stored only locally, visibly indicated, and expiring automatically.
5. Bound log and trace **retention**, configurable by the instance admin.

Instrumentation uses OpenTelemetry so that operators can wire their own,
self-hosted backends.

## Consequences

- Debugging production issues requires the user's cooperation (debug mode).
- The project will not know how many installations exist; GitHub statistics
  and image pulls are the only signals, and that is acceptable.

## Alternatives considered

- **Full tracing by default:** convenient, contrary to the privacy principle.
- **Opt-out telemetry:** erodes trust in a privacy-focused project.
