# Product: personas and journeys

Who Mazzamurello is for, and what they do with it. Requirements about the
user experience are justified by these personas and journeys; a feature that
serves none of them needs a new persona or journey here first.

The bar is high: the experience must be as good as the best hosted
assistants, on the web and on the phone, while keeping every principle of the
[vision](../VISION.md).

## Personas

All personas are members of the same household, each with their own account
and private data. None of them gets age-specific behavior (VISION.md).

### P1 — The technical admin

Runs the server and administers the tenant. Uses the assistant all day, on the
desktop browser and the phone: long working conversations, code, documents,
data analysis, research. Uses the sandbox heavily and wants to see what the
assistant did (tool calls, commands, outputs), how full the context is and
what each answer cost. Tunes models, tools, instructions and skills.
Tolerates complexity but not friction.

### P2 — The non-technical adult

Uses the assistant mostly from the phone for everyday life: questions,
planning, writing and reviewing documents, understanding photos and PDFs,
household organization. Never thinks about sandboxes or models. Needs clear
defaults, readable answers and understandable approval prompts.

### P3 — The teenager

Uses it for school, learning and creative projects, on the phone and a laptop.
Expects a fast, modern interface. Benefits from rendered outputs (documents,
diagrams, small web pages) and from organizing work by subject.

### P4 — The older relative

Uses the phone, prefers speaking to typing, reads with large text. Needs few
choices on screen, forgiving interactions and complete, well-structured
answers read aloud. Is not interrupted while speaking and is never rushed.

## Journeys

Each journey names the personas it serves most.

### J1 — Ask and follow up (all)

Opens the app on the conversation list, starts a new conversation or
continues one, sends a message and reads the answer as it streams, with
formatted text, code, tables and math. Stops a run that goes in the wrong
direction. Leaves the app and finds the complete answer when coming back, on
any device where they are signed in, and continues there.

### J2 — Try another way (P1, P2, P3)

Edits an earlier message, or asks for a different answer, without losing the
previous one, and switches between the versions to compare them. Rewinds the
conversation to an earlier turn and continues from there. Forks a
conversation into a new one that starts from a chosen turn and goes its own
way.

### J3 — Find and organize conversations (all)

The conversation list is the main screen. Conversations are ordered by their
most recent message, newest first. Folders sit in the same list and are
ordered by the most recent message of any conversation they contain; they can
be collapsed and expanded. Conversations and folders can be pinned on top. A
fork starts in the folder of the conversation it came from and shows where it
came from. Old conversations are found by searching their content.

### J4 — Share with the family (P1, P2)

Sends a member of the household a copy of a conversation or an artifact, or
puts information in a shared space. Nothing is shared unless they share it
explicitly.

### J5 — Show, don't just tell (P2, P3, P4)

Sends a photo, a screenshot or a PDF taken on the phone, or shares a page or a
file into the app from another app, and asks about it. Every uploaded file
goes into their files, where any later conversation can use it again.

### J6 — Make something (P1, P3)

Asks for a document, a diagram, a small web page or a spreadsheet. The
assistant produces an artifact shown next to the conversation, revises it on
request keeping each version, and lets them download it.

### J7 — Let the assistant work (P1)

Asks for a task that needs the sandbox: running code, installing tools,
processing files, browsing. Follows a task list of the steps, sees each step
in detail when they want to, answers the questions the assistant asks, and
approves the actions that need approval. Long tasks keep going when the
context fills up, because older parts of the conversation are compacted for
the model while the full conversation stays visible.

### J8 — Be told when it matters (all)

Starts a long task, closes the app, and receives a notification on the phone
when the answer is ready or when the assistant needs an approval or an answer.
The notification itself reveals nothing of the conversation.

### J9 — Talk instead of typing (P4, P2)

Presses a button and speaks a whole turn, taking as long as needed, with
pauses, and presses the button again when finished. The assistant thinks,
writes its complete answer and reads it aloud. It never interrupts, and it
does not shorten its answer because it is spoken.

### J10 — Keep it off the record (P1, P2, P3)

Opens a temporary conversation for something they do not want to keep: it is
not listed in the history, not used for memory, and deleted when they leave
it.

### J11 — Know and correct what it remembers (all)

Sees what the assistant remembers about them, corrects it or deletes it
(MEM-001 to MEM-003).

### J12 — Know what it costs (P1)

Sees, while a conversation runs, how much of the model's context window is in
use, and what each message, each conversation and the whole month cost on
pay-per-token providers. Every model call is in their cost ledger, including
the calls that generate titles or compact history.

### J13 — Tailor the assistant (P1, P3)

Switches the model of a conversation at any turn and chooses which tools it
may use, starting from good defaults. Edits the assistant's base instructions
or adds instructions of their own, for all conversations or for one. Writes
skills, or imports skills others have written, and uses them in any
conversation.
