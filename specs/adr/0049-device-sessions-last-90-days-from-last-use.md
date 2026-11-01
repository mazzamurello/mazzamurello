# ADR-0049: Device sessions last 90 days from their last use

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0025, ADR-0048, AUTH-004, AUTH-009

## Context

AUTH-004 requires every device session to carry an expiry, and the database
contract stores `expires_at`, but no lifetime is specified. Family members
mostly use phones, where signing in again is a chore, while a lost or
forgotten device should not stay signed in forever.

## Decision

1. A device session expires **90 days after its last use**. At login,
   `expires_at` is 90 days after the session is created.
2. Every authenticated request that accepts the session sets `last_used_at`
   to the current time and moves `expires_at` to 90 days later, through
   `auth_touch_session`.
3. An expired session is rejected like a revoked one and is no longer listed
   among the user's sessions. It is never renewed: renewing happens only on a
   request that the session authenticates.

## Consequences

- A device in daily use stays signed in indefinitely; one left unused for 90
  days signs out by itself.
- Revocation (AUTH-004) and disabling the account (AUTH-009) remain the way
  to end a session at once.
- Every authenticated request writes to `device_sessions`. At the scale of a
  household this is negligible.
- Expired and revoked sessions remain in the table; deleting them after a
  retention period can come later.

## Alternatives considered

- **30 days from last use:** unused devices drop out sooner, but people who
  open the app once a month would sign in at every visit.
- **90 days from login, never renewed:** a simpler rule, but everyone signs
  in again every three months, including on devices in daily use.
