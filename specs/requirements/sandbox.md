# SBX — Sandbox and network isolation

Where and how user and agent code runs. Background: ADR-0010, threat model
T-03 to T-07.

## SBX-001: One sandbox per user

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Each user MUST have their own sandbox. A sandbox MUST NOT be shared between
users, and code run on behalf of a user MUST run only in that user's sandbox.

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

Each sandbox MUST have a persistent workspace that survives sandbox restarts
and re-creation, so that installed software and files persist for the user.

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

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

The control plane MUST be able to place files into a user's workspace and
retrieve files from it through the sandbox driver, streamed and subject to
size limits configurable by the instance admin, so that the assistant can
work on files provided by the user and return the files it produces.

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
