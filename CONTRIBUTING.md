# Contributing to Mazzamurello

Thank you for your interest. Mazzamurello is a young project with a strict,
spec-driven process. Reading this page first will save you time.

## Ground rules

- **Specs come first.** Every change serves a requirement in
  [`specs/requirements/`](specs/requirements/). New behavior starts as a spec
  proposal, not as code.
- **English only** in the repository (code, comments, specs, commits, PRs).
  Conversations in issues and discussions may happen in other languages, but
  English reaches more people.
- **Be kind.** This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
- **Security issues are never reported publicly.** See [SECURITY.md](SECURITY.md).

## Where to start

| You want to… | Do this |
|---|---|
| Ask a question or discuss an idea | Open a [Discussion](https://github.com/mazzamurello/mazzamurello/discussions) |
| Report a bug | Open an issue using the bug report form |
| Propose a feature or behavior change | Open a spec proposal issue, then a `spec/*` pull request |
| Fix a bug covered by an existing requirement | `test/*` pull request reproducing it, then `impl/*` |
| Improve documentation | `docs/*` pull request |

The project is in its design phase; see [ROADMAP.md](ROADMAP.md) for what is
in scope now. Proposals outside the [vision](VISION.md) will likely be
declined — this is not a judgment of the idea, just of the project's scope.

## Pull request types

The default branch is `master`. Each pull request has exactly one type,
given by its branch prefix, and CI rejects files outside the paths allowed
for it. A milestone pull request, from a `milestone/` branch, has no type of
its own: each of its commits has one, at the start of its subject, and is
checked the same way
([ADR-0060](specs/adr/0060-milestone-branches.md)). Every pull request
targets `master`.

| Branch prefix | May change |
|---|---|
| `spec/` | `specs/`, `ROADMAP.md`, `VISION.md` |
| `test/` | `tests/`, `evals/` |
| `impl/` | `src/`, `migrations/`, `deploy/`, `pyproject.toml`, `uv.lock` |
| `docs/` | `docs/`, `README.md`, `CHANGELOG.md` |
| `rules/` | `AGENTS.md`, governance files, `.github/`, `.devcontainer/`, `tools/`, licensing files |

The intended flow for a feature is:

1. `spec/…` — requirements (and ADRs if needed) are proposed and approved.
2. `test/…` — tests are written from the approved spec and fail.
3. `impl/…` — the implementation makes them pass without touching tests.

The full workflow is described in
[docs/development/workflow.md](docs/development/workflow.md).

## Commits

- Use [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(sandbox): …`, `fix(api): …`, `docs: …`, `spec(agent): …`,
  `test(tenancy): …`, `chore: …`.
- Reference the requirement IDs a commit serves in its body, e.g.
  `Refs: SBX-005, SBX-006`.
- **Sign off every commit** (see below).

## Developer Certificate of Origin (DCO)

This project does not use a Contributor License Agreement. Instead, every
commit must carry a `Signed-off-by` line certifying the
[Developer Certificate of Origin 1.1](https://developercertificate.org/):
that you wrote the change, or otherwise have the right to submit it under the
project's licenses.

```bash
git commit -s -m "feat(api): add conversation listing"
```

The sign-off must match the commit author's email. CI checks every commit
(`tools/check_dco.py`). You keep the copyright of your contributions; they
are licensed under the same terms as the files they modify ("inbound =
outbound"), as declared in [REUSE.toml](REUSE.toml).

## AI-assisted contributions

This project is itself written by AI agents under human direction, so
AI-assisted contributions are welcome — under the same rules:

- The human who signs off a commit is responsible for it, regardless of who
  or what wrote it.
- AI agents must follow [AGENTS.md](AGENTS.md).
- You may credit the tool with a `Co-authored-by:` or `Assisted-by:` trailer.
- Do not submit changes you have not read and understood.

## Review

- Every pull request is reviewed by automated checks and, where required by
  [CODEOWNERS](.github/CODEOWNERS), by a maintainer.
- Changes to specs, rules and security-critical areas always require
  maintainer approval.
- Automated AI review never runs with secrets or write permissions on pull
  requests from forks (REPO-008).

## Local checks

```bash
python3 tools/check_specs.py
python3 tools/check_traceability.py
python3 -m unittest discover -s tests/tooling -t . -v
```

Once the Python workspace exists, also run:

```bash
uv sync --locked --all-packages
uv run ruff format --check
uv run ruff check
uv run pyright
uv run pytest
```

`uv run ty check` gives faster type-checking feedback; pyright remains the
required gate until ty meets the switch criteria recorded in `specs/adr/`.
