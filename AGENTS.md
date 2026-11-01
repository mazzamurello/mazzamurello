# AGENTS.md

Rules of engagement for AI agents (and humans) working on Mazzamurello.
These rules are not suggestions: CI enforces most of them, and a change that
breaks them will be rejected.

## Sources of truth

1. `specs/requirements/` — what the system must do (IDs like `SBX-005`).
2. `specs/adr/` — why it is built this way.
3. `specs/contracts/` — interfaces that outlive the code (API, DB schema).
4. `specs/threat-model.md` — what we defend against.
5. `specs/glossary.md` — the only names allowed for domain concepts.
6. Tests — the executable form of the specs.

Code is the least authoritative artifact in this repository. When code and
specs disagree, the code is wrong — or the spec must be changed first.

## Before you change anything

- Find the requirement ID(s) your change serves. **No ID, no change.**
- If the spec is missing, ambiguous or wrong: **stop** and propose a spec
  change. Never resolve ambiguity silently in code.
- Any decision not covered by the specs becomes an ADR proposal.
- Use only terms defined in the glossary. A new concept needs a glossary
  entry first.

## Pull request types

The branch prefix defines what a pull request may touch. CI enforces it
(`tools/check_pr_paths.py`).

| Branch | May change | Purpose |
|---|---|---|
| `spec/*` | `specs/`, `ROADMAP.md`, `VISION.md` | Requirements, ADRs, contracts |
| `test/*` | `tests/`, `evals/` | Tests written from specs, before code |
| `impl/*` | `src/`, `migrations/`, `deploy/`, `pyproject.toml`, `uv.lock` | Make tests pass |
| `docs/*` | `docs/`, `README.md`, `CHANGELOG.md` | Documentation |
| `rules/*` | this file, `.github/`, `.devcontainer/`, `tools/`, governance files | Project rules (maintainer only) |

Milestones ([ADR-0060](specs/adr/0060-milestone-branches.md)):

- A milestone is one branch, `milestone/<name>`, from `master`. Commit to it
  locally, one change at a time; push it when the milestone is ready, after
  running every CI check locally.
- Each commit has one type, at the start of its subject: `spec:`, `test:`,
  `impl:` or `docs:`, and changes only the paths of that type. CI checks
  every commit of the milestone pull request this way.
- The milestone pull request goes into `master`, gets an automated review and
  a maintainer's approval, and merges with a merge commit. To update the
  branch, merge `master` into it; no other merges.
- `rules/` pull requests, and the `spec/` pull requests they depend on, go to
  `master` separately and wait for a maintainer's approval.

Implementation never modifies tests. If a test looks wrong, stop and say so.
Tests of requirements that are only `accepted` may fail without failing CI
(pending tests); once a requirement is `implemented`, its tests must pass.

## Non-negotiable rules

- **Language:** every repository artifact — code, comments, specs, ADRs,
  commit messages, PR descriptions, docs — is in English, regardless of the
  language of the conversation. Other languages appear only in i18n files.
- **Isolation:** tenant scoping is enforced by Postgres row-level security.
  Never filter by tenant manually as a substitute, never use a privileged
  database role from the application.
- **No host execution:** nothing runs on the host on behalf of users. Only the
  sandbox driver talks to the container runtime.
- **No secrets in sandboxes:** credentials stay in the control plane.
- **Async discipline:** never block the event loop; use async libraries or
  `asyncio.to_thread`.
- **Do not weaken rules to pass checks:** never edit tests, CI, `tools/` or this
  file to make your change pass.

## Definition of done

A change is done only when all of these hold:

- it references the requirement IDs it implements or verifies;
- tests, type checks (strict), linters and design tests pass;
- spec format and traceability checks pass (`python3 tools/check_specs.py`);
- CI stays within its time budget: no test takes longer than 30 seconds, and
  each test job stays within its budget in `.github/workflows/ci.yml`
  ([ADR-0059](specs/adr/0059-a-time-budget-for-ci.md)). When a change needs
  more, make the tests faster first; a budget is raised only by a `rules/`
  pull request that says why;
- every commit is signed off (`git commit -s`) by a human who takes
  responsibility for it.

## More

- Full workflow, review loop and roles: [docs/development/workflow.md](docs/development/workflow.md)
- How specs are written: [specs/README.md](specs/README.md)
- Contribution process: [CONTRIBUTING.md](CONTRIBUTING.md)
