# ADR-0078: A sandbox per conversation, for one answer

- **Status:** Accepted
- **Date:** 2026-11-06
- **Deciders:** @tapionx
- **Related:** ADR-0010, ADR-0022, ADR-0035, ADR-0068, ADR-0073, ADR-0076, ADR-0077, SBX-001, SBX-010, SBX-018, SBX-019, SBX-020, CNV-005, OPS-006, T-33

## Context

Each user has one sandbox and one workspace, shared by all their
conversations (ADR-0010, ADR-0022 point 6). A conversation in which
injected instructions took hold, perhaps with a weaker model, can read and
change everything the user kept in that workspace from other conversations,
and plant files that steer them later (T-33). Connectors and devices are
called by the harness, never from the sandbox (AGT-013, ADR-0063), so the
workspace is the one bridge between conversations.

A sandbox lives until 30 minutes after its last command (ADR-0076). Programs
started in it, such as a daemon injected instructions planted, run until
then, using the sandbox's CPU and internet. The driver keeps the time of the
last command in memory only: sandboxes running when it restarts are never
removed.

A gVisor sandbox starts, runs a command and is removed in about 0.35
seconds on the maintainer's server, and an idle one uses about 46 MB of
memory (measured on 2026-11-06).

## Decision

1. **One sandbox per conversation.** Each conversation has its own container
   and its own workspace, addressed by tenant, user and conversation. A
   conversation's commands run only in its sandbox, and its workspace is
   visible to no other conversation (SBX-001).
2. **A sandbox lives for one answer.** When a run ends, whether it finished,
   failed, was stopped or waits for the user, the worker removes the
   conversation's sandbox; the next answer gets a new one with the same
   workspace (SBX-018). A program started in a sandbox outlives neither the
   answer that started it nor the sandbox.
3. **Safety nets.** A sandbox without commands for `SIBILLO_SANDBOX_IDLE_MINUTES`,
   now 5 by default, is removed, for a run that ended without telling the
   driver. The driver removes every sandbox when it starts, so none is left
   untracked.
4. **A conversation's workspace lives with it** (SBX-010): deleting the
   conversation deletes its workspace; archiving keeps it. A fork starts with
   a copy of the original conversation's workspace as it was when the fork
   was made (CNV-005). Rewinding leaves it as it is (ADR-0068).
5. **The quota is per workspace** (SBX-019).
6. **Backups hold every conversation's workspace,** as
   `workspaces/<tenant>/<user>/<conversation>.tar` (ADR-0077);
   `restore --workspace USERNAME` restores the workspaces of that user's
   conversations that still exist.
7. **Workspaces of the earlier layout are not migrated:** before the first
   release, per-user workspaces are left unused, as ADR-0071 does for the
   database; the README says how to remove them.
8. **Sharing files between conversations comes later,** deliberately: the file
   library (CNV-012) or folders as projects would be explicit bridges, chosen
   by the user, and need their own decision.

## Consequences

- A compromised conversation reaches only its own workspace and the answer it
  is in; what it plants dies with the answer, outside the workspace, or stays
  in that one conversation's workspace.
- Work that spans conversations, such as a budget updated every month, stays
  in one conversation until sharing arrives; a fork carries a copy forward.
- Every answer that runs a command starts a sandbox, about a third of a
  second; background programs stop when the answer ends.
- More, smaller workspaces: a user's disk use is the sum of their
  conversations', each under its quota until hard limits arrive (SBX-016).

## Alternatives considered

- **The per-user sandbox with an offline twin for untrusted answers:** keeps
  one workspace, but the workspace still carries content between
  conversations, and the twin needs a second container anyway.
- **A sandbox per conversation that lives until idle:** isolates
  conversations, but leaves planted programs running between messages.
- **A sandbox per folder:** a project boundary the user chooses; kept for
  the later decision on sharing (point 8).
