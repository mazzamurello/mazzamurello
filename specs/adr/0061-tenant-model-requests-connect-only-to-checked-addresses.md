# ADR-0061: Tenant model requests connect only to checked addresses

- **Status:** Accepted
- **Date:** 2026-11-02
- **Deciders:** @tapionx
- **Related:** ADR-0017, ADR-0051, MOD-009, T-27

## Context

ADR-0051 lets a tenant admin configure model endpoints, and restricts them to
`https` and public addresses, checked when the endpoint is saved and again
before every request. A review of phase 0 found two ways around the check:

- **DNS rebinding.** The check resolves the endpoint's host name, and the HTTP
  client resolves it again when it connects. A name that answers with a
  public address the first time and a private one the second passes the
  check and reaches the household's network.
- **Redirects.** The OpenAI client follows redirects by default, so a public
  endpoint that answers `302` with a private address leads the control plane
  there, with no DNS trick at all.

## Decision

1. **The check happens at connection time.** Requests for tenant models go
   through an HTTP transport that resolves the host name itself, requires
   every address it returns to be public, and connects to one of those
   addresses. The request keeps its host name for TLS, so the certificate is
   still verified against the endpoint's name.
2. **Redirects are not followed** for tenant models. A redirect fails the
   model request.
3. **Public** means a global unicast address: IPv4-mapped IPv6 addresses are
   judged as the IPv4 address they carry, and the NAT64 prefix `64:ff9b::/96`
   is not public, since a NAT64 gateway can map it to a private address.
4. The check when the endpoint is saved stays, so that an admin hears at once
   that an endpoint cannot be used; the same definition of public applies.
5. Instance models, configured by the trusted instance admin, may still use
   any address, such as a local server on the household's network.

## Consequences

- A tenant's endpoint behind a CDN still works: it connects to one of the
  public addresses its name resolves to.
- Tests check the transport directly, with an injected resolver and policy,
  since no test can serve a model on a public address.

## Alternatives considered

- **An egress proxy for the control plane:** stronger, and needed later for
  connectors, but a component to deploy before phase 1 needs it.
- **Network rules for the API and worker containers:** they would need to
  allow the household's local model servers for instance models, which is the
  traffic tenant models must not reach.
