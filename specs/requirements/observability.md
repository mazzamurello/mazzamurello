# OBS — Observability and privacy

What the system records about its own behavior, and what it never records.
Background: ADR-0014, ADR-0058, ADR-0072.

## OBS-001: Nothing sent to external services by default

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The system MUST NOT send telemetry, analytics, crash reports, logs or traces
to any external service unless the instance admin explicitly configures it.

## OBS-002: Metrics without content

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** unit

Metrics MUST NOT contain message text, tool arguments or outputs, memory
items or any other user content.

## OBS-003: Content redacted in logs and traces

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** unit

Logs and traces MUST redact message text, tool arguments and outputs, memory
items and credentials by default.

## OBS-004: Per-user debug mode

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 3
- **Verification:** integration

A user SHOULD be able to enable, for themselves only, a debug mode that
records unredacted traces locally. It SHOULD be visibly indicated and turn
itself off automatically after at most 24 hours.

## OBS-005: Bounded retention

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

Logs and traces MUST be deleted after a retention period configurable by the
instance admin, with a default of at most 14 days.

## OBS-006: Outbound requests only to declared destinations

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security, design

The control plane MUST connect to external services only for the declared
destinations of ADR-0072, each only for its purpose, and no library may
download data at run time. The web client MUST load every script, style,
font, icon and image from the instance itself, never from a CDN or another
third party.

Rationale: what leaves the household must be what its users and admins chose
to send, and a short list they can check.
