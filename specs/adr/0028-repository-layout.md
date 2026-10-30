# ADR-0028: Repository layout — one uv workspace, three packages, tests and migrations at the top

- **Status:** Accepted
- **Date:** 2026-10-30
- **Deciders:** @tapionx
- **Related:** ADR-0003, ADR-0008, ADR-0021, ADR-0022, ADR-0026, REPO-001

## Context

Three components run as separate containers with very different privileges:
the server (API and worker), the sandbox driver (Docker API access) and the
network guard (host firewall). The privileged ones must stay small, with few
dependencies, so that they can be reviewed thoroughly. The pull request policy
(REPO-001) separates tests from implementation by path.

## Decision

We will use a single repository organized as a **uv workspace**:

```
pyproject.toml        workspace root: tooling configuration (ruff, pyright, pytest)
uv.lock               one lock file, with hashes
src/
  server/             API and worker: two entrypoints, one package
  sandboxd/           sandbox driver
  netguard/           network guard
migrations/           database migrations (Alembic)
tests/
  unit/  integration/  e2e/  security/  design/
deploy/
  compose.yaml        reference deployment
  images/             Dockerfiles: server, sandboxd, netguard, sandbox base image
```

- Each package under `src/` has its own `pyproject.toml` and declares only its
  own dependencies; `sandboxd` and `netguard` do not depend on `server`.
- Each package is built into its own container image.
- **Tests live outside `src/`**, so that `test/*` and `impl/*` pull requests
  stay separable by path (REPO-001).
- **Migrations live outside `src/`.** The database schema is a contract
  (ADR-0003): migrations survive any rewrite of the server code, are reviewed
  as contracts, and must stay compatible across releases. Keeping them out of
  the package makes that visible and lets CI and code owners treat them
  separately from ephemeral code.

## Consequences

- The privileged components get small images and small dependency trees.
- One lock file keeps versions consistent across packages.
- The existing pull request policy applies without changes.

## Alternatives considered

- **Migrations inside the server package** (the usual Alembic layout):
  conventional, but mixes a long-lived contract with code that may be
  regenerated.
- **Separate repositories per component:** more overhead for a small project,
  and harder to change contracts atomically.
- **One package for everything:** the privileged components would inherit the
  server's dependencies.
