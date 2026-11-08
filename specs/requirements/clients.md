# UX — Client experience

What every first-party client must offer, on the web and on the phone.
Clients use only the public API (API-001). Background: ADR-0016, ADR-0039,
ADR-0040, ADR-0042, ADR-0067, ADR-0070, and the personas and journeys of the
[product description](../product.md).

## UX-001: Installable web app

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

The web client MUST work in current mobile and desktop browsers and MUST be
installable on the home screen of Android and iOS devices as a web app.

## UX-002: Rich message rendering

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Clients MUST render Markdown in messages, including tables, code blocks with
syntax highlighting and a copy action, and mathematical notation. Rendering
MUST NOT execute scripts or load remote resources contained in messages.

## UX-003: Simple by default, detailed on request

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** review

Clients SHOULD show tool activity, reasoning and sandbox output as compact
summaries that the user can expand to see full details. Tool activity MUST
appear where it happened among the answer's text, also while the answer
streams, and MUST show whether each call is still running or done. A command
the agent runs in the sandbox MUST say in a few words what it is for, which
clients show above the command (ADR-0085). Approval prompts MUST
nevertheless always show the tool, its arguments and destination in full
(ADR-0033).

Rationale: personas P2 and P4 need clarity; persona P1 needs the details.

## UX-004: Notifications

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

The installable web app MUST be able to receive notifications, with the user's
consent, when a run finishes while the user is away and when an approval or an
answer to a question is pending. Notification payloads MUST NOT contain
message text, titles, tool arguments or other conversation content; they MUST
carry only the kind of event and identifiers needed to open the right
conversation (ADR-0039).

Rationale: journey J8; pending approvals expire (AGT-007), so users must learn
about them in time.

## UX-005: Voice turns

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e, eval

A user MUST be able to speak a turn instead of typing it. The user starts and
ends the turn explicitly; pauses MUST NOT end it, and the assistant MUST NOT
speak while the user's turn is open. After the turn ends, the assistant MUST
produce its complete answer and read it aloud. Answers to spoken turns MUST
NOT be shortened or simplified because they will be spoken (ADR-0040).

Rationale: journey J9.

## UX-006: Sharing into the app

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** e2e

On devices that support it, the installed web app SHOULD accept text, links,
images and files shared from other apps, and offer to start a conversation
with them as attachments.

## UX-007: Accessibility

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e, review

Clients MUST meet WCAG 2.2 level AA, MUST respect the system text size and
MUST remain usable with text enlarged to 200%.

Rationale: persona P4.

## UX-008: Live context and cost

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

While a run streams, clients MUST show how much of the model's context window
the conversation uses, and the cost of the run so far on pay-per-token
providers. Clients MUST show the cost of each assistant message beside it,
and keep in view the cost of the open conversation and the user's spend over
the last 24 hours and the last 30 days (MOD-006, MOD-007, ADR-0073).

Rationale: journey J12.

## UX-009: Progress and questions during long tasks

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** e2e

The assistant SHOULD keep a task list for long tasks, one per conversation,
which lasts from one run to the next. During a run, clients SHOULD show the
task list as it updates, and its latest state when the conversation is
opened. Clients MUST show the questions the assistant asks the user
(AGT-015) as choices the user can answer, in their own words or by skipping
the question, in place of the message box, also when the conversation is
opened later; several questions are shown one at a time, and the controls to
answer stay in view on any screen (ADR-0083).

Rationale: journey J7.

## UX-010: Rewinding asks first and says the files stay

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Before a conversation is rewound (CNV-004), including by editing an earlier
message (CNV-016), clients MUST ask the user to confirm, say how many
messages will be deleted, and tell them that files in their workspace are
not changed by rewinding.

Rationale: journey J2.

## UX-011: Light and dark themes

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Clients MUST offer a light and a dark theme, follow the device's setting by
default, and let the user choose one instead. Both themes MUST meet the
contrast that UX-007 requires.

## UX-012: The sprite greets the user

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** e2e

When the user starts a new conversation, clients SHOULD show the sprite
greeting them with a quote chosen at random from a list of famous quotes in
the public domain, with its author and work, translated with the rest of the
interface (ADR-0070).

## UX-013: The sprite shows what a run is doing

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** e2e, review

While a run is in progress, clients SHOULD show the sprite acting out what
the assistant is doing: thinking, searching the web, reading, writing files,
running commands or answering; when the run ends, it stands still. The sprite
MUST be decorative: the same activity MUST be given as text, and the sprite
MUST NOT move when the device asks for reduced motion (ADR-0070).

## UX-014: Errors say what to do

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Clients MUST show errors so that they say what went wrong and how to fix it,
announced to assistive technologies, and SHOULD show the sprite holding a sign
beside them (ADR-0070). An error that ended a run MUST be shown in the
conversation, in place of the run's answer, with the reason the model or its
provider gave (MOD-015), and MUST stay there when the conversation is reloaded
or opened on another device: it is part of the conversation, not a notice to
dismiss. The reason stays too when the run's stored answer keeps it, as a
refusal's does. Other errors are shown in a notice.

Rationale: personas P2 and P4.

## UX-015: Choosing the model

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Clients MUST let the user choose the model of a conversation (MOD-012), and
tenant admins the default model, among every model of their household's
connections, and search them, with the same picker. For each
model they MUST show its connection, its name, whether it runs locally or
remotely (MOD-010), its price when it is paid per token, and whether it can
only chat, without tools (MOD-014).

## UX-016: Testing a connection in the settings

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

When a tenant admin adds or changes a connection, clients MUST show the
result of its test (MOD-013) step by step, with the reason for a failure and
how to fix it, and MUST show the technical details on request. Clients MUST
ask only for what the kind of connection needs: for OpenRouter, the API key.

## UX-017: One design language

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** review

Clients SHOULD follow the design language of ADR-0070: its layout, colors,
typefaces, icons and sprite, as the reference prototype shows them.

## UX-018: Typing starts where the user expects

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** e2e

On devices with a keyboard, clients SHOULD put the focus in the field where
the user starts typing: the username on the sign-in screen, and the message
box when a new chat opens. On touch screens they SHOULD NOT, since focusing a
field opens the on-screen keyboard over the screen.

## UX-019: The workspace panel

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Clients MUST let the user browse a conversation's workspace as a tree,
beside the conversation or, on a phone, as a full-screen sheet, with each
entry's size and when it changed, and the workspace's size against its quota
(SBX-019). The user MUST be able to preview, download, upload into a folder,
create a folder, rename and move, and delete files and folders, and reset the
whole workspace; deleting and resetting MUST ask first. A folder MUST download
as a `.zip`. The panel MUST show the workspace as it is after each answer
(ADR-0079).

## UX-020: Workspace files never run in the app

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security, e2e

A workspace file MUST NOT be served or shown as a page or a script of the
app's origin. The API MUST serve a file for download as an attachment, and
for preview only as one of a fixed list of types, with
`X-Content-Type-Options: nosniff` and a Content Security Policy that lets a
file opened by itself run nothing in the app's origin; clients MUST show HTML
as its source and SVG as an image (ADR-0079, T-22).
