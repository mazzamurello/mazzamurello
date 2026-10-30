# ADR-0021: Enforce sandbox egress on the host with a dedicated nftables table

- **Status:** Accepted
- **Date:** 2026-10-30
- **Deciders:** @tapionx
- **Related:** ADR-0010, ADR-0022, ADR-0023, SBX-004, SBX-005, SBX-006, SBX-007, SBX-013, SBX-015

## Context

ADR-0010 requires that sandboxes reach the internet but nothing local:
private, loopback, link-local, CGNAT and multicast ranges, IPv6 local
ranges, and the host's own addresses (SBX-005), nor other sandboxes
(SBX-006). This ADR decides how.

The sandbox must stay capable: package managers, `git` over SSH and
arbitrary tools must work, so restricting traffic to proxy-aware protocols is
not acceptable. Sandboxes run under gVisor (ADR-0023), whose kernel
(the Sentry) runs its own network stack and exchanges raw frames with the
outside through an `AF_PACKET` socket.

Three designs were tested with spikes before this decision:

| Spike | Design | Result |
|---|---|---|
| v1, 2026-10-30, Debian 12, Intel N95, gVisor `release-20261026.0` | A network sidecar sharing the sandbox's network namespace, with `nftables` rules in that namespace | **Failed.** The gVisor sandbox reached the host's LAN address and the bridge gateway: its frames bypass the namespace's netfilter. Docker's embedded DNS (`127.0.0.11`) was unreachable from gVisor |
| v2, 2026-10-30, Ubuntu 26.04, local | A router container as the only gateway of a per-sandbox Docker `--internal` network | **Failed.** Docker drops on the host every packet whose destination is outside an internal network's subnet, so traffic never reached the router. Using a normal network instead would let a compromised Sentry bypass the router through the host |
| v3, 2026-10-30, Ubuntu 26.04, AMD Ryzen 9 5950X, **no `/dev/kvm`**, gVisor `release-20261026.0` | A dedicated `nftables` table on the host matching only the sandbox bridge | **Passed.** Internet by name and IP and public DNS worked. Host LAN address, `docker0`, the sandbox bridge gateway, another sandbox and IPv6 were blocked, each verified against a control container that could reach them. A container with `NET_ADMIN` and raw sockets that rewrote its own routes, emulating a compromised sandbox kernel, was equally blocked. Without the table the sandbox reached the LAN, proving the table is what blocks it |

This matches the position of the gVisor maintainers, who do not treat the
Sentry as a trust boundary for network policy: enforcement belongs outside it.

## Decision

We will enforce sandbox egress **in the host kernel**, with a dedicated
`nftables` table owned by the project.

1. All sandboxes attach to one **sandbox bridge** with a fixed interface name,
   created by the sandbox driver, with inter-container communication and
   IPv6 disabled.
2. A **network guard** container installs the table `inet mazzamurello` on the
   host. It runs only project code, with host networking and the
   `NET_ADMIN` capability, and no other privileges or mounts.
3. The table matches **only traffic entering from the sandbox bridge**:
   - forwarded traffic to every range of SBX-005 is dropped;
   - all IPv6 traffic from the bridge is dropped (SBX-013);
   - all traffic from the bridge addressed to the host itself is dropped,
     whatever the host address;
   - everything else is left to the host's normal processing, so any
     protocol to public addresses works (SBX-004).
4. The table is separate from Docker's rules and from firewall managers such
   as firewalld or ufw, and never modifies them. In `nftables` a drop in any
   table is final, so other tables cannot override it.
5. The rules live only in kernel memory: the network guard installs them at
   startup and reinstalls them if they disappear; uninstalling Mazzamurello
   removes them.
6. The sandbox driver starts a sandbox only after verifying that the table is
   in place, and stops running sandboxes if it disappears (SBX-015).
7. Sandboxes resolve names through a resolver chosen by the instance, written
   into the sandbox's `resolv.conf` by the driver (SBX-007), because gVisor
   cannot use Docker's embedded DNS.

## Consequences

- Egress restrictions hold even if the sandbox kernel is compromised: they are
  outside the attacker's reach.
- Mazzamurello adds state to the host firewall, limited to one clearly named
  table. Docker itself already manages host firewall rules; installing gVisor
  is a host change in any case.
- The network guard is a privileged infrastructure component and becomes
  security-critical: minimal image, pinned, covered by security tests.
- A sandbox can still send its own workspace data to the internet; this
  residual risk is accepted (threat model).
- Still to verify on a real cloud VM: blocking of the metadata endpoint
  `169.254.169.254`, which no test host exposed. It is covered by the blocked
  ranges and must be part of the security tests (SBX-005).

## Alternatives considered

- **Network sidecar sharing the sandbox's namespace** (spike v1): bypassed by
  gVisor's `AF_PACKET` networking.
- **Router container on a Docker internal network** (spike v2): blocked by
  Docker's internal-network rules; on a normal network, bypassable.
- **Rules in Docker's `DOCKER-USER` chain:** works, but mixes our rules into
  Docker's chains and is fragile across `iptables` variants and firewall
  managers. A separate table achieves the same with clean ownership.
- **Egress proxy only:** breaks every non-proxy-aware tool.
- **gVisor's own netfilter emulation (`--reproduce-nftables`):** enforced
  inside the Sentry, which is not trusted for this.
- **gVisor `--network-proxy-path`:** experimental, and would require writing a
  user-space network stack with filtering.
