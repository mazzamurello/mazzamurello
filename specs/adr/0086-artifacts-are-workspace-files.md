# ADR-0086: Artifacts are workspace files, shown in a viewer

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** @tapionx
- **Related:** ADR-0038, ADR-0067, ADR-0076, ADR-0078, ADR-0079, AGT-004, AGT-023, ART-001, ART-002, ART-003, ART-004, UX-020

## Context

ADR-0038 planned artifacts as objects of their own: stored in the database
with immutable versions, created through artifact tools, and active content
served from a separate domain. Since then, each conversation got a persistent
workspace (ADR-0076, ADR-0078): the assistant writes files there with its
file tools, the user browses them in the Files panel, which previews
Markdown, CSV, text, images, PDF, audio and video (ADR-0079), and the
assistant offers a file to the user with a card that opens it there
(AGT-023). Forks copy the workspace; deleting a conversation deletes it.

Versions mainly let an earlier answer show what it showed then. The assistant
rewrites a file as easily as it revises an artifact, and a user who wants a
history can ask for one: the sandbox has git.

A separate domain for active content is the strongest isolation, but a second
domain, certificate and proxy entry is a burden for a household hosting its
own instance. Browsers give a document an opaque origin when it is served
with the `sandbox` directive of its Content Security Policy and shown in a
frame with the `sandbox` attribute: it is a stranger to every origin,
including the one it was served from, has no access to its cookies or
storage, and is limited by its policy in what it may load.

## Decision

1. **An artifact is a workspace file the assistant shows.** It makes and
   revises files with its file tools, and shows one with `offer_download`,
   whose card opens the file in the viewer and downloads it. No artifact
   tools, tables or versions; a card of an earlier answer opens the file as
   it is now, or says it is gone.
2. **One viewer for every workspace file,** in the Files panel, and larger on
   request: Markdown rendered as messages are, source code highlighted, CSV
   as a table, images, SVG included, as images, Mermaid diagrams (`.mmd`)
   drawn as an image, web pages run, PDF, audio and video. The textual types
   switch between their preview and their source.
3. **Web pages run on the same address, in an opaque origin.** The file
   endpoint serves an HTML file with `page=true` as `text/html` with the
   policy `sandbox allow-scripts`, scripts and styles inline only, `data:` and
   `blob:` resources, and no network: no fetch, no script, style, image or
   font from any address. The client shows it in a frame with the `sandbox`
   attribute set to `allow-scripts` alone. A page is therefore one
   self-contained file.
4. **Passive rendering for SVG and diagrams:** an image element runs no
   scripts, so SVG files and drawn Mermaid diagrams are shown as images.
   Mermaid draws in the client with its strict security level.
5. **The assistant is told** to make web pages as single self-contained HTML
   files, with no network, and diagrams as Mermaid in `.mmd` files, and to
   show what it made with `offer_download`.

## Consequences

- No new storage, tools or contracts beyond the file endpoint's `page`
  parameter; artifacts get the workspace's privacy, quota, forks and
  deletion.
- An earlier answer's card shows the file as it is now.
- A page cannot use libraries from the network; the assistant inlines what it
  needs. A bundled set of libraries served alongside pages can come later.
- A page can still navigate its own frame to another address, carrying data
  it holds; no browser control prevents it, with a separate domain either.
  This is a residual risk in the threat model, bounded by the lethal
  trifecta mitigation (AGT-004).
- The isolation relies on the browser's sandbox and policy enforcement; a
  separate domain would also hold against a browser bug in them, and would
  give pages their own process in every browser.

## Alternatives considered

- **Artifacts as versioned database objects (ADR-0038):** two more tables,
  artifact tools and version views, for a history that is rarely needed.
- **A separate domain for pages (ADR-0038):** stronger, but a second domain,
  certificate and proxy entry for every household; a deployment that wants it
  can be offered it later as an option.
- **A separate port on the same host:** a different origin, but the same
  site: cookies do not distinguish ports, so it adds setup without the
  isolation a separate domain gives.
- **Showing web pages as source only:** safe, but the user cannot use what
  the assistant made.
