# ADR-0002: License under AGPL-3.0-or-later, accept contributions under the DCO, declare licensing with REUSE

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** REPO-002, ADR-0006

## Context

The project's goal is a free, private assistant that anyone can run. It is
not a commercial venture. Two risks matter:

- someone building a closed, hosted service on top of the project without
  contributing back — a realistic scenario given the multi-tenant design;
- loss of trust if the license can later be changed unilaterally, as
  happened in several projects that combined a copyleft license with a
  Contributor License Agreement.

## Decision

We will:

1. License the server and all code under **AGPL-3.0-or-later**. Anyone
   offering a modified version as a network service must offer its source to
   its users.
2. License specifications and documentation under **CC-BY-4.0**.
3. License future client SDKs and protocol definitions meant for third-party
   integration under **Apache-2.0**, so integrations carry no copyleft
   obligations. This will be declared when the first such package exists.
4. Accept contributions under the **Developer Certificate of Origin 1.1**,
   with a `Signed-off-by` trailer on every commit, checked by CI. **No CLA.**
   Contributors keep their copyright; contributions are licensed inbound as
   they are outbound.
5. Declare the license of every file in `REUSE.toml`, following the
   [REUSE specification](https://reuse.software/), with license texts in
   `LICENSES/`.

The "or later" clause allows adopting future versions of the AGPL published by
the Free Software Foundation without having to contact every contributor.

## Consequences

- No single party, including the founder, can relicense the project. This is
  a deliberate commitment.
- Some companies avoid AGPL software; we accept a smaller corporate audience.
- The project's own copyright position depends on human authorship of the
  creative parts of the work (specifications, architecture, selection and
  review), since purely machine-generated material may not be protected by
  copyright in some jurisdictions. Our process keeps human authorship
  explicit: specs and ADRs are human-approved, and every commit is signed
  off by a human.
- Model weights and voice models have their own licenses and are never
  bundled (OPS-008).

## Alternatives considered

- **MIT / Apache-2.0 for everything:** maximal adoption, but allows closed
  hosted forks.
- **GPL-3.0:** does not cover use over a network, which is the main way this
  software is used.
- **AGPL with a CLA:** signals a possible future relicensing and erodes trust.
- **Source-available licenses (SSPL, ELv2, BSL):** not open source.
