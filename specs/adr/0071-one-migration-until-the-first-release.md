# ADR-0071: One migration until the first release

- **Status:** Accepted
- **Date:** 2026-11-03
- **Deciders:** @tapionx
- **Related:** ADR-0003, ADR-0046, ADR-0068, ADR-0069, OPS-005

## Context

The database contract changes with every milestone, and `migrations/` has
grown one Alembic revision per change since phase 0. Phases 0 and 1 change
the schema in ways that would need data conversions: message versions
removed (ADR-0068), model configurations replaced by connections
(ADR-0069). Sibillo has not been released: the only databases are the
maintainers' own installations and the test suite's. OPS-005 requires
upgrades only between released versions.

Writing and testing conversions for data that exists only on developers'
machines costs time and leaves the history harder to read than the schema
it builds.

## Decision

1. **Until the first release, `migrations/` holds one initial migration**
   that creates the schema of the database contract, and is rewritten
   whenever the contract changes. No data conversions are written.
2. **Existing databases are recreated** after a change of the schema: the
   change says so in its commit, and an installation is set up again from
   scratch (`docker compose down --volumes`, then the installation steps).
3. **From the first release on, migrations are only added,** and every
   released version upgrades to the current one without manual steps
   (OPS-005). The first release's migration is the one in place then.

## Consequences

- The migration reads as the schema it builds, and the contract and the
  migration are compared directly.
- Every schema change before the first release deletes the data of existing
  installations, the maintainer's included; there are no users to protect
  yet.
- Tests that checked the conversions of earlier revisions are removed with
  them.

## Alternatives considered

- **Keep adding revisions with data conversions:** the discipline OPS-005
  needs after the release, paid now for data nobody keeps.
- **Add revisions without conversions:** a history that does not match any
  database anyone ever ran.
