# CNV — Conversations and spaces

How conversations behave and how they are organized, beyond the basic
operations of API-003. Background: ADR-0031, ADR-0037, journeys J1 to J5 and
J10 of the [product description](../product.md).

## CNV-001: Message versions

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** e2e

A user MUST be able to edit one of their earlier messages, or ask for a new
answer to it, without losing what followed it. The earlier continuation MUST
be kept as another version, and the user MUST be able to list the versions,
switch between them and continue from any of them (ADR-0037).

Rationale: journey J2.

## CNV-002: Only the active path reaches the model

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

A run MUST receive as history only the messages on the path from the start of
the conversation to the turn it continues. Messages of other versions MUST NOT
be sent to the model or used by tools in that run.

## CNV-003: Stopping a run

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

A user MUST be able to stop a queued or running run. A stopped run MUST NOT
start further model or tool calls; the messages it produced before stopping
MUST be kept, and the run MUST be recorded as cancelled.

Rationale: journey J1.

## CNV-004: Automatic titles

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** integration

A new conversation SHOULD receive a short title generated from its first
exchange, unless the user has already named it. Title generation is a model
call and is subject to the data egress policy (MOD-003).

## CNV-005: Pinned conversations

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** e2e

A user SHOULD be able to pin conversations, which are then listed before the
others.

## CNV-006: Search

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A user MUST be able to search the titles and message text of the
conversations they can access. Search results MUST be limited by row-level
security like any other read (TEN-003).

## CNV-007: Spaces

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

A user MUST be able to create spaces, each with a name, instructions for the
assistant and reference files, and to place conversations in a space or keep
them outside any space. Runs in a conversation of a space MUST receive the
space's instructions and have access to its reference files.

Rationale: journey J3. A space shared with other users is a shared space
(TEN-007).

## CNV-008: Sharing within the household

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security, integration

A user MUST be able to share a space with chosen users of their tenant, and to
send a read-only copy of a conversation to another user of their tenant.
Sharing MUST be explicit (TEN-007). The system MUST NOT offer links that give
access to a conversation, a space or an artifact without authentication.

Rationale: journey J4.

## CNV-009: Temporary conversations

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A user MUST be able to start a temporary conversation. A temporary
conversation MUST NOT be listed with the others, MUST NOT create or use
memory items, and MUST be physically deleted, with its runs, when the user
leaves it or at the latest 24 hours after its last activity.

Rationale: journey J10.

## CNV-010: Attachments

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A user MUST be able to attach images, PDF files and common document formats
to a message. Attachments MUST be stored as private data of the user
(TEN-008), MUST be available to the agent in the sandbox of that user, and
MUST be subject to the data egress policy when sent to a remote model
(MOD-003).

Rationale: journey J5.

## CNV-011: Conversation settings

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** integration

A user SHOULD be able to choose, for a conversation, the model among those the
instance offers them, and whether the model may reason at length before
answering. The settings SHOULD default to those of the conversation's space,
then to the user's defaults.
