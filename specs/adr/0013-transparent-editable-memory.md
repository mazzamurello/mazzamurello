# ADR-0013: Memory is transparent and fully controlled by the user

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** MEM-001, MEM-002, MEM-003, MEM-004, MEM-005, MEM-006

## Context

An assistant that remembers across conversations is much more useful, and
much more invasive. Hidden memory erodes trust and conflicts with the right
to rectification and erasure of personal data.

## Decision

We will make memory a first-class, user-facing feature:

- users can **see** every memory item the assistant holds about them, with
  its origin (which conversation, when);
- users can **edit** and **delete** any memory item; deletion is real and
  also removes derived data (embeddings, indexes, caches);
- memory is private to its user; memory in a shared space exists only when
  explicitly created there;
- users can turn memory off.

## Consequences

- Memory must be stored in a structured, inspectable form, not only as
  opaque embeddings.
- Deletion must be traceable through every derived store; tests verify it.

## Alternatives considered

- **Opaque, model-managed memory:** convenient to build, impossible to audit.
