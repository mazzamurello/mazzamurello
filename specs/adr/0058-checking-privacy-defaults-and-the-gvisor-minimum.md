# ADR-0058: Checking the privacy defaults and the gVisor minimum

- **Status:** Accepted
- **Date:** 2026-11-01
- **Deciders:** @tapionx
- **Related:** ADR-0014, ADR-0053, AUTH-001, MOD-002, OBS-001, OBS-003, SBX-017

## Context

The privacy defaults of ADR-0014 hold today because nothing logs content and
nothing sends data out, but no test would notice if a change or a dependency
broke them. SBX-017 needs the driver to refuse an older gVisor release, and a
test cannot install one without changing the host's Docker configuration.

## Decision

1. **Logs carry no secrets or content.** The test harness keeps the output of
   every process it starts: the API, the worker and the sandbox driver. A
   security test signs in with a known password, configures a model with a
   known API key, and runs a conversation whose message text, tool arguments
   and tool output contain marker strings; then it checks that none of them
   appears in any process's output, at the default log level (AUTH-001,
   MOD-002, OBS-003). There are no traces yet; when tracing arrives, its
   exporter is checked the same way.
2. **Nothing is sent out by default** (OBS-001). Design tests check that:
   - the lock file contains no package whose purpose is to send telemetry,
     error reports or traces to a service, such as `sentry-sdk`, `logfire`
     (the no-op `logfire-api` that Pydantic AI uses is allowed),
     `opentelemetry-sdk` or `opentelemetry-exporter-*`, `posthog`, `ddtrace`,
     `newrelic`, `rollbar` or `bugsnag`;
   - DBOS is configured without a conductor and without OTLP export, and
     Pydantic AI is not instrumented.

   The deny-list grows as such packages come to light.
3. **The gVisor minimum can be raised.**
   `MZM_SANDBOX_MINIMUM_GVISOR_RELEASE` lets the instance admin require a
   newer release than the minimum built into the driver, for example after a
   gVisor security fix. A value older than the built-in minimum stops the
   driver with a configuration error: the minimum can never be lowered. The
   test of SBX-017 starts a driver whose minimum is newer than the installed
   release and checks that it refuses sandboxes and says how to install a
   supported release.

## Consequences

- A log line that leaks a password, a key or a message fails CI.
- A new dependency that brings telemetry fails CI until it is reviewed and
  either removed or proven inactive.
- The refusal path of SBX-017 is tested on every machine, without an old
  gVisor release.

## Alternatives considered

- **Watch the network of the end-to-end deployment:** proves directly that
  nothing leaves, but needs a connection observer and slows CI; the design
  tests catch the likely causes first.
- **Register an old gVisor release with Docker in CI:** tests the real
  release check, but only in CI, and changes the runner's Docker setup.
