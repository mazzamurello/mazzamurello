# ADR-0073: Conversations for daily use

- **Status:** Accepted
- **Date:** 2026-11-04
- **Deciders:** @tapionx
- **Related:** ADR-0003, ADR-0037, ADR-0041, ADR-0042, ADR-0066, ADR-0068, ADR-0069, AGT-016, CNV-005 to CNV-009, MOD-003, MOD-006, MOD-007, UX-008

## Context

With the web client rebuilt (ADR-0070), what a household meets every day is
missing: every chat is called "New conversation", long chats run into the
model's context window, costs are recorded but never shown, a conversation
cannot be forked, and the list cannot be organized or searched. The
requirements exist (journeys J3 and J12); what remains open is how.

ADR-0041 decided that compaction is a view only the model sees, and left the
strategy to the instance admin, per model, with a configurable summary
model. Since then the instance has no models (ADR-0069), and the maintainer
prefers fixed behavior over settings.

## Decision

1. **Helper calls use the conversation's own model.** Titles and the
   summaries of compaction are written by the model the conversation uses,
   so their data goes only where the conversation's data already goes
   (MOD-003, MOD-010), and their cost is the conversation's (MOD-006). This
   replaces ADR-0041 point 3: there is no per-model strategy and no summary
   model to configure.
2. **Titles.** When the first run of an untitled conversation starts, the
   worker asks the model, alongside the answer, for a title of a few words
   for the first message, in its language, and stores it, unless the user
   named the conversation meanwhile. The title does not wait for the answer:
   once stored, it is announced on the run's event stream with a `CUSTOM`
   event named `mzm.title`, so clients name the conversation while it is
   answered. The run finishes only after its title request did. The request is recorded in the cost ledger with the purpose
   `title`. A failed request leaves the conversation untitled.
3. **Compaction** follows ADR-0041 points 1, 2 and 4 with a fixed strategy:
   when the history of a run would exceed 80% of the model's context window,
   the oldest turns are summarized by the conversation's model, and the most
   recent turns and the current request stay as they are. The summary is a
   compaction checkpoint; the stored conversation never changes.
4. **The context window comes from the connection.** OpenRouter lists each
   model's window. A connection to your own server has a `context_window`, in
   tokens, that the admin can set, since the server decides it (Ollama's
   `num_ctx`); it is 8192 until set.
5. **Usage is reported as the run goes.** After each model response, the run
   emits an AG-UI `CUSTOM` event named `mzm.usage`, with the context window,
   the tokens the context uses, and the run's tokens and cost so far
   (MOD-007). Clients show a context gauge and the run's cost while it
   streams.
6. **Costs are shown where they are read.** Each answer shows its cost,
   small, beside its copy action; the conversation's total, and the user's
   spend over the last 24 hours and the last 30 days, stay visible. Rolling
   periods replace "the current day and month": they never reset to zero at
   midnight or on the first of the month. Local models cost nothing and show
   no cost. A page to explore costs in detail comes later.
7. **Forking copies the path.** Forking at a run creates a conversation, in
   the same folder, with copies of the runs and messages from the first run
   to that one, under new identifiers, and records the conversation and run
   it came from. The fork's title is the original's. Ledger entries are not
   copied: the original's spending happened once.
8. **Folders and pins.** Folders belong to one user. A conversation is in at
   most one folder; deleting a folder moves its conversations out. Folders
   and conversations can be pinned; a folder's collapsed state is stored, so
   that it follows the user across devices. The list API returns pinned
   entries first, then the others, each group by its most recent message,
   newest first, a folder by that of its conversations (CNV-008).
9. **Search uses PostgreSQL's full-text search** with the `simple`
   configuration, which does not depend on the language. Each stored message
   keeps the text a person reads, its user prompt or the assistant's answer,
   in an indexed column; titles are searched too. Results are ranked, limited
   by row-level security as every read is (TEN-003), and show a snippet of
   the matching text.

## Consequences

- No new setting except the context window of a connection to your own
  server, which only its admin can know.
- A title or a summary costs a model request on paid providers; both are in
  the ledger and in the conversation's total.
- Searching ignores the content of tool calls and results, which people do
  not read as conversation text.
- Forks double the storage of the path they copy, and stay correct when the
  original is rewound or deleted.

## Alternatives considered

- **A household helper model for titles and summaries:** one more setting,
  and a local conversation's content could reach a remote helper.
- **Compacting only when the server refuses:** Ollama cuts long prompts
  silently instead of refusing, so the model would answer without the start
  of the conversation.
- **Calendar day and month:** easy to explain, but the totals drop to zero at
  midnight and on the first of the month, which hides what was just spent.
- **Forks that point to the original's runs:** no copy, but rewinding or
  deleting the original would change or break the fork (ADR-0068).
- **Trigram search:** finds parts of words, but ranks poorly and grows large
  for long conversations.
