# Development workflow

How Mazzamurello is built: by AI agents, under human direction, with the
specifications as the source of truth (ADR-0003) and CI as the enforcement
layer (ADR-0004). This document is the long form of [AGENTS.md](../../AGENTS.md).

## Roles

Roles can be played by humans or by AI agents, but each run of an agent plays
exactly one role, in its own context.

| Role | Reads | Writes | Notes |
|---|---|---|---|
| Maintainer (human) | everything | approves specs, critical tests, rules | Final say on meaning and scope |
| Spec author | specs, conversation with the maintainer | `specs/` | Accompanies proposals with a summary in the maintainer's language |
| Test author | specs, contracts | `tests/`, `evals/` | **Does not read the implementation** |
| Implementer | specs, contracts, tests | `src/`, `migrations/`, `deploy/` | **Never modifies tests** |
| Reviewer | the diff and the specs | review comments | Separate passes: correctness, security, simplicity |
| Red team | specs, threat model, running system | `tests/` (security) | Tries to break isolation invariants |

Using a different model for the reviewer than for the implementer reduces
correlated errors.

## Lifecycle of a feature

```
1. spec/*   requirements (+ ADR, + glossary, + contracts)   → maintainer approves
2. test/*   tests that reference the requirement IDs, failing → reviewed
3. impl/*   implementation that makes them pass               → reviewed, CI green
4. docs/*   user documentation                                → reviewed
```

Small, self-contained changes are preferred at every step. Requirement status
moves from `draft` to `accepted` in step 1 and to `implemented` once its tests
pass on `master` (in a later `spec/*` pull request).

## When the spec is not enough

If, at any step, the spec is missing, ambiguous or contradictory, the agent
**stops** and proposes a spec change instead of deciding in code or in tests.
"The spec doesn't say" is a valid and welcome outcome.

## The review loop

1. Automated reviewers comment on the pull request.
2. The author (an agent) addresses the comments and pushes fixes.
3. Steps 1–2 repeat **at most three times**. If issues remain, or if fixes
   start oscillating, the pull request is escalated to a maintainer.
4. Reviewers must flag, never accept: weakened tests, broad exception
   handling that hides failures, disabled checks, new dependencies without
   justification, and any change to isolation code.

## Tests

| Kind | Purpose | Examples |
|---|---|---|
| Unit | Logic in isolation | Redaction of logs (OBS-003) |
| Integration | Components with real dependencies (testcontainers) | Database role privileges (TEN-004) |
| End-to-end | The system through its public API or UI | Conversation lifecycle (API-003) |
| Design | Architecture rules on code and live schema | RLS forced on every table (TEN-003), layering, no blocking calls in async code |
| Security | Attempts to break invariants | Reaching the LAN from a sandbox (SBX-005), cross-tenant reads (TEN-006) |
| Eval | Agent behavior against models | Injection must not exfiltrate (EVL-003) |

Tests reference requirements with a marker, e.g.
`@pytest.mark.spec("SBX-005")`, which feeds the traceability check
(REPO-004).

Test strength is measured: mutation testing on security-critical modules,
property-based testing for parsers, policies and permission logic.

## Pull request types

See the table in [AGENTS.md](../../AGENTS.md#pull-request-types). The check is
implemented in `tools/check_pr_paths.py`. Dependency updates from Dependabot
(`dependabot/*` branches) may change dependency manifests and workflow files.

## Language

Conversations with agents may be in any language; every artifact is in
English and uses the [glossary](../../specs/glossary.md) (ADR-0005).

## Agent environment

Agents working on the project should run in a development container, not
directly on a maintainer's workstation — the same principle the project
applies to its own users' code.
