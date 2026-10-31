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
assistant did (tool calls, commands, outputs). Tolerates complexity but not
friction.

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

Opens the app, starts a new conversation or continues one, sends a message
and reads the answer as it streams, with formatted text, code, tables and
math. Stops a run that goes in the wrong direction. Leaves the app and finds
the complete answer when coming back, on any device.

### J2 — Try another way (P1, P2, P3)

Edits an earlier message, or asks for a different answer, without losing the
previous one. Switches between the versions to compare them and continues
from the one they prefer.

### J3 — Organize work (P1, P3)

Groups related conversations in a space with its own instructions and
reference files (a school subject, a work project, the household budget).
Finds an old conversation by searching its content. Pins the conversations
used every day.

### J4 — Share with the family (P1, P2)

Shares a space with other members of the household, such as household
documents or holiday planning, or sends a member a copy of a conversation.
Nothing is shared unless they share it explicitly.

### J5 — Show, don't just tell (P2, P3, P4)

Sends a photo, a screenshot or a PDF taken on the phone, shares a page or a
file into the app from another app, and asks about it.

### J6 — Make something (P1, P3)

Asks for a document, a diagram, a small web page or a spreadsheet. The
assistant produces an artifact shown next to the conversation, revises it on
request keeping each version, and lets them download it.

### J7 — Let the assistant work (P1)

Asks for a task that needs the sandbox: running code, installing tools,
processing files, browsing. Sees the steps in detail when they want to, and
approves the actions that need approval.

### J8 — Be told when it matters (all)

Starts a long task, closes the app, and receives a notification on the phone
when the answer is ready or when the assistant needs an approval. The
notification itself reveals nothing of the conversation.

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
