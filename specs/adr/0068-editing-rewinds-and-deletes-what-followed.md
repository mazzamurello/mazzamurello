# ADR-0068: Editing rewinds and deletes what followed

- **Status:** Accepted
- **Date:** 2026-11-03
- **Deciders:** @tapionx
- **Related:** ADR-0031, ADR-0034, ADR-0037, ADR-0041, ADR-0042, CNV-001, CNV-002, CNV-004, CNV-005, CNV-016, UX-010, T-24

## Context

ADR-0037 keeps every continuation of a conversation as a version: editing a
message or asking for a new answer adds a run beside the old one, and clients
offer arrows to switch between them (CNV-001). The web client implemented it.
Trying it, the maintainer found the versions confusing: after asking for a
new answer, two answers exist and arrows appear, and it is not clear which
one the assistant will continue from. Asking for a new answer was not wanted
at all.

What users need is simpler: go back to an earlier point and continue from
there, and, when both ways matter, keep a copy. Rewinding (CNV-004) and
forking (CNV-005) already describe exactly that.

## Decision

1. **A conversation has one path.** Its runs still form the chain of ADR-0037,
   each run continuing its parent, but the chain never branches: there are no
   versions, and no new answer to the same message. ADR-0037's points 2 and 6
   no longer apply; its other points stand.
2. **Rewinding deletes what followed.** Rewinding to a turn makes its run the
   active run and deletes the runs after it, with their messages and run
   events; rewinding to before the first turn deletes every run. The durable
   workflows of the deleted runs are deleted with them (ADR-0034). Workspace
   files are not changed. Entries of the cost ledger are kept, detached from
   the deleted runs, as when a conversation is deleted (ADR-0042); memory
   items stay, since the user sees and manages them.
3. **Editing a message is rewinding, then sending.** The client rewinds to the
   turn before the message and starts a run with the edited text. It asks
   first, says how many messages will be deleted and that files stay
   (UX-010).
4. **The API rewinds explicitly.** `POST /conversations/{id}/rewind` names the
   run that becomes the last, or none. It replaces setting `active_run_id`,
   since deleting is not a field update. A run input's `parentRunId`, if
   given, must be the active run, so a standard AG-UI client that sends it
   keeps working and a client with a stale view gets a conflict instead of a
   fork in the chain.
5. **Forking keeps both ways.** To try another way without losing the current
   one, the user forks the conversation at a turn (CNV-005) and continues in
   the fork.
6. **No conversion of existing versions.** Sibillo has not been
   released, so the schema is rewritten rather than migrated (ADR-0071).

## Consequences

- Clients show one history and one rule: what you see is what the assistant
  continues from.
- An answer the user rewinds past is gone; the confirmation says so, and a
  fork beforehand keeps it.
- Content the user rewound past can no longer reach the model or memory
  through a later switch of version (T-24).
- History pages no longer describe versions, and the API contract changes in
  a way older clients notice; there are no clients other than the web app
  yet.

## Alternatives considered

- **Keep versions, drop only the new answer:** editing would still create
  arrows and two histories, which is the confusion the maintainer reported.
- **Rewind without deleting, keeping hidden runs:** data that no client can
  show, kept only to occupy storage and to be leaked.
- **Edit in place, rewriting the message:** the answers that followed would
  no longer match the history, and the model would see a past that did not
  happen.
