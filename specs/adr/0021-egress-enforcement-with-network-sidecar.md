# ADR-0021: Enforce sandbox egress with a per-sandbox network sidecar

- **Status:** Proposed
- **Date:** 2026-10-30
- **Deciders:** @tapionx
- **Related:** ADR-0010, ADR-0022, SBX-004, SBX-005, SBX-006, SBX-007, SBX-013, SBX-015

## Context

ADR-0010 requires that sandboxes reach the internet but nothing local:
private, loopback, link-local, CGNAT and multicast ranges, IPv6 local
ranges, and the host's own addresses (SBX-005), nor other sandboxes
(SBX-006). It names host firewall rules as one possible mechanism; this ADR
decides the mechanism.

The sandbox must stay capable: package managers, `git` over SSH, media
downloads and arbitrary tools must work, so restricting traffic to
proxy-aware protocols is not acceptable. The mechanism must also work on the
wide variety of Linux hosts self-hosters run, without fighting the host's
own firewall configuration.

## Decision

We will give **every sandbox its own network sidecar**: a minimal container
that owns the sandbox's network namespace and enforces the egress policy
inside that namespace only.

1. The sandbox driver creates the network sidecar first, on a bridge network
   reserved for sandboxes, with inter-container communication disabled and
   IPv6 disabled.
2. The network sidecar runs a fixed, project-built image with `nftables`,
   with the `NET_ADMIN` capability (which is scoped to its own network
   namespace), no host network, no host mounts and no other privileges. It
   executes only project code, never user code.
3. The sidecar installs a ruleset in its namespace that:
   - rejects outbound traffic to every range listed in SBX-005 and to every
     address of the host, except an explicitly allowed resolver (SBX-007);
   - rejects all IPv6 traffic (SBX-013);
   - drops inbound connections not related to an outbound connection;
   - accepts everything else, so any protocol to public addresses works
     (SBX-004).
4. The driver **verifies** the ruleset (reads it back and probes a blocked
   address) before starting the sandbox. Only then does it start the sandbox
   under the isolation runtime, joined to the sidecar's network namespace,
   without `NET_ADMIN`. If any step fails, the sandbox does not start
   (SBX-015).
5. Because the Docker bridge itself lies in a private range, the same rules
   also block the host's bridge address and every other sandbox.
6. Name resolution goes through a resolver chosen by the instance, so that
   sandboxes cannot resolve names of containers or hosts internal to the
   instance or the household (SBX-007). The exact mechanism (dedicated
   resolver container, or a public resolver in phase 0) is fixed after the
   spike, because Docker's embedded DNS on user-defined networks also
   resolves container names.

Future providers use the native equivalent: on Kubernetes, network policies
on the sandbox pods.

## Validation required before acceptance

This ADR stays `Proposed` until a spike on a reference host shows that:

- a gVisor container can join another container's network namespace
  (`--network container:<sidecar>`), which the gVisor documentation does
  not explicitly cover;
- the sidecar's `nftables` rules filter the gVisor sandbox's traffic;
- the sandbox cannot alter or bypass the rules;
- the targets of SBX-005 and SBX-006 are unreachable while the internet is
  reachable;
- the DNS mechanism prevents resolution of internal names.

The spike's results are recorded in this ADR when it is accepted.

## Consequences

- No change to the host's firewall: the mechanism does not depend on
  iptables or nftables variants, firewalld or ufw on the host.
- Any protocol to the internet works inside the sandbox.
- One extra, very small container per running sandbox.
- The sidecar image becomes security-critical: it is minimal, pinned and
  covered by the sandbox security tests.
- A compromised sandbox can still send its own workspace data to the
  internet; this residual risk is accepted (threat model).

## Alternatives considered

- **Host firewall rules (`DOCKER-USER` chain):** requires root on the host,
  interacts badly with Docker's own rules, firewalld and ufw, and traffic to
  the host itself goes through `INPUT`, which is easy to miss.
- **Egress proxy on an internal network:** no host changes and immune to DNS
  rebinding, but only proxy-aware traffic works; `git` over SSH and many
  tools would break.
- **No network in the sandbox:** safe, but removes most of the assistant's
  usefulness.
