# ADR-0007: Server-only, containerized deployment; one instance per household

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** OPS-001, OPS-002, OPS-003, OPS-004, TEN-001

## Context

Several personal assistant projects are designed to run on the user's own
workstation and to execute commands directly on the host. That model is
incompatible with strong isolation, with multiple users, and with an
always-on assistant reachable from phones.

The reference model for this project is self-hosted household software such
as Immich or Home Assistant: one installation per home, on a server, used by
the whole family.

## Decision

We will:

1. Run Mazzamurello **only as containers on a Linux server**, deployed with
   Docker Compose. Kubernetes support may follow for operators who need it.
2. Support Linux on x86_64 and arm64 with Docker Engine. Other environments
   (Docker Desktop on macOS or Windows, NAS platforms without the required
   runtime) are unsupported, and the system detects and reports them.
3. **Never execute anything on the host on behalf of users.** All user and
   agent code runs in sandboxes (ADR-0010).
4. Target **one instance per household**, with a data model that is
   multi-tenant from the start (ADR-0009), so that the same software can
   serve several households or a small organization.

## Consequences

- No desktop installer; clients are web and mobile (ADR-0016).
- The requirement for an isolation runtime narrows the supported platforms.
- Operators who host for others get the same isolation guarantees as a
  single family.

## Alternatives considered

- **Workstation install with host execution:** contrary to the security
  model.
- **Single-user design, multi-tenancy later:** retrofitting tenant isolation
  into a data model is expensive and error-prone; user isolation is needed
  inside a family anyway.
