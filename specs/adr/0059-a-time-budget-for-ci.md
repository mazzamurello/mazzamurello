# ADR-0059: A time budget for CI

- **Status:** Accepted
- **Date:** 2026-11-01
- **Deciders:** @tapionx
- **Related:** ADR-0004, ADR-0024, ADR-0053, ADR-0055, REPO-011

## Context

Every pull request waits for CI before it merges, and a milestone is a chain
of pull requests that each wait for the one before (ADR-0055). The tests ran
in one job, one after another, and took about seven minutes on GitHub's
runners: two minutes of sandbox isolation tests, mostly spent waiting for
connections to time out one by one, a minute for the end-to-end deployment,
and almost two for the rest. Nothing stopped the next feature from adding a
slow test, or the next milestone from adding a minute.

## Decision

1. **The tests run in parallel jobs,** each on its own runner, with its own
   Docker and its own host firewall, so the network guard's table of one job
   cannot affect another:

   | Job | Tests |
   |---|---|
   | core | `tests/design`, `tests/integration` (except the sandbox driver's), `tests/tooling` |
   | sandbox | `tests/security`, `tests/integration/test_sandbox_driver.py` |
   | end-to-end | `tests/e2e` |

   Lint and type checks run in a job of their own. A last job, named
   `Python checks` as the branch rulesets require, passes only when all of
   them passed.
2. **No test may take longer than 30 seconds,** counting its call alone:
   session fixtures, such as the database and the images, are shared by many
   tests and count in the job's session instead.
3. **Each job has a budget for its test session,** measured from pytest's
   report:

   | Job | Measured on 2026-11-01 | Budget |
   |---|---|---|
   | core | 149 s | 200 s |
   | sandbox | 116 s | 150 s |
   | end-to-end | 76 s | 100 s |

   The budgets leave about a third of headroom for runners' variance and for
   new tests.
4. **The limit and the budgets live in `.github/workflows/ci.yml`,** next to
   the jobs they bound; `tools/check_test_durations.py` reads pytest's JUnit
   report after the tests and fails the job when a test or the session goes
   over. Every job also stops after 15 minutes.
5. **When a change needs more time,** it makes tests faster first: running
   waits in parallel, waiting for an outcome instead of a fixed time,
   smaller limits in the harness. Moving tests to another job, or adding a
   job, is a `rules/` pull request; so is raising a budget, which says why the
   time is needed. The budgets are reviewed at each milestone.

## Consequences

- CI's wall time is the longest job, about three minutes, instead of the sum.
- The jobs install the workspace, gVisor and the images three times; runner
  minutes grow, which is free for public repositories.
- A slow test fails CI even when the job is within its budget, so slowness is
  found where it starts.
- The budgets do not cover the time spent before the tests: installing
  dependencies and gVisor, about 25 seconds per job.

## Alternatives considered

- **Run the tests in parallel on one runner (pytest-xdist):** the tests share
  the host's firewall table and the instance's default model, so parallel
  workers would interfere.
- **Run the end-to-end test only on milestone pull requests:** saves a job,
  but finds a broken deployment only at the milestone.
- **Only a timeout for each job:** stops a hung run, but lets the suite grow
  slowly until it reaches the timeout.
