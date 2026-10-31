# ADR-0045: Pending tests and a test harness contract

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0003, ADR-0004, ADR-0008, ADR-0009, ADR-0028, REPO-001, REPO-004, REPO-009, TEN-004

## Context

Tests are written from the specs before the code (ADR-0003): a `test/*` pull
request adds tests that fail, and an `impl/*` pull request makes them pass
without changing them (REPO-001). Two things are missing for that to work.

First, CI runs the whole test suite on every pull request and fails on any
failing test (REPO-009), so a `test/*` pull request cannot be merged while its
tests fail. Marking such tests as expected failures with a strict marker does
not help: once the implementation lands, the marker must be removed, and an
`impl/*` pull request may not touch tests. REPO-004 already distinguishes
requirements that are `accepted`, and may still lack tests, from requirements
that are `implemented` and must be verified.

Second, tests and implementation are written by different authors, and the
test author does not read the implementation (the workflow in
`docs/development/workflow.md`). Tests that need a database with the schema
applied must know, before any migration exists, how that database is created,
which roles exist and how migrations are run. Creating roles needs more
privilege than migrations should have (TEN-004).

## Decision

1. **Pending tests.** A test is *pending* when it carries at least one `spec`
   marker and every requirement it references has the status `accepted`.
   - A pending test that fails, in setup or in its body, is reported as an
     expected failure, with the requirement IDs as the reason. A pending test
     that passes is reported as passed.
   - Every other test must pass: tests without a `spec` marker, and tests
     that reference at least one `implemented` requirement.
   - When a `spec/*` pull request marks a requirement `implemented`, CI runs
     the suite with that status, so the pull request fails unless every test
     of the requirement passes. Moving a requirement back to `accepted` is a
     spec change reviewed by a maintainer (REPO-005).
   - The test summary lists the requirements whose pending tests all pass,
     as candidates for `implemented`.
   - Collection errors are never converted: a test module must not import
     implementation code at module level, only inside fixtures and tests.
   - A pending test must fail when the implementation is absent. A test that
     passes vacuously, such as "every table has row-level security" on an
     empty schema, is a defect: it first checks that what it inspects exists.
2. The gate is a pytest hook in `tests/conftest.py`, which reads requirement
   statuses with the same parser as `tools/check_specs.py`. Because it decides
   what CI enforces, `tests/conftest.py` is a rules file, changed only by
   `rules/*` pull requests (REPO-001).
3. **Test harness contract.** How tests reach the system under test is a
   contract, [`test-harness.md`](../contracts/test-harness.md), changed only by
   `spec/*` pull requests. It starts with the database: PostgreSQL 17 started
   by the test suite with testcontainers (ADR-0008), roles and database
   created by the initialization in the [database contract](../contracts/database.md),
   migrations run with Alembic as `mzm_owner`, behavior tested as `mzm_app`.
   Interfaces to the server application are added before the first tests
   that need them.
4. Libraries that only tests use are added to the `dev` dependency group by
   `impl/*` pull requests, which may change `pyproject.toml` and `uv.lock`,
   before the `test/*` pull requests that need them.

## Consequences

- `test/*` pull requests merge with green CI; their failing tests show up as
  expected failures until the implementation lands.
- The status of a requirement in the spec, approved by a maintainer, is the
  single switch between "may fail" and "must pass".
- A regression in an `accepted` requirement goes unnoticed by CI until the
  requirement is marked `implemented`; requirements should be marked
  `implemented` soon after their tests pass.
- Tests that need Docker fail, rather than skip, where Docker is missing.
- The workflow documentation describes `test/*` pull requests with pending
  tests in a follow-up `docs/*` pull request.

## Alternatives considered

- **Merging `test/*` pull requests with failing CI:** makes red CI normal and
  hides real failures.
- **Strict expected-failure markers:** the `impl/*` pull request would have to
  remove them, which REPO-001 forbids; a third pull request per feature would
  be needed between implementation and merge.
- **Skipping tests when the implementation is missing:** a skip condition
  that stays true by mistake silences a test forever, even after the
  requirement is marked `implemented`.
- **Roles created by migrations:** migrations would need a role allowed to
  create roles, a privilege the running system never needs.
