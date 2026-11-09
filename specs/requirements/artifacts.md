# ART — Artifacts

Outputs the assistant creates for the user and shows next to the
conversation: documents, code, diagrams, web pages, spreadsheets. They are
files of the conversation's workspace, opened in a viewer.
Background: ADR-0086, which supersedes ADR-0038, journey J6 of the
[product description](../product.md).

## ART-001: Artifacts are workspace files

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

The agent MUST be able to make a file in the conversation's workspace, revise
it, and show it to the user in the conversation. A file it shows MUST open in
a viewer from the answer, and the user MUST be able to download it. Any file
of the workspace MUST open in the same viewer. Files are not versioned: a file
shown by an earlier answer opens as it is now (ADR-0086).

## ART-002: Artifact types

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Clients MUST be able to display at least these types: Markdown documents,
source code highlighted, CSV tables, images including SVG, diagrams written
in Mermaid, web pages, PDF, audio and video, and MUST show the source of the
textual ones on request. Other files MUST at least be downloadable. The
agent's instructions MUST say how to make web pages and diagrams that
display (ADR-0086).

## ART-003: Isolated rendering of active content

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security

Content that can execute code when displayed MUST NOT run with the client's
origin. A web page MUST run in a sandboxed frame, in a document with an
opaque origin, without network access; an SVG image MUST be displayed as an
image, which runs no scripts. Their code MUST NOT be able to read device
session credentials, call the public API as the user, or read other files
(ADR-0086).

Rationale: an artifact may contain untrusted content (AGT-003); rendering it
must not hand that content the user's session (threat T-22).

## ART-004: Artifacts are private data

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security

An artifact MUST belong to the conversation whose workspace holds it and be
private to its owner, as the workspace is (SBX-010). Other users of the
tenant MAY receive a read-only copy only when the owner sends it to them
(CNV-010).
