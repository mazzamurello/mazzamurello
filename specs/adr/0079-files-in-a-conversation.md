# ADR-0079: Files in a conversation

- **Status:** Accepted
- **Date:** 2026-11-07
- **Deciders:** @tapionx
- **Related:** ADR-0022, ADR-0067, ADR-0076, ADR-0078, CNV-005, CNV-012, CNV-017, SBX-010, SBX-014, SBX-019, UX-019, UX-020, AGT-023, TEN-008

## Context

Each conversation has a workspace, `/workspace` in its sandbox (ADR-0078).
The assistant can reach files only by fetching them itself, and the user can
see what it made only in its answers. People want to hand it a PDF, a photo
or a spreadsheet from their phone or computer, see what is in the workspace,
and take files home.

Workspace files are untrusted: the assistant may have made them from web
content. A file served as a page of the app's origin could run with the
user's session (T-22).

Sharing files between conversations, through a file library (CNV-012) or
folders as projects, is a separate decision, deliberately left for later.

## Decision

1. **The workspace panel** (UX-019). A conversation's workspace is browsable
   as a tree, beside the conversation on a computer and as a full-screen
   sheet on a phone. Folders load their contents when opened; every entry
   shows its size and when it changed; hidden files are behind a toggle; the
   panel shows the workspace's size against its quota (SBX-019) and refreshes
   when an answer ends.
2. **What the panel does:** preview, download (a folder as a `.zip`),
   upload into a folder, create a folder, rename and move, delete, and reset
   the whole workspace. Deleting and resetting ask first.
3. **Previews, never as the app** (UX-020): text, code, JSON and logs as
   text (the first megabyte); Markdown rendered as answers are; CSV as a
   table of its first rows; PNG, JPEG, GIF, WebP and SVG as images, so that
   nothing in an SVG runs; PDF in the browser's own viewer; audio and video in
   the browser's player; HTML as its source. Other files show their name,
   size and a download button. The API serves a file for preview only with
   one of these types and `X-Content-Type-Options: nosniff`, and for download
   as an attachment. Every file comes with a Content Security Policy of its
   own, `sandbox` with no scripts, so that one opened by itself, as from a link
   in an answer, runs nothing in the app's origin; a PDF, which the browser's
   viewer does not open sandboxed, gets a policy that allows only the PDF
   itself. The client shows images, PDF, audio and video from the preview
   address, and text from its content, under the app's Content Security
   Policy (ADR-0067).
4. **Attachments** (CNV-017). A file picked or dropped in the message box,
   or taken with the phone's camera, uploads at once into
   `/workspace/uploads/`, with progress in the message box; a name already
   taken gets a number, as `budget (2).csv`, and nothing is overwritten.
   Removing it before sending deletes it. The message sent lists its
   attachments; the model reads that list as part of the user's message,
   with each file's path and size, and the history shows them as chips that
   open the panel.
5. **Offering a file** (AGT-023). The agent's `offer_download` tool names one
   file of the workspace; the answer shows a card with its name, its size and
   a download button. A browser does not download without the user's tap, so
   the card never downloads by itself. It points at the workspace as it is:
   later it downloads the file's current content, or says it is gone.
6. **Limits.** One upload is at most `MZM_UPLOAD_MAX_MB`, 1024 by default,
   and an upload that would take the workspace over its quota is refused.
   Uploads stream from the client through the API and the driver into the
   sandbox, held in memory by none; they are written under a temporary name,
   renamed when complete, and removed when interrupted.
7. **Through the driver only** (SBX-014). The API asks the sandbox driver to
   list, read, write, move and delete; the driver works on the
   conversation's workspace only, refuses paths outside it (absolute paths,
   `..` segments, links leading out), and never follows a link to read or
   write. Operations made outside an answer start the conversation's sandbox
   for the operation and remove it after, so none is left running (SBX-018).
8. **Private to the conversation's owner** (TEN-008): only they reach its
   workspace, through the conversation's row-level security.

## Consequences

- The assistant works on the user's own files, and the user sees and
  manages everything it kept, from any device.
- Every file operation outside an answer starts a sandbox for a moment, about
  a third of a second.
- A household behind a reverse proxy must let uploads of
  `MZM_UPLOAD_MAX_MB` through, nginx's default being 1 MB; the README says so.
- A 1 GB upload fits a 2 GB workspace once; the instance admin can raise the
  quota.

## Alternatives considered

- **Attachments in a file library, outside the workspace** (CNV-012 as it
  was written): a bridge between conversations, which ADR-0078 removed on
  purpose; it comes back as an explicit decision of its own.
- **An offered file copied at the moment it is offered:** the card would
  always give what the assistant offered, at the cost of a second copy outside
  the workspace and its quota.
- **Rendering HTML and other active content in the panel:** that is the
  artifacts' isolated rendering (ART-003), not this milestone.
- **Uploading when the message is sent:** sending would wait for large files.
