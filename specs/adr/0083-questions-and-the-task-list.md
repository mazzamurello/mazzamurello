# ADR-0083: Questions to the user and the task list

- **Status:** Accepted
- **Date:** 2026-11-08
- **Deciders:** @tapionx
- **Related:** ADR-0031, ADR-0032, ADR-0033, ADR-0037, ADR-0043, AGT-003, AGT-015, UX-009

## Context

Journey J7 asks for long tasks the user can follow and steer: the assistant
should say what it plans and how far it got, and ask when it cannot decide.
The harness offers both (ADR-0043):

- `AskUser` gives the model one tool, `ask_user_question`: one to a few
  questions, each with a short header and two to six options, single or
  multiple choice. With `answerer=None` the call is deferred: the run ends
  with `DeferredToolRequests`, and a later run passes the answer as
  `DeferredToolResults`. `ask_user_result` checks an answer against the
  question and renders what the model receives; `check_response` validates
  text a user typed.
- `Planning` gives the model tools to write and update a task list, and keeps
  the list in a `PlanStore` it reads before each model request.

ADR-0033 decided how a run waits for the user: it ends as `interrupted`, the
pending requests are stored with the conversation, and the answer starts a
new run. No interrupt existed until now: the API refuses `resume`, and Pydantic
AI's AG-UI stream turns only approvals into interrupts, not deferred calls.

## Decision

1. **Questions are deferred calls of `AskUser`**, given to every run that
   has tools. A run that ends with calls to `ask_user_question` is
   interrupted: the worker stores its `DeferredToolRequests` in
   `conversations.pending_interrupts`, marks the run `interrupted`, and
   finishes the stream with `RUN_FINISHED` whose `outcome` is
   `{type: interrupt, interrupts}`. Each interrupt has the ID `int-` followed
   by the tool call's ID, `reason` `ask_user`, the `toolCallId`, and
   `metadata.questions`: the questions as the model asked them. Questions
   do not expire. Amended by ADR-0090: questions pending with an approval
   are declined when the approval expires.
2. **Answering:** the client starts a run with `resume`, one entry per
   pending interrupt. `status: resolved` with `payload.answers`, one per
   question: `{header, selected}` with the labels picked, or
   `{header, custom_answer}` with the user's own words, at most 2000
   characters. `status: cancelled` declines. The server checks each entry
   against the stored question with `check_response`, renders the result
   with `ask_user_result`, and passes the results to the worker in the
   workflow input; it refuses entries for unknown interrupts, missing
   entries and answers that do not fit (`approval.invalid`). The new run has
   kind `resume`, continues the interrupted run, and clears
   `pending_interrupts` when it starts.
3. **A pending question blocks** new messages, rewinds and forks
   (`run.interrupt_pending`); the client shows it in place of the message
   box, one question at a time, with a counter and arrows to move between
   them, in a card no taller than the window, so that its buttons stay in
   reach. Until the last question, the card offers Skip and Next, which
   needs the question answered; on the last, Skip and Answer, which needs
   every question answered. Picking a choice never moves on by itself: the
   user moves with Next or the arrows. `GET /conversations/{id}` returns the pending interrupts, so a
   client opened later shows them too.
4. **Answers carry the user's provenance**: what the model receives is
   built by the server from its stored question and the user's choice, so it
   is labeled as the user's input, not as tool output, when provenance
   comes (AGT-003). The model writes the questions, so clients show them as
   the assistant's, never as a prompt of the app.
5. **The task list is `Planning`** with a store per conversation, the table
   `conversation_plans`, under row-level security. The list lasts from run
   to run; a fork copies it, and a rewind leaves it to the model to rewrite.
   After each planning tool returns, the worker emits a `CUSTOM` event
   `sibillo.plan` with the list; `GET /conversations/{id}` returns it as `plan`.
6. **Always on:** questions and the task list are not among the tools a
   user switches off (CNV-013); a run without tools has neither.
7. **In the history**, the calls to `ask_user_question` and to the planning
   tools stay tool calls; clients show a question with its answer, and
   changes to the task list folded.

## Consequences

- The interrupt path of ADR-0033, from the worker to the client, exists and
  is tested before approvals use it; approvals add an expiry and their own
  payload.
- AG-UI clients see a standard interrupt; only the payload of the answer is
  ours.
- A model that never calls `ask_user_question` or the planning tools works as
  before.

## Alternatives considered

- **Waiting inside the run for the answer:** holds a durable workflow open
  for as long as the user takes, and diverges from ADR-0033.
- **Free-text questions in the answer:** the user must read the whole answer
  to find them, and a client cannot show choices.
- **The task list in the system prompt:** changes the prompt on every update,
  which defeats prompt caching; `Planning` keeps it in the conversation.
- **A task list per run:** lost when a question interrupts the run, which is
  exactly when the user wants to see it.
