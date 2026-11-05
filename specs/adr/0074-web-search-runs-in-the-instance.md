# ADR-0074: Web search runs in the instance, not at the model provider

- **Status:** Accepted
- **Date:** 2026-11-05
- **Deciders:** @tapionx
- **Related:** ADR-0030, ADR-0035, ADR-0057, ADR-0072, AGT-003, AGT-013, AGT-014, MOD-003, SBX-004, SBX-008

## Context

The assistant needs to search the web and read pages (phase 1). AGT-013
allows two places for capabilities that reach the web: the user's sandbox,
or tools that the model provider runs itself.

Remote providers offer such tools. OpenRouter (ADR-0057), for example, runs
web search and page fetching as server tools on its side, through search
companies of its choice, for a fee per search on top of tokens. They are
easy to add, but:

- **The query leaves through a third party.** Every search goes to the
  provider and to a search company it chooses, under their retention
  policies, together with the account that made it.
- **They exist only for some models.** Models on the household's own
  server have none, so search would work differently depending on the model.
- **Their results bypass our tools.** They reach the model directly: the
  system cannot bound them (AGT-014), mark them as untrusted content
  (AGT-003) or show them as tool calls.

Privacy is the reason a household runs Mazzamurello, and the sandbox already
reaches the public internet on the user's behalf (SBX-004).

## Decision

We will run web search and page reading ourselves, in the instance:

1. **No provider-run web tools.** The system does not enable a provider's
   web search or page fetching, even where the provider and the framework
   support them.
2. **Search and reading are tools of the system,** for every model, local
   or remote. Their results are tool results like any other: bounded
   (AGT-014) and marked as untrusted content (AGT-003).
3. **No keys for search.** The search engine the system uses needs no
   account or key. A search service that needs one is a separate decision.

Where each tool runs, and which engine searches, is ADR-0075.

## Consequences

- Searches reach only the search engines the system chooses, from the
  instance's address, and every model searches the same way.
- No per-search fees from the provider.
- Search quality depends on the engines a household can query without a
  key, and the system has to handle engines that limit or block automated
  queries.
- Other provider-run tools, such as image generation or delegation to other
  models, are judged one by one; tools that run code or keep files at the
  provider are not used, because the household's files would leave the
  sandbox.

## Alternatives considered

- **Provider-run search for remote models, our own search for the others:**
  better results for remote models with little work, but it sends queries
  through third parties, and search would behave differently by model.
- **Provider-run search only:** the least work, but local models could not
  search, and every search would leave through the provider.
