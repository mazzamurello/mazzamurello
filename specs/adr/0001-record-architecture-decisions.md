# ADR-0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** ADR-0003, REPO-003

## Context

Mazzamurello is written by AI agents under human direction. Agents start
every session without memory of previous ones, and future contributors will
not have been present when decisions were taken. Decisions that live only in
conversations are lost, and lost decisions get silently re-litigated in code.

## Decision

We will record every significant product, architecture, process and
governance decision as an architecture decision record (ADR) in
`specs/adr/`, using the light MADR format of [`template.md`](template.md).

- ADRs are numbered sequentially and never renumbered.
- Accepted ADRs are immutable. A changed decision is a new ADR that
  supersedes the old one; the old one's status becomes
  `Superseded by ADR-NNNN`.
- ADRs are proposed through `spec/*` pull requests.
- Valid statuses: `Proposed`, `Accepted`, `Rejected`, `Deprecated`,
  `Superseded by ADR-NNNN`. CI validates the format.

## Consequences

- Agents and contributors can learn *why* the system is built as it is
  before changing it.
- Writing an ADR costs time; it is required only for decisions that are hard
  to reverse or that constrain future work.

## Alternatives considered

- **Decisions in issues or wiki pages:** not versioned with the code, not
  reviewed, easily lost.
- **Decisions only in requirements:** requirements say *what*, not *why*.
