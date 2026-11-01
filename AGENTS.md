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

Where pull requests go ([ADR-0055](specs/adr/0055-an-integration-branch-before-master.md)):

- `spec/`, `test/`, `impl/` and `docs/` pull requests target `next`, the
  integration branch. Once CI passes, whoever opened one merges it, with a
  merge commit and without waiting for an approval. To update one, merge
  `next` into it, never `master`.
- `rules/` pull requests target `master` and wait for a maintainer's
  approval; afterwards a pull request from `master` brings them into `next`.
- At a milestone, one pull request brings `next` into `master`. It gets an
  automated review and a maintainer's approval, and merges with a merge
  commit; then `master` is merged back into `next`.
- Never push to `next` directly.

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
- every commit is signed off (`git commit -s`) by a human who takes
  responsibility for it.

## More

- Full workflow, review loop and roles: [docs/development/workflow.md](docs/development/workflow.md)
- How specs are written: [specs/README.md](specs/README.md)
- Contribution process: [CONTRIBUTING.md](CONTRIBUTING.md)
