# ADR-0076: A persistent workspace in an ephemeral sandbox

- **Status:** Accepted
- **Date:** 2026-11-05
- **Deciders:** @tapionx
- **Related:** ADR-0022, ADR-0035, ADR-0043, ADR-0053, ADR-0077, SBX-001, SBX-010, SBX-016, SBX-018, SBX-019, AGT-014, AGT-022, T-33

## Context

Each user has one sandbox (SBX-001), which the driver stops after 30 idle
minutes and starts again on the next command (ADR-0053). Its workspace, a
Docker volume at `/workspace`, is permanent; the rest of its disk survives a
stop, and is lost only when the container is created again. Commands start
in `/workspace`, and large tool outputs are kept there (AGT-014).

So everything the agent writes is permanent by default, and the workspace
only grows: downloads, intermediate data and tool outputs pile up beside the
few files worth keeping. And anything injected instructions plant in the
sandbox, in the workspace or in the system, survives into every later
conversation (T-33), and into backups (ADR-0077).

The workspace has two jobs: the sandbox's scratch space, and the place where
a household's long-lived files end up, such as a script it reuses or a
budget it updates every month.

## Decision

1. **Only `/workspace` persists.** When a sandbox stops, the driver removes
   its container; the next command starts a new one from the image. Software
   installed in the system, processes and every file outside `/workspace`
   are gone (SBX-018).
2. **Commands start in a scratch folder,** `/scratch`, outside the workspace.
   Keeping a file is a deliberate act: putting it in `/workspace`. Large tool
   outputs are kept in scratch (AGT-014), so they last as long as the
   sandbox.
3. **The agent is told the difference** (AGT-022): scratch is for what gets
   to an answer; `/workspace` is for what the user will want again, such as
   scripts, results and notes, each piece of work in its own folder with a
   `README.md` that says what it is and how to make it again. Bulk data is
   not kept when it can be fetched again.
4. **A workspace quota, measured** (SBX-019): after every command the driver
   measures the workspace, and the command's result tells the agent when the
   workspace uses more than 80% of its quota, or exceeds it, so that it tidies
   up or asks the user. The quota is configurable, 2 GiB by default.
5. **Hard disk limits come later** (SBX-016). Docker's local volumes cannot
   mount a filesystem image (`loop: invalid argument`, spike of 2026-11-05),
   so the mechanism of ADR-0022 point 7 does not work as written. gVisor can
   bound everything outside `/workspace` (`--overlay2=root:self,size=…`),
   which needs a runtime registered with that argument on the host; it is
   checked in a spike of its own, with the workspace's hard limit.
6. **Useful software belongs in the image** (ADR-0022 point 9): what users
   need often is added to the sandbox image instead of being installed in
   every sandbox; the roadmap tracks the selection.

## Consequences

- The workspace holds what the household chose to keep, which keeps it
  small, readable and worth backing up (ADR-0077).
- Nothing planted outside `/workspace` outlives the sandbox; what is planted
  inside it remains, and the defenses there are the backups' history, the
  user's view of the workspace and untrusted content handling (AGT-003).
- Software installed with `apt` or `pip` has to be installed again in a new
  sandbox, in `/workspace` if it must last; the image's selection matters
  more.
- Older conversations can point to tool outputs that no longer exist; the
  agent runs the command again.
- The quota is a warning, not a wall: one command can still exceed it until
  the hard limits arrive.

## Alternatives considered

- **A disposable workspace,** emptied with the sandbox: the safest, but the
  household loses the files the assistant made for it, and tasks that span
  days stop working.
- **Keeping the container's disk:** installed software survives, but so does
  anything planted in the system, and its size has no bound.
- **Instructions only, with commands still starting in `/workspace`:** models
  follow instructions most of the time, not always; a default that forgets
  is safer than one that keeps.
