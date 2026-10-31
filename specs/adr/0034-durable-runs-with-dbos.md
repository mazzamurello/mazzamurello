# ADR-0034: Durable runs with DBOS on PostgreSQL

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0008, ADR-0026, ADR-0030, ADR-0032, ADR-0033, AGT-009, AGT-010, API-004, TEN-009

## Context

ADR-0026 decided that runs execute in workers, that their events are
persisted in order and streamed with resumption, and that runs are never
silently lost. It proposed implementing this ourselves with a job queue
(procrastinate), a `run_events` table and `LISTEN/NOTIFY`.

Pydantic AI integrates with several durable execution engines. **DBOS** is an
MIT-licensed library that needs nothing but PostgreSQL, with a first-party
Pydantic AI capability (`DBOSDurability`): model requests and MCP calls become
checkpointed steps. A spike on 2026-10-31 (DBOS 3.4.0, Pydantic AI 2.63.0,
PostgreSQL 17, scripted model) showed:

| Scenario | Result |
|---|---|
| Durable event stream with offsets; reading again from an offset | First event after 0.25 s; the replay matched exactly |
| Approval answer delivered to a running workflow | Worked |
| Approval timeout | Denied automatically (fail closed) |
| Partitioned queue, concurrency 1 per conversation | A second run in the same conversation started 0.22 s after the first ended; other conversations ran in parallel |
| Worker killed with `SIGKILL` during a tool | A new process recovered and completed the run, without duplicated events |
| `delete_workflow` | Removed status, step outputs and stream rows |

It also showed constraints:

- DBOS stores workflow inputs, step outputs (by default pickled, including
  model responses) and streams in its own `dbos` schema, **without row-level
  security**. RLS cannot be added there, since DBOS does not set our tenant
  context.
- Function tools that are not DBOS steps are re-executed after a crash.

## Decision

We will use **DBOS** as the durable execution engine for runs, keeping the
guarantees of ADR-0026 and replacing its mechanism:

1. A run is a DBOS workflow whose ID is the run ID; the agent carries the
   `DBOSDurability` capability. The workflow input carries the tenant and user
   IDs, from which the worker sets the database context like the API does.
2. Runs are enqueued on a queue partitioned by conversation, with concurrency
   1 per partition (one run at a time per conversation).
3. Run events are written to a **DBOS stream** of the workflow, as AG-UI
   events (ADR-0032); the stream offset plus one is the event's sequence
   number. API processes read the stream from an offset to serve and resume
   SSE streams. This replaces the `run_events` table and `LISTEN/NOTIFY`.
4. Mediated tools that have side effects run as DBOS steps. A sandbox command
   interrupted by a crash may run again; this is documented to users of the
   workspace tools.
5. **Isolation of DBOS data (TEN-009):** application code reaches DBOS data
   only through run IDs read from the row-level-secured `runs` table; deleting
   a conversation deletes its workflows; finished workflows are deleted after
   the retention period.
6. The application version is set explicitly and changed deliberately, since
   in-flight workflows recover only on a compatible version.
7. DBOS replaces procrastinate for background work, amending ADR-0008.

Default (pickle) serialization is accepted for now, because the database is
trusted (ADR-0011); a JSON serializer is a possible later hardening.

## Consequences

- Durability, ordering, resumption, recovery and per-conversation
  serialization come from a maintained library instead of our code.
- One more schema in the database, holding user content outside RLS; this is
  a documented exception with its own requirement and threat (T-19).
- Workflows must be deterministic; I/O belongs in steps.

## Alternatives considered

- **Our own queue, event table and notifications (ADR-0026's mechanism):**
  keeps all data under RLS, but re-implements what DBOS provides.
- **Temporal:** requires a separate server.
- **Prefect:** no durable sleep, and a server for scheduling.
- **Postgres-based engines in the harness (pgtask, Absurd):** younger, 0.x.
