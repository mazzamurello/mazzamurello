# ADR-0037: Conversation history as a tree of runs

- **Status:** Proposed
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0031, ADR-0032, ADR-0033, ADR-0034, CNV-001, CNV-002, CNV-003, CNV-004, CNV-005, API-003

## Context

Journey J2 of the [product description](../product.md) asks for editing an
earlier message, or asking for another answer, without losing what followed
(CNV-001). A linear history cannot keep both continuations.

ADR-0031 stores the Pydantic AI messages produced by each run, in run order.
Pydantic AI itself takes history as a plain list (`message_history`) and has
no notion of alternatives. AG-UI 1.0 has an optional `parentRunId` in
`RunAgentInput` and `RUN_STARTED`: a reference to a prior run in the same
thread, with branching ("time travel") semantics, independent of interrupts.

The decision must be made in phase 0, because it changes the database and API
contracts of conversations.

## Decision

We will model a conversation's history as **a tree of runs**:

1. Every run has a **parent run**: the run whose messages it continues, or
   none for the first run. The messages a run produces belong to it, in order.
   This amends ADR-0031, point 1: messages are ordered within their run, and
   runs are ordered by the tree.
2. A run continues the conversation's **active path** by default. A client
   starts a different version by naming another parent with AG-UI's
   `parentRunId`: editing a message, or asking for a new answer, starts a run
   whose parent is the parent of the run being replaced. Runs with the same
   parent are **versions** of each other.
3. A run that resumes an interrupt (ADR-0033) is a child of the interrupted
   run, as a continuation, not a new version. While an interrupt is pending,
   the conversation accepts only the run that resumes it.
4. The conversation records the **active run**: the last run of the path shown
   to the user and continued by default. Starting a run makes it active;
   switching versions changes it, and rewinding (CNV-004) makes an earlier run
   of the path active. Forking (CNV-005) copies the runs of a path into a new
   conversation.
5. The agent receives the messages of the path from the first run to the
   parent, as a plain Pydantic AI `message_history` (CNV-002). Pydantic AI
   needs no branching support.
6. History served to clients is the active path, projected to AG-UI messages
   (ADR-0031, point 4), with the versions available at each turn.
7. Stopping a run (CNV-003) cancels its durable workflow (ADR-0034) and marks
   it `cancelled`; its messages so far stay in the tree.

## Consequences

- Branching uses a standard AG-UI field; standard clients that never send
  `parentRunId` simply continue the active path.
- Reading a path is a walk up the tree; paths are short (one node per turn),
  and an index on the parent makes the walk cheap.
- Deleting a single version, if offered later, deletes its subtree.
  Conversation deletion is unchanged.
- Memory items and audit events created by a run stay valid when the user
  switches to another version; they are tied to the run, not to the path.

## Alternatives considered

- **Linear history, editing truncates:** simpler, but loses answers and does
  not satisfy CNV-001.
- **A tree of individual messages:** finer than needed; a run's messages are
  produced and replaced together, and Pydantic AI's tool call and result
  pairs must never be split across versions.
- **Copying the conversation on every edit:** duplicates history and breaks
  the conversation identity that Pydantic AI and AG-UI share (ADR-0031).
