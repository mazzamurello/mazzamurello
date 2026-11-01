# ADR-0060: Milestone branches

- **Status:** Accepted
- **Date:** 2026-11-01
- **Deciders:** @tapionx
- **Related:** ADR-0004, ADR-0055, ADR-0059, REPO-001, REPO-002, REPO-005

## Context

With the integration branch of ADR-0055, every `spec/`, `test/`, `impl/` and
`docs/` change was its own pull request into `next`, waiting for CI before
the next one could build on it, and every milestone ended with pull requests
bringing `master` back into `next`. The maintainer reviews a milestone as a
whole anyway. Work goes faster when it is committed locally, commit after
commit, and pushed once, when the milestone is meaningful.

## Decision

1. **A milestone is one branch,** `milestone/<name>`, started from `master`.
   Work is committed to it one change at a time and pushed when the
   milestone is ready for review, with every check of CI run locally first.
2. **Each commit has a type,** given by the start of its subject: `spec:`,
   `test:`, `impl:` or `docs:`. A commit may change only the paths its type
   allows, as a pull request of that type could (REPO-001), so
   implementation still never changes tests.
3. **The milestone pull request** goes from the branch into `master`. Its
   path check takes every commit that is not already on `master`: a commit
   without a type, of type `rules:`, or changing paths outside its type, is
   rejected. Merges are allowed only to bring `master` into the branch. The
   pull request gets an automated review and a maintainer's approval
   (REPO-005), and is merged with a merge commit, so `master` keeps every
   commit.
4. **`rules/` pull requests stay separate** and go to `master` with a
   maintainer's approval: they change the checks that gate everything else.
   A `spec/` pull request that a `rules/` one needs goes to `master` first in
   the same way. The other single-type pull requests remain possible for
   small changes outside a milestone.
5. **The integration branch is retired:** `next`, its ruleset and its checks
   are removed. This supersedes ADR-0055.

## Consequences

- No pull request waits for another during a milestone; CI runs once, at the
  end, within its time budget (ADR-0059).
- A difference between the maintainer's machine and CI is found only at the
  milestone, and its fix joins the same branch.
- Nothing of a milestone is on GitHub until it is pushed.
- Milestone reviews are large, but read commit by commit, each of one type.

## Alternatives considered

- **Keep the integration branch:** reviews were already per milestone, and
  every change paid for a pull request and a CI run of its own.
- **One commit per milestone:** fewer commits to read, but specs, tests and
  code would mix, and the path policy could no longer tell them apart.
