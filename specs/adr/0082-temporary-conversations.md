# ADR-0082: Temporary conversations

- **Status:** Accepted
- **Date:** 2026-11-08
- **Deciders:** @tapionx
- **Related:** ADR-0042, ADR-0052, ADR-0073, ADR-0078, CNV-005, CNV-006, CNV-007, CNV-008, CNV-009, CNV-011, MEM-001, SBX-010, TEN-004, TEN-009

## Context

Journey J10 asks for a conversation that leaves nothing behind: a question
the user does not want in their list, their search or the assistant's
memory. Deleting a conversation already removes its runs, its durable
workflows and its workspace, and detaches its ledger entries (ADR-0042,
ADR-0078). What is missing is a conversation that is never listed and is
deleted without the user asking.

A client cannot be relied on to say when the user leaves: a tab is closed, a
phone drops its connection. The worker already runs a periodic job across
tenants, the retention of workflows, through a `SECURITY DEFINER` function
that returns only identifiers (ADR-0052).

## Decision

1. **Temporary from the start:** `POST /conversations` takes
   `temporary: true`; `conversations.temporary` is set on creation and never
   changes. A temporary conversation cannot become a normal one, so nothing
   the user said in it is kept by mistake.
2. **Out of sight:** `GET /conversations`, `GET /conversation-list` and
   `GET /search` leave temporary conversations out. Its owner still reads it
   by its ID, which is how a client shows it.
3. **Not shared with the rest:** forking it, and moving it into a folder,
   pinning or archiving it, are refused with `409 conversation.temporary`.
   Its title is not generated (CNV-006), which would cost a model call for a
   list it is not in. Memory, when it comes, neither reads nor writes for it
   (MEM-001). Its settings, tools and files work as in any conversation.
4. **Deleted when left:** clients delete it with `DELETE
   /conversations/{id}` when the user leaves it for another screen of the
   app or signs out. A reload is not leaving.
5. **Deleted a day after its last activity:** every
   `SIBILLO_TEMPORARY_SWEEP_SECONDS` (default 600) the worker calls
   `expired_temporary_conversations(hours)` with 24, a `SECURITY DEFINER`
   function that returns the identifiers, tenant and owner of temporary
   conversations whose `updated_at` is more than that many hours ago and that
   have no queued or running run. It deletes each one under its owner's
   request context, as `DELETE` does: workflows, workspace, then the rows.
   A deletion that fails is retried by the next sweep.
6. **Ledger:** its entries are detached on deletion, as for any
   conversation (ADR-0042), so the user's costs stay right.

## Consequences

- Nothing about a temporary conversation outlives it, except costs without
  content.
- A temporary conversation left open in a closed tab exists for up to a day,
  unlisted; its owner can reach it only by its URL.
- The sweep deletes with the owner's request context, so row-level security
  applies to it as to the API; the function exposes only identifiers.
- Tests set a short sweep interval and move `updated_at` back, instead of
  waiting a day.

## Alternatives considered

- **Delete on `pagehide` or `beforeunload`:** would delete on every reload,
  and does not fire when a phone kills the tab.
- **A toggle that keeps a temporary conversation:** what the user said
  thinking it would vanish would be kept; starting a normal conversation is
  one click.
- **Deleting in the API on the next request of its owner:** a user who never
  comes back keeps it forever.
- **A role that bypasses row-level security for the sweep:** forbidden
  (TEN-004); identifiers and the owner's context are enough.
