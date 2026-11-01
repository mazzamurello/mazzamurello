# API — Public API and conversations

The interface every client uses. Background: ADR-0016, ADR-0008.

## API-001: One public API for all clients

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

Every first-party client MUST use only the public HTTP API. The server MUST
NOT expose client-specific private endpoints.

## API-002: Committed OpenAPI contract

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The public API MUST be described by an OpenAPI document committed in
`specs/contracts/`. CI MUST fail when the server serves an operation the
contract does not describe or lacks one it describes, or when a request the
server accepts or a response it sends during the test suite does not match
the contract (ADR-0056).

## API-003: Separate conversations

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** e2e

A user MUST be able to create, list, open, rename, archive and delete
conversations. Each conversation MUST have its own history; content MUST NOT
flow between conversations except through memory items (MEM-004).

## API-004: Streaming responses

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Assistant responses, including tool activity, MUST be streamed to clients
with Server-Sent Events carrying AG-UI 1.0 events, each with a sequence
number. A client that reconnects MUST be able to resume receiving the events
after the last sequence number it received, while the run is in progress or
after it has finished (ADR-0032).

## API-005: Compatibility and deprecation

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 2
- **Verification:** review

Breaking changes to the public API SHOULD be introduced only with a new
version, migration notes and a deprecation period for the previous behavior.

## API-006: Voice input and output

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

The API MUST transcribe a recorded spoken turn into text (speech-to-text) and
synthesize an assistant message as audio (text-to-speech), for voice turns
(UX-005). Speech services MUST be local by default; remote speech services
MUST be subject to the data egress policy (MOD-003). Recordings MUST NOT be
kept after transcription unless the user chooses to keep them.

## API-007: Stable error codes

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

Every error response of the public API MUST carry a stable, machine-readable
error code documented in the API contract, so that clients can present errors
in the user's language.
