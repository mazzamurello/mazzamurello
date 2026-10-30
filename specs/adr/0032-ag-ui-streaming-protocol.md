# ADR-0032: AG-UI 1.0 as the client streaming protocol, with a resume extension

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0016, ADR-0030, ADR-0031, ADR-0033, ADR-0034, API-004

## Context

The first API contract defined an event vocabulary of our own. Pydantic AI
ships adapters for two standard protocols, AG-UI and the Vercel AI UI message
stream, which turn its stream events into protocol events. Evaluated on
2026-10-31:

- **AG-UI 1.0** is a versioned specification with SDKs for TypeScript and
  Python, community SDKs for other languages including Dart, and events for
  text, reasoning, tool calls and results, run lifecycle and errors. Its
  interrupt model — a run finishes with an `interrupt` outcome and a new run
  carries the `resume` answers — matches Pydantic AI's deferred tools.
- **Vercel AI** is excellent with the Vercel AI SDK in TypeScript, but its
  resumable streams depend on its own transports, and no SDK outside
  JavaScript is documented.
- Neither supports resuming an SSE stream after a disconnection; AG-UI's
  HTTP+SSE binding explicitly does not ("a broken stream cannot be
  re-entered"), and requires consumers to ignore SSE `id:` fields.

Runs execute in workers and must survive disconnections (ADR-0034), so
resumption is essential, especially on phones.

## Decision

We will use **AG-UI 1.0 events over Server-Sent Events** as the client
protocol, with a documented extension:

1. **Starting a run** is AG-UI compatible: the client posts a
   `RunAgentInput` for a conversation (`threadId` = conversation ID) and
   receives the run's events as an SSE stream. Only the new user input and
   `resume` answers are taken from the request (ADR-0031).
2. **Every event carries a sequence number** in the SSE `id:` field, starting
   at 1 within a run. Standard AG-UI clients ignore it, as the specification
   requires.
3. **Resuming** is our extension: `GET /runs/{run_id}/events` with
   `Last-Event-ID` (or `after`) replays the events after that number, then
   follows the run until it ends. The run itself is unaffected by
   disconnections.
4. **Approvals** use AG-UI interrupts: a run waiting for approval finishes
   with an `interrupt` outcome, and the answer starts a new run with `resume`
   (ADR-0033).
5. **History** is served in AG-UI's message format, as a projection of the
   stored Pydantic AI messages (ADR-0031).
6. Events are produced with Pydantic AI's AG-UI event stream, with explicit
   `thread_id` and `run_id`, and stored durably as they are produced
   (ADR-0034).

## Consequences

- Any AG-UI client works for the normal case; resuming requires knowing our
  extension, which is documented in the API contract.
- The protocol is maintained by a community and versioned; upgrades are
  reviewed like framework upgrades.

## Alternatives considered

- **Vercel AI UI message stream:** best for a React web client, weaker for
  non-JavaScript clients and for server-driven resumption.
- **Our own event vocabulary:** full control, but no client ecosystem and a
  permanent translation layer.
