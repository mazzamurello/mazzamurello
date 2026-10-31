# ART — Artifacts

Outputs the assistant creates for the user and shows next to the
conversation: documents, code, diagrams, web pages, spreadsheets.
Background: ADR-0038, journey J6 of the [product description](../product.md).

## ART-001: Artifacts with versions

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

The agent MUST be able to create an artifact and revise it. Every revision
MUST create a new version; earlier versions MUST stay available, and the user
MUST be able to view any version and download it.

## ART-002: Artifact types

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Clients MUST be able to display at least these artifact types: Markdown
documents, source code, SVG images, diagrams written in a text notation, and
web pages. Other files produced in the sandbox MUST at least be downloadable.

## ART-003: Isolated rendering of active content

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security

Artifacts that can execute code when displayed, such as web pages and SVG
images, MUST be rendered on an origin separate from the API and the client,
inside a sandboxed frame. Their code MUST NOT be able to read device session
credentials, call the public API as the user, or read other artifacts.

Rationale: an artifact may contain untrusted content (AGT-003); rendering it
must not hand that content the user's session (threat T-22).

## ART-004: Artifacts are private data

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security

An artifact MUST belong to the conversation that created it and be private to
its owner, or visible to the members of the shared space that contains the
conversation (CNV-008).
