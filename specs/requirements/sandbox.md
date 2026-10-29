# SBX — Sandbox and network isolation

Where and how user and agent code runs. Background: ADR-0010, threat model
T-03 to T-07.

## SBX-001: One sandbox per user

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Each user MUST have their own sandbox. A sandbox MUST NOT be shared between
users, and code run on behalf of a user MUST run only in that user's sandbox.

## SBX-002: Strong isolation runtime

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Sandboxes MUST run under an isolation runtime stronger than a plain
container: gVisor by default, Kata Containers as a supported option. The
runtime MUST be selected through a provider interface so that new providers
can be added without changing the control plane.

## SBX-003: Fail closed without isolation

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

If the configured isolation runtime is unavailable, the system MUST refuse to
start sandboxes and MUST report the reason to the instance admin. It MUST NOT
fall back to a weaker runtime.

## SBX-004: Internet access

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

A sandbox MUST be able to reach public internet addresses, so that the agent
can browse, download and install software.

## SBX-005: No access to local networks

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security

A sandbox MUST NOT be able to open connections to: `0.0.0.0/8`, `10.0.0.0/8`,
`100.64.0.0/10`, `127.0.0.0/8`, `169.254.0.0/16`, `172.16.0.0/12`,
`192.168.0.0/16`, `224.0.0.0/4`, `::1/128`, `fc00::/7`, `fe80::/10`, `ff00::/8`,
or any address of the host. Security tests MUST verify this from inside a
running sandbox.

## SBX-006: No sandbox-to-sandbox traffic

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security

A sandbox MUST NOT be able to reach any other sandbox over the network.

## SBX-007: Isolated name resolution

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 1
- **Verification:** security

Sandboxes SHOULD use a resolver that does not resolve names internal to the
host or the household network.

## SBX-008: No secrets in sandboxes

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security

A sandbox MUST NOT contain credentials of any kind — in environment
variables, files, mounts or images — other than credentials the user has
explicitly placed in their own workspace.

## SBX-009: Container runtime confined to the sandbox driver

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

Only the sandbox driver MUST have access to the container runtime. The
control plane MUST NOT mount the container runtime socket and MUST interact
with sandboxes only through the sandbox driver's authenticated API.

## SBX-010: Persistent workspace

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

Each sandbox MUST have a persistent workspace that survives sandbox restarts
and re-creation, so that installed software and files persist for the user.

## SBX-011: Resource limits

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Each sandbox MUST be limited in CPU, memory, disk usage, number of processes
and execution time, with limits configurable by the instance admin.

## SBX-012: No privileged sandboxes

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

Sandboxes MUST NOT run privileged, share host namespaces or mount host paths
other than their own workspace. Root inside the sandbox is allowed.
