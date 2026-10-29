# ADR-0016: API first; web (installable PWA) first, native mobile later; voice through the API

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** ADR-0008, API-001, API-002, API-003, API-004, API-006

## Context

The primary ways of using the assistant are the web and the phone, organized
in many separate conversations, one per purpose. Voice matters too, mostly as
"ask, let it work, listen to a long answer" rather than real-time calls.
A native mobile app is the most expensive component to build and maintain.

## Decision

We will:

1. Expose **one public HTTP API**, described by a committed OpenAPI
   contract, used by every first-party client. No client has private
   back doors.
2. Organize interaction in **separate conversations**: users create, list,
   rename, archive and delete them.
3. Stream responses with **Server-Sent Events**.
4. Build the **web client first, as an installable Progressive Web App**,
   which also serves phones. A native mobile app follows when push
   notifications, background audio or platform integration require it.
5. Provide **voice through the API** (speech-to-text in, text-to-speech out),
   backed by local speech services by default, so every client gets it.
6. Treat chat-app integrations (messaging bridges) as optional connectors,
   never as the primary interface.

## Consequences

- Third parties can build their own clients on a stable, documented API.
- Push notifications on mobile require platform push services; this needs
  its own design (Web Push for the PWA first).

## Alternatives considered

- **Messaging apps as the main interface:** a single endless thread per
  channel, data flowing through third parties.
- **Native mobile app first:** highest cost before the core is proven.
