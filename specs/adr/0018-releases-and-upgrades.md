# ADR-0018: Releases, upgrades and supply-chain integrity

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** OPS-005, OPS-006, OPS-007, OPS-008, REPO-007

## Context

Self-hosters upgrade irregularly and often skip versions. They trust the
images they pull with their family's data. A failed migration or a tampered
image is far more damaging here than in a typical web app.

## Decision

We will:

1. Use **Semantic Versioning**, staying in `0.x` until contracts are stable;
   every breaking change ships with migration notes.
2. Generate the changelog from **Conventional Commits**.
3. Guarantee **upgrades from any earlier released version** to the current
   one, tested in CI.
4. Document **backup and restore**, and test restore in CI.
5. Publish **multi-architecture** (amd64, arm64) container images, **signed**
   (Sigstore cosign) and with an **SBOM**.
6. Pin CI actions to commit SHAs, grant workflows minimal permissions, and
   update dependencies through automated, reviewed pull requests.
7. Never bundle model weights or voice models in images; download them at
   setup time, showing their licenses.

## Consequences

- Release engineering work from the first release on.
- Users can verify what they run.

## Alternatives considered

- **`latest`-only, unsigned images:** common, and not acceptable for this
  project's trust model.
