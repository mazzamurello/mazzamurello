# CNV — Conversations, folders and files

How conversations behave and how they are organized, beyond the basic
operations of API-003. Background: ADR-0031, ADR-0037, ADR-0041, ADR-0044,
journeys J1 to J5, J10 and J13 of the [product description](../product.md).

## CNV-001: Message versions

- **Status:** deprecated
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

A user MUST be able to edit one of their earlier messages, or ask for a new
answer to it, without losing what followed it. The earlier continuation MUST
be kept as another version, and the user MUST be able to list the versions,
switch between them and continue from any of them (ADR-0037).

Replaced by CNV-016: editing rewinds, and a fork keeps both ways (ADR-0068).

## CNV-002: Only the active path reaches the model

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

A run MUST receive as history only the messages on the path from the start of
the conversation to the turn it continues, possibly compacted (ADR-0041).
Messages that rewinding deleted (CNV-004) MUST NOT be sent to the model or
used by tools in that run.

## CNV-003: Stopping a run

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

A user MUST be able to stop a queued or running run. A stopped run MUST NOT
start further model or tool calls; the messages it produced before stopping
MUST be kept, and the run MUST be recorded as cancelled.

Rationale: journey J1.

## CNV-004: Rewinding

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A user MUST be able to rewind a conversation to any earlier turn, or to
before its first turn, and continue from there. What followed that turn MUST
be deleted: its messages, runs and run events (ADR-0068). Rewinding MUST NOT
change files in the user's workspace, and the API contract MUST say so;
clients ask first and tell the user (UX-010).

Rationale: journey J2.

## CNV-005: Forking

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

A user MUST be able to fork a conversation at any turn into a new
conversation, which starts with a copy of the history up to that turn and
then evolves independently. The fork MUST record the conversation and turn it
came from, and MUST be placed in the same folder (ADR-0073).

Rationale: journeys J2 and J3.

## CNV-006: Automatic titles

- **Status:** implemented
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** integration

A new conversation SHOULD receive a short title generated from its first
exchange by the conversation's own model, unless the user has already named
it. Title generation is a model call and is subject to the data egress
policy (MOD-003) and to the cost ledger (MOD-006, ADR-0073).

## CNV-007: Folders

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

A user MUST be able to create, rename and delete folders, and to move
conversations into a folder or out of it. A conversation is in at most one
folder. Deleting a folder MUST NOT delete its conversations, which move out of
it. Folders only group conversations; they carry no instructions or
settings.

Rationale: journey J3.

## CNV-008: Conversation list

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

The API and clients MUST present a single list of conversations and folders:

- pinned entries first, then the others;
- within each group, ordered by the time of the most recent message, newest
  first, where a folder's time is that of the most recent message of any of
  its conversations;
- conversations and folders can be pinned and unpinned;
- folders can be collapsed and expanded, and the choice is kept for the user
  on every device (ADR-0073).

Rationale: journey J3.

## CNV-009: Search

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A user MUST be able to search the titles and message text of the
conversations they can access. Search results MUST be limited by row-level
security like any other read (TEN-003).

## CNV-010: Sharing within the household

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security, integration

A user MUST be able to send a read-only copy of a conversation, or of an
artifact, to other users of their tenant. Sharing MUST be explicit
(TEN-007). The system MUST NOT offer links that give access to a
conversation, a file or an artifact without authentication.

Rationale: journey J4.

## CNV-011: Temporary conversations

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A user MUST be able to start a temporary conversation. A temporary
conversation MUST NOT be listed with the others, MUST NOT create or use
memory items, and MUST be physically deleted, with its runs, when the user
leaves it or at the latest 24 hours after its last activity. Its entries in
the cost ledger are kept, without content.

Rationale: journey J10.

## CNV-012: File library

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

Every user MUST have a file library holding the files they upload, such as
images, PDF files and documents. A file attached to a message MUST be stored
in the file library, and any of the user's conversations MUST be able to
reference files of the library. Files MUST be private data of the user
(TEN-008), MUST be made available to the agent in that user's sandbox only,
and MUST be subject to the data egress policy when sent to a remote model
(MOD-003). The user MUST be able to list, rename and delete their files.

Rationale: journey J5.

## CNV-013: Conversation settings

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A user MUST be able to change, for a conversation and at any turn, the model
among those offered to them, whether the model may reason at length, and
which of their permitted tools are enabled (AGT-002). The change applies from
the next run. New conversations MUST start from the user's defaults, which
start from defaults set by the instance admin, so that a user who changes
nothing gets a well-configured assistant.

Rationale: journey J13.

## CNV-014: Custom instructions

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A user MUST be able, both as a default for all conversations and for a single
conversation:

- to replace the assistant's base instructions with their own, and restore
  the default at any time;
- to add instructions of their own, kept separate from the base instructions.

Clients MUST present the two as separate settings. Instructions MUST NOT
affect security controls, which never rely on prompts (ADR-0044).

Rationale: journey J13.

## CNV-015: Continuity across devices

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

A conversation MUST be continuable from any device where its owner is signed
in, including a run in progress, whose events a second device receives from
the start (API-004).

Rationale: journey J1.

## CNV-016: Editing a message

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, e2e

A user MUST be able to edit one of their earlier messages. Editing MUST
rewind the conversation to the turn before that message (CNV-004) and send
the edited message as a new turn. To keep what followed as well, the user
forks the conversation first (CNV-005, ADR-0068).

Rationale: journey J2.
