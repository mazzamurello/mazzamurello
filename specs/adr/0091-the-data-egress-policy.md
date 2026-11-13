# ADR-0091: The data egress policy

- **Status:** Proposed
- **Date:** 2026-11-13
- **Deciders:** @tapionx
- **Related:** ADR-0017, ADR-0066, ADR-0069, ADR-0088, MOD-003, MOD-010, MOD-012, MOD-016, API-006, UX-024

## Context

ADR-0017 promised a data egress policy "per tenant, user and shared space",
with at least a "local models only" setting, and ADR-0066 made every
connection state where its inference runs, so that the policy has something
to decide on. What the policy holds, who sets it, which requests it covers
and what a user sees when it refuses were left open.

Shared spaces do not exist yet: a policy for them cannot be built or tested
before them.

## Decision

1. **Two policies for now:** `any`, which allows every model, and
   `local_only`, which allows only models of connections whose inference runs
   locally (MOD-010). Later policies, such as allowing some providers only,
   extend the same list.
2. **Three settings, and the strictest wins.** A tenant admin sets the
   household's policy and a policy for each user; each user sets their own.
   The policy that applies to a user, their *effective* policy, is the
   strictest of the three. Nobody loosens what someone else set: a user can
   only choose `local_only` for themself, and a tenant admin cannot see or
   change a user's own choice. Without any setting the policy is `any`, as
   today.
3. **Checked before every request.** The model gateway checks the user's
   effective policy just before each model request it makes for them: a run's
   model calls, a title, a compaction, a transcription and speech (MOD-006
   lists these purposes). A change applies from the next request, also in a
   run already going. A request the policy refuses is not sent and fails with
   `model.egress_refused`; when the policy cannot be read, the request is
   refused too.
4. **No silent switch to another model.** As when a model is no longer
   offered (MOD-012), a conversation whose model the policy refuses fails
   instead of using another model: the user chooses a local one. A new
   conversation treats a refused default model as not offered: it starts with
   the tenant's default model if the user's default is refused, and without a
   model if both are, so that the user chooses one.
5. **Refused models stay listed, marked.** `GET /models` keeps listing every
   model and adds the user's policies, so that clients can show remote models
   as unavailable and say why, instead of making them disappear.
6. **Speech too.** The household's speech models follow the same check; for a
   user whose policy refuses them, spoken turns and reading aloud are
   unavailable.
7. **Shared spaces later.** The policy of a shared space is a requirement of
   its own (MOD-016), built with shared spaces (TEN-007): a request carrying a
   shared space's data will follow the strictest of the space's and the
   user's policies.

What the policy does not cover: tools that reach the internet, such as web
search and reading pages, send queries and fetch pages but are not model
requests. Tool permissions govern them (AGT-002): a household that wants
nothing to leave sets those tools to denied.

## Consequences

- "Local models only" is one switch for the household, for a member, or for
  oneself, and is enforced at the one place every model request passes.
- A conversation with a remote model stops working for a user who switches
  to local models only, until they choose another model; the client says so.
- The policy is only as right as the location an admin gave each connection
  (ADR-0066).
- Policy changes are not audit events: they are settings, visible where they
  are set.

## Alternatives considered

- **Hiding refused models:** simpler for clients, but models would vanish
  without a reason, and an admin choosing the household's default would see a
  different list from a member.
- **Falling back to a local model:** keeps a conversation going, but changes
  its model behind the user's back, which MOD-012 already rejects.
- **A per-conversation switch standing in for shared spaces:** a fourth
  setting to explain, for a need shared spaces will meet.
- **Checking only when a run starts:** a long run would keep sending data to
  a remote model after the user, or their admin, said no.
