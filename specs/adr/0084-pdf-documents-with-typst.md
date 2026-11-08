# ADR-0084: PDF documents with Typst

- **Status:** Accepted
- **Date:** 2026-11-08
- **Deciders:** @tapionx
- **Related:** ADR-0053, ADR-0076, ADR-0080, SBX-021

## Context

ADR-0080 put pandoc in the sandbox to make documents, but pandoc writes a PDF
only through a typesetting engine, and the image has none. Asked for a PDF,
the assistant drew one with matplotlib instead, page by page, without
headings, lists or tables that flow.

The engines pandoc 3.1.11, Debian's, can use:

- **LaTeX:** the classic, from hundreds of megabytes to more than a gigabyte
  with the fonts and packages documents need, and slow under gVisor.
- **WeasyPrint:** HTML and CSS to PDF, packaged by Debian, with about 90
  packages.
- **Typst:** one static program of about 40 MB, from Typst's own release;
  Debian does not package it. It typesets in a fraction of a second and
  embeds its own fonts for text and mathematics.

Pandoc's Typst template passes an empty font list unless a font is named,
which Typst 0.15 refuses: `pandoc --pdf-engine=typst` fails as installed.

## Decision

1. **Typst is the sandbox's PDF engine:** its release for the image's
   architecture, pinned by version and checked against the release's SHA-256,
   installed as `/usr/local/bin/typst`.
2. **A plain command works:** the image gives pandoc's Typst template a
   default font list, Libertinus Serif, which Typst embeds, then DejaVu Sans
   and Noto Sans, so that `pandoc in.md -o out.pdf --pdf-engine=typst` makes
   a typeset PDF without naming a font. The build fails if the template no
   longer has the line it changes.
3. **The agent is told how:** its instructions name Typst and the pandoc
   command for a PDF, and say that `typst compile` takes Typst documents
   directly.

## Consequences

- Documents, reports and letters come out as typeset PDFs, with mathematics
  and tables, without installing anything.
- The image grows by about 40 MB.
- Updating Typst means a new version and checksum in the image, and checking
  pandoc's template still works with it.

## Alternatives considered

- **LaTeX:** the best known output, at many times the size and start-up time.
- **WeasyPrint:** CSS gives control over the layout, but at about 90 packages,
  and the model writes HTML instead of the Markdown it already writes.
- **Instructions only:** without an engine, they can only steer the model to
  drawing pages with matplotlib.
