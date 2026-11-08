# ADR-0080: The sandbox toolbox

- **Status:** Accepted
- **Date:** 2026-11-07
- **Deciders:** @tapionx
- **Related:** ADR-0022, ADR-0023, ADR-0053, ADR-0075, ADR-0076, ADR-0079, SBX-021, AGT-011

## Context

ADR-0022 promised a capable sandbox image, with common tools for documents,
media and data; ADR-0023 measured that they work under gVisor. The image
still holds only a shell, Python and git. Since files can be attached to a
message (ADR-0079), people hand the assistant PDFs, spreadsheets and photos,
and it has nothing to read them with: it printed a PDF with `cat`, and
anything it installs is gone when the answer ends (ADR-0076), so it would
install the same packages for every answer.

Every megabyte of the image is disk on the household's server and time in
every CI job that loads it (ADR-0059). A sandbox starts as fast whatever the
image's size.

## Decision

We will build these tools into the sandbox image, from Debian's packages
unless said otherwise:

1. **Documents:** poppler's tools (`pdftotext`, `pdftoppm`, `pdfinfo` and the
   rest), `qpdf`, `pandoc`, and fonts for documents: DejaVu, Liberation
   (metric-compatible with Arial, Times and Courier) and Noto's core.
2. **Office files** through Python libraries: python-docx, openpyxl and
   python-pptx read and write them; there is no office suite.
3. **Reading for the model:** markitdown turns PDF, Word, Excel, PowerPoint
   and HTML files into Markdown.
4. **Images and media:** ImageMagick and ffmpeg.
5. **Data:** pandas, numpy, matplotlib, Pillow and pypdf in Python; `jq`,
   `sqlite3`, `file`, `zip` and `unzip`.
6. **Node.js** with npm, for scripts and tools written in JavaScript; npm
   from its own release, checked against the registry's hash, since Debian's
   brings hundreds of packages for it.
7. **One Python for the user's work.** The Python libraries live in one
   environment, `/opt/tools`, first on the `PATH`, so that `python3` and `pip`
   are that environment's; its dependencies are pinned by hash and installed
   from wheels only, as the page reader's are (ADR-0075), and the page reader
   keeps its own environment.
8. **Nothing a sandbox does not use:** no package documentation, no test
   suites of the Python libraries, and none of the GPU drivers that Debian's
   ffmpeg depends on but loads only when there is a GPU, which a sandbox
   lacks.
9. **The agent knows its tools.** Its instructions list what is there, so
   that it reaches for them before installing anything, and installs only
   what is missing, knowing it lasts for one answer.

We leave out an office suite (LibreOffice, about 500 MB), so office files are
not converted to PDF with their layout, and text recognition (Tesseract), so
scanned documents are read only by a model that sees images. Both can be
installed in a sandbox for one answer, and either can join the image later.

## Consequences

- The assistant reads and makes the files a household uses without
  installing anything, and its answers come sooner.
- The image grows from about 0.3 GB to about 1.3 GB, which every CI job that
  loads it pays for; pandoc and the Python environment are most of it.
- Updating a tool means rebuilding the image; the Python environment's pins
  are refreshed like the page reader's.

## Alternatives considered

- **Installing tools when needed, in each sandbox:** slow for every answer,
  and it needs the network each time (ADR-0076).
- **LibreOffice for office files:** faithful conversion, at about 500 MB and a
  slow start under gVisor.
- **Tesseract for scans:** about 60 MB with two languages, for a need that
  models reading images increasingly cover.
- **Separate images for different kinds of work:** the driver runs one image
  (ADR-0022), and a conversation does not know in advance what it will need.
