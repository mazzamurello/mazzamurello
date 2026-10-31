# ADR-0052: The worker and the first runs

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0031, ADR-0032, ADR-0034, ADR-0037, ADR-0042, ADR-0050, ADR-0051, AGT-009, AGT-010, API-004, CNV-002, CNV-003, TEN-009

## Context

ADR-0034 makes runs DBOS workflows executed by workers, with their events in
DBOS streams. Implementing the first runs needs the details it leaves open:
how the worker runs and is configured, who creates the DBOS tables, when
messages are stored, what an untitled conversation looks like, and how long
event streams are kept.

## Decision

1. **The worker** runs as `python -m mazzamurello_server worker`, connected as
   `mzm_app`, with the configuration of the
   [configuration contract](../contracts/configuration.md). API processes
   enqueue runs and read their streams with a DBOS client; only workers
   execute them.
2. **DBOS tables are created by the migration command.** After the Alembic
   revisions, the migration command runs the DBOS system migrations in the
   `dbos` schema as `mzm_owner`, granting `mzm_app` the access DBOS needs.
   Processes connected as `mzm_app` never create or alter tables.
3. **A run is one workflow**, with the run's ID, on the queue partitioned by
   conversation (ADR-0034). The workflow sets the request context from the
   tenant and user IDs of its input, marks the run `running`, runs the agent
   with the messages of the path from the first run to the parent
   (CNV-002, ADR-0037), and ends the run `completed`, `failed` with an error
   code, or `cancelled`.
4. **Messages are stored as they are produced**, after each model response
   and each tool result, so that a cancelled or failed run keeps what it
   produced (CNV-003).
5. **Events** are AG-UI events from Pydantic AI's event stream, written to the
   workflow's stream under the key `events`. The stream offset plus one is the
   sequence number, and `runs.last_event_seq` follows it. A run that fails
   ends its stream with `RUN_ERROR` carrying the error code; a cancelled run
   with `RUN_ERROR` carrying `run.cancelled`.
6. **Stopping a run** cancels its workflow. A queued run never starts; a
   running one starts no further model or tool calls (CNV-003).
7. **Untitled conversations** have an empty title. Clients show their own,
   localized placeholder; automatic titles come later.
8. **Instructions** are a short built-in text naming the assistant and its
   role, until instructions and skills arrive (ADR-0044).
9. **Retention.** When it starts, and then every hour, the worker deletes the
   workflows of runs whose `finished_at` is more than `MZM_RUN_RETENTION_DAYS`
   days ago (default 30), with their streams (TEN-009). It finds them with
   `retention_expired_runs`, a `SECURITY DEFINER` function that returns only
   run identifiers, since row-level security limits it to one user at a
   time. The run and its
   messages stay; replaying the events of such a run answers `404`. Deleting
   a conversation deletes the workflows of its runs at once.
10. **A run without a model** is refused before it starts: if neither the
    tenant nor the instance has a default model, starting a run answers
    `409` with `model.unavailable`.

## Consequences

- Deployments run at least one API process and one worker; Compose starts
  both.
- The DBOS version in the lock file and the DBOS schema in the database move
  together, through the migration command.
- Event replay is limited to the retention period; history is not.
- Clients must handle empty titles.

## Alternatives considered

- **Letting DBOS create its tables at worker start:** needs `CREATE` on the
  database for `mzm_app`, which TEN-004 rules out.
- **Storing messages only when a run ends:** simpler, but a cancelled or
  crashed run would lose everything it said.
- **The first words of the first message as title:** no model call, but the
  title would be in whatever form the message happened to be.
