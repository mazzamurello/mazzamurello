# ADR-0038: Artifacts stored as versioned objects and rendered on an isolated origin

- **Status:** Proposed
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0012, ADR-0030, ADR-0035, ART-001, ART-002, ART-003, ART-004, AGT-003

## Context

Journey J6 of the [product description](../product.md) asks for outputs that
live next to the conversation, can be revised and downloaded: documents,
code, diagrams, web pages. Some of them are active content: a web page or an
SVG image can run scripts when displayed. Their content may be derived from
untrusted sources (AGT-003), so displaying them is a way for injected code to
act in the user's browser.

Files created by the agent in the sandbox (ADR-0035) are already downloadable
(SBX-014); artifacts are what the client displays.

## Decision

We will:

1. Store each artifact as an object of the conversation's owner, with an
   artifact type and a list of immutable versions. Artifacts are created and
   revised through mediated tools offered to the agent (AGT-001); each
   revision is a new version (ART-001).
2. Announce artifact changes to clients as AG-UI events of the run, so that
   they appear while the answer streams.
3. Serve active content (web pages, SVG) **from a separate origin**, a
   dedicated host name configured by the instance admin, that never receives
   device session cookies, inside a frame with the `sandbox` attribute (no
   `allow-same-origin`) and a restrictive Content Security Policy. Access to
   an artifact on that origin uses a short-lived, read-only grant for that one
   version, never the device session token (ART-003).
4. Render passive types (Markdown, code, diagrams in a text notation) in the
   client with the same rules as messages (UX-002).

## Consequences

- One more host name to configure for deployments that display web page
  artifacts; without it, such artifacts are offered only as downloads.
- The artifact tools join the agent's tools and their capability classes.
- Artifact contracts (API and database) are written at the start of phase 1.

## Alternatives considered

- **Rendering active content on the client's origin:** simplest, but gives
  injected scripts the user's session.
- **Only downloads, no rendering:** safe, but does not satisfy journey J6.
- **Artifacts as plain files in the workspace:** reuses storage, but the
  workspace is execution-plane storage the sandbox can modify at any time,
  which defeats immutable versions.
