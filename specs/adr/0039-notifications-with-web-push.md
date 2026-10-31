# ADR-0039: Notifications with Web Push and content-free payloads

- **Status:** Proposed
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0016, ADR-0033, UX-001, UX-004, AGT-007, OBS-001

## Context

Runs continue when the client is closed (AGT-009), and pending approvals
expire and are denied when nobody answers (AGT-007). Journey J8 of the
[product description](../product.md) needs the user to be told on the phone.
A native mobile app is a phase 3 candidate; phase 1 has an installable web
app (UX-001).

The Web Push standard (RFC 8030, with VAPID, RFC 8292, and message
encryption, RFC 8291) works for installed web apps on Android, desktop
browsers and iOS 16.4 or later. Messages go through the browser vendor's push
service, a third party.

## Decision

We will deliver notifications with **Web Push**:

1. The server keeps the VAPID key pair in the control plane and the push
   subscriptions of each device session as private data of the user.
   Revoking a device session deletes its subscriptions.
2. Payloads are encrypted, as the standard requires, and carry **no content**:
   only the event kind (`run_finished`, `approval_pending`) and the
   conversation and run identifiers. The client shows a generic text in the
   user's language and loads the details from the API after the user opens it
   (UX-004).
3. A notification is sent only when no client of the user is following the
   run's events.

## Consequences

- No conversation content reaches the push services; they still learn that
  the instance sent a notification to a device, and when. This is documented
  for users who enable notifications, and notifications are off until a user
  enables them on a device (OBS-001).
- A native app (phase 3) can reuse the same events with another transport.

## Alternatives considered

- **No notifications in phase 1:** users would miss approvals before they
  expire.
- **A self-hosted push relay (such as ntfy):** avoids vendor push services,
  but requires installing another app on each phone, which personas P2 and P4
  will not do. It remains a possible additional transport.
- **Email:** slow and noisy for this purpose, and requires mail
  configuration.
