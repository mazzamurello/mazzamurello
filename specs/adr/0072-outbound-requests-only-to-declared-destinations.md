# ADR-0072: Outbound requests only to declared destinations

- **Status:** Accepted
- **Date:** 2026-11-03
- **Deciders:** @tapionx
- **Related:** ADR-0014, ADR-0039, ADR-0058, ADR-0064, ADR-0067, ADR-0069, ADR-0070, AGT-013, OBS-001, OBS-006, UX-002, UX-004

## Context

A household runs Mazzamurello to keep its data at home. OBS-001 forbids
telemetry, and the web app's Content Security Policy keeps scripts to its
own origin (ADR-0067). Neither covers every way software reaches the
internet on its own:

- **Libraries fetch at run time.** The price catalog can download updated
  prices from GitHub; tokenizer libraries download their encodings on first
  use; model libraries download weights.
- **Web pages load from third parties.** Fonts from a web font service,
  scripts and styles from a CDN, icons from a sprite sheet: each request
  tells a third party who opens the app and when, and makes the app depend
  on that service being up. The design prototype itself loads its fonts
  from Google (ADR-0070).

The maintainer wants a rule, not a case-by-case judgment: the software never
fetches anything remote unless the case is explicitly allowed.

## Decision

1. **The control plane connects only to declared destinations.** Its own
   components (the database, the sandbox driver) and these external ones,
   each only for its purpose:

   | Destination | Chosen by | For |
   |---|---|---|
   | A household's connections | a tenant admin (ADR-0069) | model requests, model lists and connection tests |
   | A household's remote MCP servers | a tenant admin (ADR-0064) | tool calls, once AGT-019 is implemented |
   | Browser vendors' push services | the user's browser (ADR-0039) | content-free notifications, once UX-004 is implemented |
   | The instance's search service (ADR-0075) | the system | web search queries, once AGT-020 is implemented; the service itself queries the search engines its settings enable |

   Adding a destination needs a change of this list, in a `spec/` change.
2. **No library fetches at run time.** Data a library would download, such as
   prices, tokenizer encodings or model files, is bundled when the image is
   built or not used: the price catalog uses the data shipped with it, and
   its updater is never started. Building the images fetches packages, which
   is not run time.
3. **Sandboxes are not the control plane.** A user's sandbox reaches the
   internet because the user's assistant does the user's work there, under
   the egress policy (SBX); tools that fetch URLs or search the web run in
   the sandbox, never in the control plane (AGT-013).
4. **The web app loads everything from the instance.** Scripts, styles,
   fonts, icons and images are bundled into the app at build time and served
   by the instance; no CDN, web font service or analytics. The Content
   Security Policy allows only the app's own origin, plus `data:` and
   `blob:` where the app needs them, so a slip fails in the browser instead
   of leaking. Messages never load remote resources (UX-002).
5. **Checked by tests.** A test watches every outbound connection of the API
   and the worker while they start, sign a user in and complete a run, and
   fails on any destination not declared. A design test fails when the built
   web app references a script, style, font or image on another origin, and
   when code starts a library's downloader.
6. **Repository files that are not shipped**, such as the design prototype,
   are not part of the software, and may load what they need to be viewed.

## Consequences

- What leaves the instance is a short list that a household can read and
  check, beside what its users and admins choose to send.
- Libraries are chosen and configured with this in mind, and some features
  cost a little more image size: bundled fonts, bundled encodings.
- Prices in the catalog are as fresh as the release; OpenRouter reports its
  own costs (ADR-0057).

## Alternatives considered

- **Rely on OBS-001 and review:** it covers telemetry, not a font or a
  tokenizer download, and review misses what a dependency does at run time.
- **An egress firewall for the control plane's containers:** stronger, and
  still worth adding, but the households' connections have arbitrary
  addresses, so the firewall alone cannot express the rule; the tests catch
  mistakes earlier.
