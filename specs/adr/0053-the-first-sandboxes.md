# ADR-0053: The first sandboxes

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0021, ADR-0022, ADR-0023, ADR-0035, ADR-0050, ADR-0052, AGT-011, AGT-014, SBX-003, SBX-007, SBX-010, SBX-011, SBX-015, SBX-017

## Context

ADR-0021, ADR-0022, ADR-0023 and ADR-0035 decide how sandboxes are isolated
and reached. Implementing them needs the details they leave open: how the
driver, which has no network privileges, knows that the egress table is in
place; the defaults of the limits and of the resolver; the minimum gVisor
release; where workspaces live; and how the processes are configured and
tested.

## Decision

1. **The network guard reports through its container health.** It checks the
   table every second and reinstalls it when it is missing (ADR-0021). Its
   Docker health check fails while the table is missing and for 10 seconds
   after it was last found missing. The driver reads that health through the
   Docker API it already holds, every 2 seconds: when the guard is not
   healthy, the driver stops every running sandbox and refuses new ones until
   the guard is healthy again and a new canary passes (SBX-015). No volume or
   socket is shared between them.
2. **The canary** is a sandbox like any other, started at driver startup and
   after every recovery. It must run under `runsc`, reach no address of the
   host through the sandbox bridge, and fail to connect to `10.0.0.1`
   (SBX-003). The driver accepts requests only after it passes.
3. **The sandbox bridge** is the Docker network `mazzamurello-sandboxes`, with
   the interface `mzmsbx0`, inter-container communication and IPv6 disabled,
   created by the driver. The network guard's table matches `mzmsbx0`.
4. **Defaults**, all configurable by the instance admin
   ([configuration contract](../contracts/configuration.md)): 1 CPU, 1 GiB of
   memory, 512 processes (`RLIMIT_NPROC`), 300 seconds per command, 1 MiB of
   command output returned, and sandboxes stopped after 30 idle minutes. The
   default resolver is Quad9, `9.9.9.9`, a non-profit resolver that does not
   log client addresses.
5. **Minimum gVisor release:** `release-20261026.0`, the release the project
   is tested with (SBX-017). Raising it is a decision recorded in the
   configuration contract.
6. **Workspaces** are Docker volumes, one per user, mounted at `/workspace`,
   the working directory. They survive stopping and re-creating the sandbox
   (SBX-010). A disk limit (SBX-016) comes later.
7. **Commands** run as root inside the sandbox, in a new process group. When
   a command exceeds its timeout, the driver kills its process group and
   reports the timeout.
8. **The agent's workspace tools** are the harness's shell and filesystem
   capabilities over a workspace backend that calls the driver, with the
   harness's tool output limits (AGT-011, AGT-014, ADR-0035).
9. **Images** are built from `deploy/images/`: `sandbox`, a Debian image with
   a shell, coreutils, Python, curl and git; and `netguard`, with `nft` and
   the network guard. The driver uses the sandbox image named in its
   configuration and nothing else.
10. **Tests** build both images, start the network guard as a container with
    host networking and `NET_ADMIN`, and the driver as a process with access
    to Docker, as the [test harness](../contracts/test-harness.md) describes.
    CI installs gVisor from its official repository so that the sandbox tests
    run on every pull request.

## Consequences

- A table removed by hand stops every sandbox within a few seconds, even
  though the guard restores it at once; sandboxes come back with the next
  `ensure` after a new canary.
- The driver depends on the guard's container name, given in its
  configuration.
- Root inside the sandbox is confined by gVisor and by the limits, not by a
  user account.
- Running the tests installs, for their duration, the project's `nftables`
  table on the machine that runs them, matching only the sandbox bridge.

## Alternatives considered

- **A status file on a volume shared by the guard and the driver:** precise,
  but adds a mount to the guard, which ADR-0021 keeps without mounts.
- **Probing a blocked address from the canary every few seconds:** checks the
  outcome rather than the rules, but needs a listener on the host to tell
  "blocked" from "nothing listening", and costs a command every probe.
- **2 CPUs, 4 GiB and 1024 processes by default:** roomier for building
  software, but a household server may host several sandboxes at once.
