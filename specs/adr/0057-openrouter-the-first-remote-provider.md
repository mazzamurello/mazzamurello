# ADR-0057: OpenRouter, the first remote provider

- **Status:** Accepted
- **Date:** 2026-11-01
- **Deciders:** @tapionx
- **Related:** ADR-0017, ADR-0042, ADR-0051, MOD-001, MOD-002, MOD-006, OBS-001

## Context

MOD-001 requires one local provider, which any OpenAI-compatible endpoint
covers, and one remote provider, for which it names OpenRouter. OpenRouter's
chat completions API is OpenAI-compatible, with differences that matter here:
it reports the cost of every response in its usage data, repeats the finish
reason in its final usage chunk, sends keep-alive comments while a request is
processed, and reports errors that occur mid-stream as stream events. Pydantic
AI has a model for OpenRouter that handles these and exposes the reported
cost. The gateway cannot tell OpenRouter apart by address: a test server, or
a proxy in front of OpenRouter, has another one.

## Decision

1. **Model configurations name their API.** A configuration gains `api`:
   `openai`, the default, for any OpenAI-compatible chat completions
   endpoint, such as Ollama, llama.cpp or vLLM; or `openrouter`, for
   OpenRouter's API, normally at `https://openrouter.ai/api/v1`. The gateway
   uses Pydantic AI's OpenRouter model for `openrouter`, and the generic
   OpenAI model otherwise.
2. **The reported cost comes first** (ADR-0042, ADR-0051): when a response
   reports its cost, the cost ledger records it, with `provider` as its price
   source; otherwise the configuration's prices, then the catalog. OpenRouter
   reports the cost in credits, which it sells for one US dollar each, so the
   ledger records the cost in `USD`. A configuration that is not paid per
   token still records zero.
3. **No attribution headers.** OpenRouter's optional `HTTP-Referer` and
   `X-OpenRouter-Title` headers would list the instance in OpenRouter's public
   app rankings; the gateway does not send them (OBS-001).
4. **Tests replay documented responses.** Tests never reach OpenRouter. The
   model the test suite serves can answer as OpenRouter's documentation
   describes: content and tool call deltas, keep-alive comments, a final usage
   chunk with `cost`, and errors before and during a stream. The responses are
   written from that documentation, because the project has no account to
   record real ones; they are revised when real traffic shows a difference.

## Consequences

- An admin picks the API when configuring a model; existing configurations
  are `openai`.
- The cost ledger is exact for OpenRouter models without prices to maintain.
- The tests prove the gateway handles OpenRouter as documented, not as it
  behaves today; a change on OpenRouter's side is found only by users.
- Other providers with their own APIs follow the same pattern: a new value of
  `api`, a model class, and replayed responses.

## Alternatives considered

- **Detect OpenRouter by its host name:** untestable without reaching
  OpenRouter, and wrong behind a proxy.
- **Treat OpenRouter as a plain OpenAI-compatible endpoint:** works for text,
  but loses the reported cost and mishandles mid-stream errors.
- **Record real responses:** more faithful, but needs an account and a key in
  the hands of whoever records them.
