# ADR-0050: The API process, its configuration and how tests reach it

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0007, ADR-0008, ADR-0028, ADR-0045, ADR-0047, AUTH-006, OPS-001, OPS-003, TEN-005

## Context

The first endpoints of the public API are about to be implemented. Tests are
written before the implementation, by authors who do not read it
(ADR-0045), so they need a fixed way to start the server and call it. The
deployment needs to know how the server is configured (OPS-001). Rate limits
per source address (AUTH-006, ADR-0047) need the client's address, which is
hidden behind the reverse proxy that publishes the single entry point
(OPS-003).

## Decision

1. **Entry point.** The API runs as `python -m mazzamurello_server api`, an
   ASGI application served by Uvicorn. The worker gets its own subcommand
   when it is implemented.
2. **Configuration from the environment.** The server reads its
   configuration only from `MZM_*` environment variables, listed in the
   [configuration contract](../contracts/configuration.md). The deployment
   sets them in the Compose file or an env file, which is the documented
   configuration file of OPS-001. A missing or invalid value, or an `MZM_*`
   variable the contract does not list, stops the process before it listens,
   with a message naming the variable.
3. **Source address.** The source address of a request is the connecting
   peer's address. When the peer is a trusted proxy, listed in
   `MZM_TRUSTED_PROXIES`, it is the rightmost address of `X-Forwarded-For`
   that is not itself a trusted proxy. Without trusted proxies the header is
   ignored, so clients cannot choose their own address.
4. **Tests reach the server as a black box.** The test harness starts the
   real process with its entry point and environment, waits until it
   answers, and calls it over HTTP ([test harness](../contracts/test-harness.md)).
   Tests depend on no Python name inside the server.

## Consequences

- Tests exercise the same process, configuration and HTTP stack as the
  deployment, including connection pooling (TEN-005).
- Starting a process costs a second or two per test session.
- Tests can send requests from many source addresses by declaring the
  loopback address a trusted proxy and setting `X-Forwarded-For`.
- Typos in variable names fail loudly instead of being ignored.

## Alternatives considered

- **Calling the ASGI application in process:** faster, but tests would import
  an application factory from the implementation and miss the server, the
  real connection handling and the configuration.
- **A TOML configuration file:** more structure, but one more format to
  document, validate and mount into containers, for a handful of settings.
- **Always trusting `X-Forwarded-For`:** any client could pick its source
  address and escape the per-address rate limit.
