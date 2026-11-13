# ADR-0064: Remote MCP servers of a household

- **Status:** Proposed
- **Date:** 2026-11-02
- **Deciders:** @tapionx
- **Related:** ADR-0011, ADR-0020, ADR-0051, ADR-0061, AGT-003, AGT-013, AGT-018, AGT-019, MOD-002

## Context

Services such as error trackers and home automation publish MCP servers over
HTTP. Connecting Sibillo to them gives the assistant their tools without
writing a connector for each. AGT-013 keeps MCP servers out of the control
plane, because a program started there, or a connection to an arbitrary
address, could reach the host and the household's network (T-21). Calling a
remote endpoint as a client, at a checked address, does neither.

## Decision

1. **Remote servers over HTTP only.** Sibillo is an MCP client of
   servers reached over HTTP. It never starts MCP programs.
2. **They belong to a tenant,** added by its tenant admin, and are available
   to every user of the tenant. There is nothing to configure per user and no
   server shared between tenants.
3. **One credential per server,** such as a token, entered by the tenant
   admin, stored encrypted like a model's API key and never returned (MOD-002).
4. **Where a server may be,** decided by who adds it: a tenant admin who is
   also the instance admin, trusted (ADR-0011), may use any address, such as
   Home Assistant on the household's network or a container next to
   Sibillo; any other tenant admin only public `https` addresses, checked
   at connection time as for tenant models (ADR-0061).
5. **Every call is approved** with a button (AGT-018). MCP's tool annotations,
   such as `readOnlyHint`, are hints from the server and grant nothing.
6. **Everything from a server is untrusted content:** its tool descriptions as
   much as its results (AGT-003), since a server can carry injected
   instructions in either (T-29).

## Consequences

- The assistant reaches the household's services with the tools their
  makers publish.
- A server's credential gives every user of the tenant the same access to
  that service; services where each person has an account wait for personal
  credentials.
- AGT-013 gains its one exception.

## Alternatives considered

- **Personal servers added by each user:** useful, but each user could connect
  a careless or malicious server; deferred, with per-user credentials and
  OAuth sign-in, to a later phase.
- **Running MCP programs in isolated containers:** reaches tools that have no
  remote server, but adds a third kind of container and its policy; not
  needed yet.
- **A setting letting tenant admins allow personal servers:** another option
  to get wrong; one fixed behavior first.
