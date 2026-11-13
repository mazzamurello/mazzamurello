# ADR-0069: Connections of a household

- **Status:** Accepted
- **Date:** 2026-11-03
- **Deciders:** @tapionx
- **Related:** ADR-0011, ADR-0042, ADR-0051, ADR-0057, ADR-0061, ADR-0064, ADR-0066, MOD-002, MOD-005, MOD-006, MOD-008, MOD-009, MOD-010, MOD-011, MOD-012, MOD-013, MOD-014, UX-015, UX-016, T-27, T-31

## Context

ADR-0051 configures models one at a time, in two scopes: instance models,
managed by the instance admin, and tenant models, managed by a tenant admin.
Using the web client, the maintainer found three problems:

- **Two scopes confuse.** Settings showed "models for the whole instance" next
  to "models for your household". The instance admin is the household's
  admin too; nobody needs models that belong to no household.
- **One model at a time does not fit OpenRouter.** It offers hundreds of
  models behind one key. Adding them one by one, each with the same address
  and key, is busywork, and the model is chosen by the admin, not by the
  person asking.
- **Errors are opaque.** When a configuration did not work, the only signal
  was a failed run.

Instance models existed for a reason: the model gateway connects from the
control plane, so an address chosen by a tenant admin must not reach the
household's network (MOD-009, ADR-0061). Only the trusted instance admin
could configure a local server. Remote MCP servers face the same question,
and ADR-0064 answered it with a rule about the person, not the scope: private
addresses only when the tenant admin is also the instance admin.

## Decision

1. **Models belong to households.** The instance has no models. A tenant admin
   manages their household's **connections**; this supersedes ADR-0051's
   two scopes and its configurations of one model each.
2. **A connection reaches one provider and offers all its models.** It has a
   name and a kind:
   - `openrouter`: OpenRouter, with an API key. Its address is
     `https://openrouter.ai/api/v1`; the API accepts another one, for tests
     and proxies (ADR-0057), and clients do not ask for it.
   - `openai`: a server with an OpenAI-compatible API, such as Ollama,
     llama.cpp, vLLM or LM Studio, with an address and an optional API key.

   A connection states where inference runs (ADR-0066): an `openrouter`
   connection is always `remote`, and the admin says it for an `openai` one.
   API keys stay write-only and encrypted, as ADR-0051 point 3 decided
   (MOD-002).
3. **Models are discovered, not entered.** The server reads a connection's
   models from its API (`GET {address}/models`) when the connection is saved
   or tested, and again when its list is more than a day old, and keeps the
   list in the database, so that clients get every model of the household in
   one request. From OpenRouter it takes every model that answers with text,
   most used first by the tokens they processed in the past week
   (`sort=top-weekly`), with their prices, context windows and whether they
   can call tools (`supported_parameters`). From other servers it takes every
   model, in the order they are listed; an Ollama server also says, for each
   model, whether it can call tools.
4. **Models that cannot call tools still chat.** Tools are how the assistant
   searches, reads and writes files and runs commands, and most models
   support them: 389 of the 454 text models OpenRouter listed on
   2026-11-03, the others being mostly made for one task, such as
   translation, images or moderation. A run with a model known not to call
   tools runs without tools: the assistant answers from the conversation
   alone, and clients say so before and while it is used (MOD-014). A model
   whose support is unknown is given tools; if its server refuses them, the
   run fails with that reason rather than quietly dropping them.
5. **The person asking chooses the model.** A model is named by its connection
   and the provider's name for it. The tenant admin chooses the household's
   **default model**; a new conversation starts with it, and any user can
   choose another model of the household for a conversation, which applies
   from its next run. When a conversation's model is no longer offered, its
   runs fail with `model.unavailable` instead of quietly using another model,
   which could send local data to a remote provider (MOD-010). A household
   is never left without a default once it has a working connection: when a
   connection is added or tested and the household has none, the default
   becomes OpenRouter's most used free model that can call tools, which costs
   nothing until an admin chooses, or else the first model a server lists.
6. **Private addresses follow the person, as for MCP servers.** A connection
   may use a private address, or plain `http`, only when its address was set
   by a user who is the instance admin as well as a tenant admin; the
   connection records it. Every other address is checked at connection time,
   requires `https` and never follows redirects, as ADR-0061 decided. A
   change of address by any other admin clears the record. This replaces
   ADR-0061 point 5, which allowed any address for instance models.
7. **Connections are tested, step by step.** The server tests a connection
   before saving a new address or key, and whenever an admin asks, saved or
   not. The test follows the steps of a request: find the address, connect,
   secure the connection (for `https`), check the key (OpenRouter's
   `GET /key`), list the models. It reports each step with its outcome,
   duration and a short detail, and a failure with a reason from a fixed list
   (MOD-013), the HTTP status when there is one, and a technical detail. A
   failed test refuses the save. The test obeys the same address rules as
   requests and reports a refused address as such, without connecting.
   Details never contain the key, and quote at most 500 characters of a
   response.
8. **Prices come from the providers.** Admins no longer enter prices.
   OpenRouter lists its prices and reports the cost of each request
   (ADR-0057); a `local` connection costs nothing; for other remote servers
   the catalog applies (ADR-0042), and a price that is unknown is shown as
   such.
9. **No conversion of model configurations.** Sibillo has not been
   released, so the schema is rewritten rather than migrated (ADR-0071).

## Consequences

- One place to configure models, in the household's settings, and one rule
  for addresses, shared with remote MCP servers.
- A household admin who is not the instance admin still cannot use a server
  on the household's network, as before.
- The model picker can hold hundreds of models; clients let users search
  them, and OpenRouter's order puts the common ones first.
- The model list can be up to a day old; saving or testing a connection
  refreshes it at once.
- Admins see why a connection fails before anyone's run does.
- The contract changes: the `/instance/models` and `/tenant/models` endpoints
  are replaced by connections and a household model list.

## Alternatives considered

- **Keep instance models:** two places to look, for a distinction no household
  needs; the person-based rule of ADR-0064 protects the network as well.
- **Keep one configuration per model:** hundreds of identical entries for
  OpenRouter, and the admin would choose for everyone.
- **Offer only models that can call tools:** simpler, but it hides models a
  household may want for plain conversation, such as a small local model
  that fits its graphics card.
- **Read the model list on every request:** always fresh, but slow for
  OpenRouter's catalog and a request to the provider each time someone opens
  the picker.
- **Save a connection that fails its test, with a warning:** a broken
  connection would offer no models and fail every run that chose it; a server
  that is down can be added once it is up.
