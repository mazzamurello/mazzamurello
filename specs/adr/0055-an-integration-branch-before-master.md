# ADR-0055: An integration branch before `master`

- **Status:** Accepted
- **Date:** 2026-11-01
- **Deciders:** @tapionx
- **Related:** ADR-0004, REPO-001, REPO-002, REPO-005

## Context

Every pull request into `master` needs a maintainer's approval (REPO-005).
In this phase almost every pull request is written by an agent and opened
from the maintainer's own account, and GitHub does not let an author approve
their own pull request. Each one then waits for the maintainer to merge it
with a bypass, one at a time, and a stack of pull requests cannot be merged
in one step. Reviewing every pull request separately is the slowest part of
the work, while what matters is reviewing each coherent piece of work before
it reaches `master`.

## Decision

1. **The integration branch** is `next`, a long-lived branch started from
   `master`. `spec/`, `test/`, `impl/` and `docs/` pull requests target
   `next`. They run the same CI as pull requests into `master`, and they are
   merged, without an approval, once CI passes, by whoever opened them,
   agents included. They are merged with a merge commit, so that every
   change on `next` names the pull request and the branch it came from.
2. **`rules/` pull requests target `master`** and keep needing a
   maintainer's approval: they change the checks that gate every other pull
   request, so they never merge unreviewed. After one is merged, a pull
   request from `master` into `next` brings it there; such a pull request
   may contain only `master`'s own history.
3. **The milestone pull request** brings `next` into `master` when a
   coherent set of requirements is done. It is reviewed by an automated
   review and approved by a maintainer, as REPO-005 requires, merged with a
   merge commit, and then brought back into `next` the same way. Its path
   check does not use a type of its own: it checks every pull request merged
   into `next` against that pull request's type, and rejects any commit that
   reached `next` without a pull request (REPO-001).
4. **`next` is protected** by a ruleset: it cannot be deleted or
   force-pushed, it changes only through pull requests, merge commits only,
   and the CI checks are required. No approval is required.
5. **This is revisited** before the first public release, or when the
   project has a second maintainer.

## Consequences

- Work reaches `next` as soon as CI passes; `master` still contains only
  reviewed work.
- `next` may contain specs and ADRs that no maintainer has approved yet;
  the milestone review covers them, and they can be changed there.
- Milestone reviews are large. The milestone pull request lists the pull
  requests it contains so they can be reviewed one by one.
- The path policy needs the merge history of `next`, so `next` never uses
  squash or rebase merges.

## Alternatives considered

- **Approve every pull request into `master`:** the current bottleneck.
- **Bypass the approval on every pull request into `master`:** fast, but
  REPO-005 would hold only on paper, and nothing would ever be reviewed.
- **Drop the required approval on `master`:** the same, without a bypass.
- **A second account or a bot that approves:** an approval that reviews
  nothing.
