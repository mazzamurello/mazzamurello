# SBX — Sandbox and network isolation

Where and how user and agent code runs. Background: ADR-0010, threat model
T-03 to T-07.

## SBX-001: One sandbox per conversation

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Each conversation MUST have its own sandbox and workspace. A sandbox MUST NOT
be shared between users or between conversations, and code run for a
conversation MUST run only in that conversation's sandbox (ADR-0078).

## SBX-002: Strong isolation runtime

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Sandboxes MUST run under the gVisor isolation runtime (`runsc`), which is
stronger than a plain container and does not require hardware virtualization
(ADR-0023).

## SBX-003: Fail closed without isolation

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

If the configured isolation runtime is unavailable, the system MUST refuse to
start sandboxes and MUST report the reason to the instance admin. It MUST NOT
fall back to a weaker runtime. At startup, the sandbox driver MUST verify the
isolation runtime with a canary sandbox, checking that it runs under the
configured runtime and that a blocked address is unreachable, before
accepting any request.

## SBX-004: Internet access

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

A sandbox MUST be able to reach public internet addresses, so that the agent
can browse, download and install software.

## SBX-005: No access to local networks

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security

A sandbox MUST NOT be able to open connections to: `0.0.0.0/8`, `10.0.0.0/8`,
`100.64.0.0/10`, `127.0.0.0/8`, `169.254.0.0/16`, `172.16.0.0/12`,
`192.168.0.0/16`, `224.0.0.0/4`, `240.0.0.0/4`, `::1/128`, `fc00::/7`, `fe80::/10`, `ff00::/8`,
or any address of the host. These restrictions MUST be enforced outside the
sandbox's kernel, so that they hold even for code with full control of the
sandbox's network configuration. Security tests MUST verify this from inside a
running sandbox, and from a test container with network administration
privileges attached like a sandbox.

## SBX-006: No sandbox-to-sandbox traffic

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security

A sandbox MUST NOT be able to reach any other sandbox over the network.

## SBX-007: Isolated name resolution

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** security

Sandboxes SHOULD resolve names only through a resolver chosen by the
instance, and SHOULD NOT be able to resolve names of containers or hosts
internal to the instance or the household network.

## SBX-008: No secrets in sandboxes

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security

A sandbox MUST NOT contain credentials of any kind — in environment
variables, files, mounts or images — other than credentials the user has
explicitly placed in their own workspace.

## SBX-009: Container runtime confined to the sandbox driver

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

The sandbox driver MUST be the only component with access to the container
runtime. The control plane MUST NOT mount the container runtime socket and MUST interact
with sandboxes only through the sandbox driver's authenticated API.

## SBX-010: Persistent workspace

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

Each sandbox MUST have a persistent workspace, mounted at `/workspace`, that
survives sandbox restarts and re-creation, so that the files the user wants
to keep persist. Nothing else in the sandbox persists (SBX-018, ADR-0076).
Deleting a conversation MUST delete its workspace, and a fork MUST start with
a copy of the original conversation's workspace as it was when the fork was
made (ADR-0078).

## SBX-011: Resource limits

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Each sandbox MUST be limited in CPU, memory, number of processes and
execution time, with limits configurable by the instance admin. Process limits
MUST count the processes running inside the sandbox.

## SBX-012: No privileged sandboxes

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

Sandboxes MUST NOT run privileged, share host namespaces or mount host paths
other than their own workspace. Root inside the sandbox is allowed.

## SBX-013: No unfiltered IPv6

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security

A sandbox MUST NOT have IPv6 connectivity unless restrictions equivalent to
SBX-005 are enforced for IPv6.

## SBX-014: File exchange with the workspace

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

The control plane MUST be able to list, read, write, move and delete files and
folders of a conversation's workspace through the sandbox driver, streamed
and held in memory by neither, so that the assistant can work on files
provided by the user and return the files it produces. A write MUST be
complete or absent, never partial, and MUST be refused when it would exceed
the workspace's quota (SBX-019). The driver MUST refuse paths outside the
workspace, including through links, and MUST NOT follow a link to read or
write. An operation outside an answer MUST NOT leave the sandbox running
(SBX-018, ADR-0079).

## SBX-015: Network restrictions before any code runs

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

A sandbox's network restrictions MUST be applied and verified before any code
runs in the sandbox. If they cannot be applied or verified, the sandbox MUST
NOT start. If they stop being in place while sandboxes are running, the
sandbox driver MUST stop those sandboxes.

## SBX-016: Workspace disk limit

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

The disk space a sandbox can use, including its workspace, MUST be limited to
a size configurable by the instance admin, on common host filesystems such as
ext4.

## SBX-017: Supported gVisor release

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The sandbox driver MUST refuse to start sandboxes when the installed gVisor
release is older than the minimum release documented by the project, and MUST
tell the instance admin how to install a supported release from gVisor's
official repository.

## SBX-018: Ephemeral sandboxes

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

When a sandbox stops, for inactivity or on request, its container MUST be
removed, so that the next command runs in a new one from the sandbox image:
processes, installed software and every file outside `/workspace` are gone.
Commands MUST start in a scratch folder, `/scratch`, outside the workspace
(ADR-0076). A sandbox MUST be stopped when the run it serves ends, and the
driver MUST stop every sandbox when it starts (ADR-0078).

Rationale: anything planted outside the workspace must not outlive the
answer that planted it (T-33), and only what was deliberately kept is
persistent.

## SBX-019: Workspace quota

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

Each workspace MUST have a quota, configurable by the instance admin. After
every command, the driver MUST report the workspace's size and quota, and
the command's result MUST tell the agent when the workspace uses more than
80% of its quota, or exceeds it (ADR-0076). Hard disk limits are SBX-016.

## SBX-020: Workspace export and import

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

The sandbox driver MUST be able to stream a conversation's workspace as a tar
archive, and to replace the workspace of a stopped sandbox with one, for
backups (ADR-0077). The import MUST NOT run anything from the archive, and
MUST refuse entries that would be written outside the workspace, such as
absolute paths, `..` segments, links and device files.
