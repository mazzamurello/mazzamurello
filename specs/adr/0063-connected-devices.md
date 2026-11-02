# ADR-0063: Connected devices

- **Status:** Proposed
- **Date:** 2026-11-02
- **Deciders:** @tapionx
- **Related:** ADR-0012, ADR-0033, ADR-0034, ADR-0035, ADR-0061, AGT-003, AGT-014, AGT-018, DEV-001 to DEV-009

## Context

The assistant acts in the user's sandbox, which is isolated on purpose: no
access to the household's network, no credentials. Much of what a person
needs help with lives elsewhere: the servers they administer, their laptop,
their phone. Installing updates, debugging a service, checking firewall rules
or reading logs for intrusions all need commands and files on those machines.
Inference stays on the instance; only the tools need to run on the device.

## Decision

1. **A device service** runs on each of the user's machines, always on. It
   connects to the instance over its public endpoint, so devices open no
   ports, and keeps the connection open (DEV-002). Pairing ties it to exactly
   one user: the service shows a code, the signed-in user confirms it, and the
   device receives a credential of its own, revocable at any time (DEV-001).
2. **A device is a set of tools, not a workspace.** Devices offer different
   tools (a server a shell, a phone its location), and one run may use the
   sandbox and several devices at once, so each device's tools are offered
   under its name next to the sandbox's (DEV-004). The workspace abstraction
   of ADR-0035, one place where commands run per run, stays for the sandbox.
3. **MCP over the device's connection.** The instance is an MCP client of each
   connected device, over the connection the device opened: the device lists
   its tools and runs the calls. MCP is the standard for tools (ADR-0020); the
   connection carries it in the direction the network allows.
4. **The Linux service's tools** are `run_command`, `read_file` (with line
   ranges), `write_file`, `edit_file`, `list_directory`, `find_files` and
   `search_text` (DEV-003), the set coding and administration agents converge
   on. Output is bounded as for the sandbox, and the agent is told to search
   before reading.
5. **Every call is approved,** with a button, before it reaches the device
   (AGT-018). The run waits as for any approval (ADR-0033); an approved call
   to an offline device waits until it reconnects, and the conversation is
   marked as waiting (DEV-005).
6. **Status.** About once a minute a device reports a short status, of which
   only the latest is kept, visible to its owner (DEV-006).
7. **Least privilege.** The service runs as a dedicated unprivileged user
   without `sudo`, unless the owner chooses otherwise at installation
   (DEV-007).
8. **The web app is a device too,** while in the foreground, with the tools a
   browser allows: location, a photo, a picked file (DEV-008).
9. **Linux first**; macOS and Windows may follow (DEV-009).

## Consequences

- The assistant can act on the household's machines, which is the most
  powerful and the most dangerous thing it does: injected instructions in a
  log line could ask for a command as the device's user (T-28). Approval of
  every call is the defense until finer permissions exist, and everything a
  device returns is untrusted content (AGT-003).
- The instance holds a live connection per device, and a run can wait on a
  device for a long time.
- A device's credential is a secret on that device; revoking the device is
  the remedy if it leaks (T-30).
- Coding on one's own machine needs nothing more: reading and editing files in
  a checkout through a device is a coding session in a conversation.

## Alternatives considered

- **A command-line client that brings tools only while it runs:** simpler, but
  the instance could not reach a machine from another device, such as asking
  from the phone about the home server.
- **Devices as workspaces:** reuses the harness's tools, but gives one run one
  place to act, and cannot express tools that only some devices have.
- **Bridging MCP servers installed on the device:** a whole ecosystem of tools,
  but the device's own `run_command` already reaches most of them, and their
  code would have to be trusted; dropped.
