# Specifications

This directory is the source of truth for Mazzamurello. Code exists to
satisfy what is written here; tests exist to prove it does.

| Path | Contents |
|---|---|
| [`requirements/`](requirements/) | Numbered requirements, grouped by area |
| [`adr/`](adr/) | Architecture decision records: why things are the way they are |
| [`contracts/`](contracts/) | Interfaces that outlive the code: public API, database schema |
| [`glossary.md`](glossary.md) | The canonical name of every domain concept |
| [`threat-model.md`](threat-model.md) | Assets, adversaries, trust boundaries and mitigations |

## Requirements

Each file in `requirements/` covers one area and declares its ID prefix in
its title:

```markdown
# SBX — Sandbox and network isolation
```

Each requirement is a level-2 heading with an ID, followed by a field list
and a normative statement:

```markdown
## SBX-005: No access to local networks

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security, integration

A sandbox MUST NOT be able to open connections to …

Rationale: …
```

### Fields

| Field | Values | Meaning |
|---|---|---|
| Status | `draft`, `accepted`, `implemented`, `deprecated` | `draft` is proposed; `accepted` is approved by a maintainer and may be implemented; `implemented` is verified by tests; `deprecated` is kept for history |
| Priority | `MUST`, `SHOULD`, `MAY` | Keywords as defined in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) and [RFC 8174](https://www.rfc-editor.org/rfc/rfc8174) |
| Phase | `0`–`3` | The [roadmap](../ROADMAP.md) phase in which the requirement is due |
| Verification | `unit`, `integration`, `e2e`, `design`, `security`, `eval`, `review` | How compliance is demonstrated |

The normative statement must use the keyword matching the priority (in
capitals). Verification kinds:

- `unit`, `integration`, `e2e` — automated tests at that level;
- `design` — automated architecture tests (layering, schema properties, …);
- `security` — adversarial tests that try to break an invariant;
- `eval` — agent-behavior evaluations against models (ADR-0015);
- `review` — human review; used only when automation is impossible.

### Rules

- IDs are never reused. A removed requirement becomes `deprecated`.
- Only maintainers move a requirement from `draft` to `accepted`.
- Tests reference the requirements they verify (traceability, REPO-004).
- `python3 tools/check_specs.py` validates format, uniqueness and every
  cross-reference to requirement IDs and ADRs in the repository's documents.

## Architecture decision records

ADRs follow a light version of [MADR](https://adr.github.io/madr/). Copy
[`adr/template.md`](adr/template.md), use the next free number, and propose
it in a `spec/*` pull request. ADRs are immutable once accepted: to change a
decision, write a new ADR that supersedes the old one.

## Language

Everything here is in English and uses the terms defined in the
[glossary](glossary.md) (ADR-0005).
