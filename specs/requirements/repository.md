# REPO — Repository governance

Rules for changing the repository itself, enforced by CI. Background:
ADR-0003, ADR-0004, ADR-0002.

## REPO-001: Pull request types and allowed paths

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** unit

Every pull request MUST have a type given by its branch prefix (`spec/`,
`test/`, `impl/`, `docs/`, `rules/`), and CI MUST reject a pull request that
changes files outside the paths allowed for its type. Files governing the
project's rules MUST be changeable only by `rules/` pull requests.
Implementation pull requests MUST NOT change tests.

The pull request that brings the integration branch into `master` has no
type of its own: CI MUST check every pull request merged into the
integration branch against that pull request's type, and MUST reject commits
that reached the integration branch without a pull request. `rules/` pull
requests MUST target `master` (ADR-0055).

## REPO-002: DCO sign-off

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** unit

Every non-merge commit in a pull request MUST contain a `Signed-off-by`
trailer whose email matches the commit author's email. Automated dependency
update bots are exempt.

## REPO-003: Spec format and cross-references

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** unit

CI MUST validate the format of requirements and ADRs (IDs, fields, allowed
values, normative keywords) and MUST fail when any document references a
requirement ID or ADR that does not exist.

## REPO-004: Traceability

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** unit

Tests reference the requirements they verify with the `spec` pytest marker.
CI MUST fail when a test references a requirement that does not exist or whose
status is `draft` or `deprecated`, and when an `implemented` requirement with
priority MUST and an automated verification kind has no test referencing it.
CI MUST report, without failing, the `accepted` requirements of that kind that
have no test yet, so that tests can be written incrementally before a
requirement is marked `implemented`.

## REPO-005: Maintainer review of rules and specs

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** review

Changes to specifications, project rules, CI configuration and governance
files MUST require approval by a maintainer, enforced through code owners
and branch protection on `master`.

## REPO-006: English artifacts

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** review

Every repository artifact MUST be written in English, except i18n resources
(ADR-0005).

## REPO-007: Hardened CI

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** review

CI workflows MUST pin third-party actions to full commit SHAs, MUST declare
minimal permissions, and MUST NOT interpolate untrusted input (such as branch
names) directly into scripts.

## REPO-008: No secrets or write access for untrusted pull requests

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** review

Workflows triggered by pull requests from forks, including AI review agents,
MUST run without secrets and without write permissions. Automation that needs
secrets MUST be triggered explicitly by a maintainer.

## REPO-009: Code quality gates

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** review

CI MUST run, on every pull request and on `master`, the formatter check, the
linter, the type checker in strict mode and the test suite of the Python
workspace, and MUST fail on any finding. Dependencies MUST be installed from
the committed lock file only.

## REPO-010: Framework upgrades reviewed against release notes

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 0
- **Verification:** review

A pull request that changes the version of Pydantic AI, its harness or the
durable execution engine in the lock file MUST summarize the relevant release
notes since the previous version, and MUST record new features that could
replace project code or change an ADR as issues or ADR proposals (ADR-0030).
