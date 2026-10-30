# ADR-0026: Durable runs executed by workers, with persisted run events

- **Status:** Superseded by ADR-0034
- **Date:** 2026-10-30
- **Deciders:** @tapionx
- **Related:** ADR-0008, API-004, AGT-009, AGT-010

## Context

A run can take minutes: model calls, tool calls, commands in the sandbox.
Clients are often phones, whose connections drop. A run must not die with the
connection that started it, and a client that reconnects must see everything
that happened while it was away (API-004). Scheduled tasks, planned for
phase 2, also start runs without any client connected.

## Decision

We will execute runs **outside the HTTP request**:

1. When a message arrives, the API stores it, creates a **run** and enqueues
   it in the PostgreSQL-backed job queue (procrastinate, ADR-0008). It returns
   immediately with the run's identifier.
2. A **worker** process executes the run: the agent loop, model calls and tool
   calls.
3. Everything that happens during a run — text deltas, tool calls and their
   results, approval requests, completion or failure — is appended to the
   database as ordered **run events**, each with a sequence number.
4. The worker signals new events with PostgreSQL `LISTEN/NOTIFY`, carrying
   only identifiers. API processes stream events to clients as Server-Sent
   Events; a client that reconnects sends the last sequence number it received
   and the stream resumes from the next one.
5. A run belongs to one conversation and is processed by one worker at a time.
   If a worker dies, the run is marked failed or retried according to its state;
   it is never silently lost.
6. API and worker are two entrypoints of the same server package (ADR-0028).

## Consequences

- Runs survive client disconnections and API restarts.
- The same path serves interactive messages and, later, scheduled tasks.
- Run events form a complete record of what the agent did, which also serves
  the audit events of AGT-008.
- More moving parts than streaming directly from the request, all of them
  needed anyway; run events must be subject to retention and to redaction in
  logs (OBS-003, OBS-005).

## Alternatives considered

- **Run inside the HTTP request, stream directly:** simplest, but the run dies
  with the connection and cannot be resumed.
- **A separate message broker (Redis, NATS):** one more service to operate,
  where PostgreSQL already provides queueing and notifications.
