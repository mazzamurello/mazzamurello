# ADR-0054: The Compose deployment

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0007, ADR-0018, ADR-0021, ADR-0022, ADR-0050, ADR-0053, AUTH-007, OPS-001, OPS-002, OPS-003, OPS-009

## Context

Phase 0 ends when a fresh Linux host goes from `git clone` to a working
conversation by following the README. The components exist; what is missing
is how they are deployed together (OPS-001), what is exposed (OPS-003), how
the operator creates the secrets and the first administrator without any
default credentials (AUTH-007), and how unsupported platforms are reported
(OPS-002).

## Decision

1. **One Compose file**, `deploy/compose.yaml`, with these services, all
   built from the repository's `deploy/images/` until signed images are
   published (ADR-0018):

   | Service | Runs | Reachable from |
   |---|---|---|
   | `postgres` | PostgreSQL 17, with the database contract's initialization | internal network |
   | `migrate` | the migration command, once, as `mzm_owner` | — |
   | `api` | the API | the single published port |
   | `worker` | the worker | — |
   | `sandboxd` | the sandbox driver, the only service with the Docker socket | internal network |
   | `netguard` | the network guard, host networking and `NET_ADMIN`, container `mazzamurello-netguard` | — |
   | `sandbox` | builds the sandbox image, then exits | — |
   | `init`, `setup` | the operator's one-time commands | — |

2. **One published port.** Only `api` publishes a port, by default
   `127.0.0.1:8080`, changed with `MZM_PUBLISH` in the `.env` file. HTTPS is
   the job of the reverse proxy the household already runs, declared in
   `MZM_TRUSTED_PROXIES` (ADR-0050). A bundled proxy may come with the web
   client.
3. **Secrets are generated, never shipped.**
   `docker compose run --rm --no-deps init` writes `deploy/.env` with random
   database passwords, `MZM_SECRET_KEY` and the driver's token, and refuses to
   overwrite an existing file. Every service reads its configuration from
   that file; a missing value stops the service with an error naming it.
4. **The first administrator** is created by
   `docker compose run --rm setup`, which runs
   `python -m mazzamurello_server setup` as `mzm_owner`. It asks for the
   tenant's name, the username, the display name and the password (twice,
   hidden; read from standard input when it is not a terminal), and calls
   `bootstrap_instance`. It refuses when any user exists (AUTH-007).
5. **Platform checks** (OPS-002). The sandbox driver adds a `platform` check:
   Docker must run on Linux, on `x86_64` or `aarch64`. Neither hardware
   virtualization nor `/dev/kvm` is needed: gVisor uses its `systrap`
   platform (OPS-009). The API's `/health` reports `unavailable` when the
   database is unreachable or sandboxes are refused, and `degraded` when no
   default model is configured; instance admins also see each check.
6. **The end-to-end test** follows the README on a fresh copy of the
   deployment, as described in the [test harness](../contracts/test-harness.md),
   locally and in CI.

## Consequences

- The README is the installation guide, and the end-to-end test keeps it
  honest.
- Building the images on the host takes several minutes on first install.
- The network guard's container name is fixed, so one host runs one
  deployment.
- A household without a reverse proxy uses plain HTTP on the published port,
  which is acceptable only on a trusted network; the README says so.

## Alternatives considered

- **A bundled Caddy with automatic HTTPS:** HTTPS out of the box, but one more
  component to configure and keep current before any client needs it.
- **Secrets written by hand from a list in the README:** no command to
  maintain, but easy to get wrong, and tempting to copy example values.
- **Migrations run by the API at startup:** one service fewer, but the API
  would need the owner's credentials, which TEN-004 keeps out of running
  services.
