## Summary

<!-- What does this pull request change, and why? -->

## Type

<!-- Must match the branch prefix. CI enforces the allowed paths. -->

- [ ] `spec/*` — requirements, ADRs, contracts
- [ ] `test/*` — tests written from approved specs
- [ ] `impl/*` — implementation (does not modify tests)
- [ ] `docs/*` — documentation
- [ ] `rules/*` — project rules and governance

## Requirements

<!-- List the requirement IDs this change proposes, verifies or implements. -->

Refs:

## Checklist

- [ ] Every commit is signed off (`git commit -s`).
- [ ] Repository artifacts are in English and use glossary terms.
- [ ] `python3 tools/check_specs.py` passes.
- [ ] Tests and checks pass locally.
- [ ] For `impl/*`: no test was modified.
- [ ] For `spec/*`: new concepts are in `specs/glossary.md`; new decisions have an ADR.
- [ ] If the lock file changes the version of Pydantic AI, its harness or DBOS: the release notes since the previous version are summarized here, and new features that could replace project code or change an ADR are recorded as issues or ADR proposals (REPO-010).
