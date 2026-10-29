# MEM — Memory

What the assistant remembers across conversations, and the user's control
over it. Background: ADR-0013.

## MEM-001: Memory is visible

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

A user MUST be able to list and read every memory item the assistant holds
about them.

## MEM-002: Memory is editable

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

A user MUST be able to edit any of their memory items, and the assistant MUST
use the edited version from then on.

## MEM-003: Memory deletion is real

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

Deleting a memory item MUST remove it and every derived copy (embeddings,
search indexes, caches) so that it can no longer influence the assistant.

## MEM-004: Memory is private

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security

Memory items MUST be private to their user. A memory item MUST exist in a
shared space only when it is explicitly created there.

## MEM-005: Memory provenance

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** integration

Each memory item SHOULD record when and from which conversation it was
created, and show this to the user.

## MEM-006: Memory can be disabled

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

A user MUST be able to turn memory off; while it is off, no memory items
are created or used for that user.
