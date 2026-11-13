# ADR-0075: Web search through the instance's SearXNG, page reading in the sandbox

- **Status:** Accepted
- **Date:** 2026-11-05
- **Deciders:** @tapionx
- **Related:** ADR-0035, ADR-0043, ADR-0053, ADR-0072, ADR-0074, AGT-003, AGT-013, AGT-014, AGT-020, AGT-021, SBX-005, SBX-006, SBX-008, OBS-001

## Context

ADR-0074 keeps web search and page reading out of the model provider's
hands: the system runs them itself, with no keys. Two questions remain:
which search engine, and where each tool runs.

No search engine offers free automated searches without a key. The free
options all read the result pages of public search engines, which limit
and block automated queries and change their pages. SearXNG is a
self-hosted metasearch engine, AGPL-3.0 like Sibillo, built for
privacy: it sends no cookies to the engines, uses a new browser profile
for every request, sets no referrer, and pauses an engine that blocks it.
It queries several engines at once, and its community keeps their parsers
up to date. It has no numbered releases: its images are tagged by date.

A sandbox reaches public addresses only: every local address and every
other container is blocked (SBX-005, SBX-006). SearXNG in each sandbox
would cost hundreds of megabytes per active user; opening the sandbox
network to a SearXNG container would be the first exception to sandbox
isolation.

## Decision

1. **SearXNG is a service of the instance**, `search` in the Compose
   deployment, from its official image pinned by date tag and digest. It
   is on its own network, `search`, shared with the worker only: not with
   the API, the database, the sandbox driver or the sandboxes. It holds no
   credentials of the system and no user data; the only secret it has is
   its own, which it generates at start for its pages.
2. **Its settings are the system's**, bundled in the image of the
   deployment:
   - its JSON format is the only one served;
   - its general engines are SearXNG's defaults, plus Google, which
     SearXNG ships disabled; the instance admin can change them;
   - its limiter, its image proxy and its statistics are off, and it logs
     no queries (OBS-001);
   - it never fetches an address taken from a request: it only queries
     the engines its settings name.
3. **Web search runs in the worker** (AGT-020): the `web_search` tool sends
   the model's query to SearXNG's JSON API at its address on the `search`
   network, the only address the tool uses, and returns the results' titles,
   addresses and excerpts. The worker never fetches a result's address.
   This is the one capability that reaches the web from the control plane
   (AGT-013): what leaves is a query string, to a service of the instance,
   and SearXNG alone talks to the engines.
4. **Page reading runs in the sandbox** (AGT-021): the `read_page` tool runs
   a reader command of the sandbox image in the user's sandbox, through the
   driver, as the shell tool runs commands (ADR-0035). The reader fetches
   one `http` or `https` address under the sandbox's egress rules, keeps
   the page's main text with Trafilatura (Apache-2.0), pinned in the image,
   and returns it as Markdown with the page's title and final address.
5. **Both results are untrusted content** (AGT-003): they reach the model as
   tool results, bounded like other tool output (AGT-014), each starting
   with a line that says where it comes from and that it is data, not
   instructions.
6. **Failures are tool errors, not run failures.** When SearXNG does not
   answer, or a page cannot be read, the tool tells the model why, and the
   run goes on.
7. **Declared destinations** (ADR-0072): the worker's only new destination
   is SearXNG, a component of the instance; SearXNG's own destinations are
   the engines its settings enable.
8. **Tests** never reach a real search engine: the test harness serves
   SearXNG's JSON API with scripted results, and the reader's tests serve
   pages from inside the sandbox, on its own loopback address.

## Consequences

- Every model, local or remote, searches the same way, through engines the
  household can see and change, and no search costs money.
- One more container, with its own memory (a few hundred megabytes) and an
  image to keep current: its date tag is raised like any other pinned
  version.
- Results are as good as the engines SearXNG can query without a key, and
  get worse while an engine blocks the instance's address.
- Sandbox isolation is unchanged; the worker's exposure is one fixed
  address that takes a query string.
- Reading pages that need JavaScript, and browser automation, come later
  (phase 3).

## Alternatives considered

- **The search tool in the sandbox, reaching SearXNG through an exception
  to the sandbox network:** keeps every web request in the sandbox, but
  weakens SBX-005 and SBX-006, and a compromised sandbox could attack
  SearXNG.
- **SearXNG in every sandbox:** no network exception, but a few hundred
  megabytes per active user, slow starts, and a bigger sandbox image.
- **Our own reader of one free search engine's pages:** no new container,
  but a single engine, blocked as easily, with a parser to maintain alone.
- **A search API with a key** (Brave, Mojeek): better results, but costs
  money and needs a credential outside the sandbox; a later decision.
