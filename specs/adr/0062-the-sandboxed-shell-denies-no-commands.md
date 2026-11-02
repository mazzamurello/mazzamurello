# ADR-0062: The sandboxed shell denies no commands

- **Status:** Accepted
- **Date:** 2026-11-02
- **Deciders:** @tapionx
- **Related:** ADR-0022, ADR-0035, ADR-0053, AGT-011, SBX-002

## Context

The harness's shell refuses some commands by name by default, such as `rm`,
`rmdir` and `dd`, as a safety net for agents that run on a real machine. In
Mazzamurello every command runs in the user's own gVisor sandbox, under the
driver's fixed policy, so the list protects nothing: the sandbox and its
workspace are the user's to change. It only stops the agent from doing
ordinary work, such as deleting a file it created, and a determined command
gets around a list of names anyway (`find -delete`, `python -c`).

## Decision

The agent's shell denies no commands and no shell operators. What a command
can reach is decided by the sandbox (SBX-001 to SBX-017), not by its name.

## Consequences

- The agent can delete, move and overwrite files in the user's workspace.
  Rewinding a conversation does not restore them (CNV-004); a confirmation
  before destructive actions belongs to the permissions of phase 1 (AGT-005),
  not to the shell.
- The harness's other safeguards stay: output limits, timeouts and the
  workspace's working directory.

## Alternatives considered

- **Keep the default list:** blocks ordinary work without adding isolation.
- **A list tuned for the sandbox:** the same weakness against indirect
  commands, and a list to maintain.
