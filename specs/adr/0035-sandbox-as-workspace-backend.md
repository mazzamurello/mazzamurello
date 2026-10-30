# ADR-0035: The sandbox as a Pydantic AI workspace backend

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0022, ADR-0023, ADR-0030, AGT-011, AGT-013, SBX-001, SBX-009

## Context

Pydantic AI defines a workspace: the environment where an agent's commands
and file operations run, behind a small, frozen backend protocol
(`WorkspaceBackend`, `SupportsCommands`, optional `SupportsFilesystem`). The
harness builds ready-made tools on it — shell commands with limits, reading,
writing, editing and searching files — and provides backends for several
sandboxes. Pydantic AI also ships a conformance suite for backends.

A spike on 2026-10-31 ran the official conformance suite against a container
under gVisor (`runsc`), without network: 36 tests passed and 2 were skipped
(one applies only to non-root users, one to an optional feature).

The workspace identity (`WorkspaceRef`) is recorded in the conversation
history, so that later runs reattach to the same environment.

## Decision

We will expose the sandbox to agents as **a Pydantic AI workspace backend**:

1. The control plane implements a workspace backend that calls the sandbox
   driver's API (ADR-0022) — it never talks to Docker itself (SBX-009).
2. The agent's workspace tools (AGT-011) are the harness capabilities that
   operate on a workspace (for example shell and file system tools), pinned to
   an exact harness version.
3. The backend **derives the sandbox from the authenticated tenant and user**,
   never from a `WorkspaceRef` found in history; a reference that does not
   match the current user's sandbox is refused (SBX-001).
4. The backend passes Pydantic AI's conformance suite in our tests.
5. Workspace implementations that run on the host (`LocalWorkspace`) or use
   Docker's default networking are never used (AGT-013).

## Consequences

- No tool set of our own to design for files and commands; improvements in the
  harness arrive with upgrades.
- The driver API must support what the protocol requires (complete output,
  exit codes, timeouts, environment variables without secrets, a stable
  working directory).

## Alternatives considered

- **A single `sandbox.exec` tool of our own:** simpler, but reinvents tools the
  harness already provides and tests.
