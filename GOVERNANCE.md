# Governance

## Current model: project lead

Mazzamurello is led by its founder, who acts as project lead (a model often
called *Benevolent Dictator For Life*, BDFL). The project lead has the final
say on scope, architecture, releases and membership.

| Role | People |
|---|---|
| Project lead | Riccardo Serafini ([@tapionx](https://github.com/tapionx)) |
| Maintainers | Riccardo Serafini ([@tapionx](https://github.com/tapionx)) |

This model is stated openly because it is how small projects actually work.
It is meant to be temporary.

## How decisions are made

- **Product and architecture decisions** are recorded as ADRs in
  [`specs/adr/`](specs/adr/) through `spec/*` pull requests. Anyone may
  propose one; discussion happens on the pull request.
- **Requirements** follow the same path in [`specs/requirements/`](specs/requirements/).
- **Rules** (AGENTS.md, CI, governance files) change only through `rules/*`
  pull requests approved by a maintainer.
- When consensus emerges, the project lead merges. When it does not, the
  project lead decides and records the reasoning in the ADR.

## Maintainers

Maintainers review and merge pull requests and triage issues. A contributor
may be invited to become a maintainer after a sustained record of
high-quality contributions and reviews. Maintainers who are inactive for
six months may be moved to emeritus status, with thanks.

## Transition to a core team

When the project has **at least three maintainers who have been active for
six consecutive months**, governance transitions to a core team:

- decisions are made by the maintainers by simple majority;
- the founder remains a maintainer with one vote;
- this document is updated through a `rules/*` pull request approved by the
  majority of maintainers.

## Licensing commitment

The project does not use a Contributor License Agreement. Contributions are
accepted under the [Developer Certificate of Origin](https://developercertificate.org/)
and remain the copyright of their authors. As a consequence, no single person
or organization can relicense the project. This is intentional.

## Code of Conduct

All participants are expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
Maintainers may moderate discussions and remove contributions that disregard
it.

## Changes to this document

Changes to governance require a `rules/*` pull request approved by the
project lead (or, after the transition, by a majority of maintainers).
