# ADR-0031: Pydantic AI's conversation model as the source of truth

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0030, ADR-0032, ADR-0033, API-003

## Context

The first database contract stored messages as a role and a text. A real
conversation also contains tool calls, tool results, reasoning, model
metadata and pending approvals. Pydantic AI represents all of this with
`ModelMessage` (`ModelRequest` / `ModelResponse` and their parts) and with
`Conversation`, which adds usage, `conversation_id` and pending deferred tool
requests. Its documentation states that the stored conversation is
"everything you need to resume". It provides official serializers
(`ModelMessagesTypeAdapter`, `ConversationTypeAdapter`).

## Decision

We will:

1. Store **Pydantic AI messages** as the source of truth of a conversation:
   the messages produced by each run (`new_messages()`), serialized with the
   official adapters, in run order.
2. Store the conversation-level state Pydantic AI keeps in `Conversation`
   (usage, pending deferred tool requests) alongside, so that a
   `Conversation` can be reassembled exactly.
3. Use **the same identifiers**: our conversation ID is Pydantic AI's
   `conversation_id`, and our run ID is Pydantic AI's `run_id` (passed
   explicitly to each run).
4. Serve conversation history to clients as a **projection** of the stored
   messages, in the message format of the client protocol (ADR-0032). The
   projection is derived, never stored as a second source of truth.
5. Never accept conversation history from clients: history is managed by the
   server, and only the new user input is taken from a request.

## Consequences

- Nothing about a conversation is lost, and resuming, auditing and evals work
  on the real record.
- The stored format follows Pydantic AI's serialization; framework upgrades
  that change it are reviewed (REPO-010) and handled by migrations.
- Clients cannot inject forged tool results or system content through history.

## Alternatives considered

- **Our own message schema:** simpler to query, but lossy and a permanent
  translation layer.
