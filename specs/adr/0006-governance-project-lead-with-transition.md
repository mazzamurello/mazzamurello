# ADR-0006: Governance by a project lead, with a defined transition to a core team

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** ADR-0002, REPO-005

## Context

The project starts with a single person, who is also its first user. Early
projects need fast, coherent decisions; projects that pretend to be
democracies while being run by one person tend to break at the first
contested decision. Projects that depend on one person forever have a bus
factor of one.

## Decision

We will declare the founder as **project lead** with the final say (the model
often called BDFL), and define in advance when and how governance moves to a
**core team** of maintainers deciding by majority: when at least three
maintainers have been active for six consecutive months. The details are in
[GOVERNANCE.md](../../GOVERNANCE.md).

To reduce the bus factor from the start, project assets (GitHub organization,
domains, signing keys, registry accounts) are owned by the organization, with
two-factor authentication required and recovery codes kept safe, and a second
trusted owner is added as soon as possible.

## Consequences

- Decisions are fast and accountable while the project is small.
- Contributors know how they can gain a say in the project.

## Alternatives considered

- **Committee or foundation from day one:** too heavy for a project with one
  maintainer.
- **Undeclared governance:** creates conflict when expectations differ.
