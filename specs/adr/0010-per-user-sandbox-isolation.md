# ADR-0010: Per-user sandboxes with a strong isolation runtime and internet-only egress

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** ADR-0007, ADR-0011, SBX-001, SBX-002, SBX-003, SBX-005, SBX-006, SBX-008, SBX-009, SBX-011, SBX-012

## Context

The assistant must be able to do a lot: browse the internet, install
software, run programs. That code is written by a model that reads untrusted
content, so it must be treated as code written by a stranger. It runs on a
server that sits inside a home network full of devices that trust anything
on the LAN (routers, NAS shares, cameras, home automation, unauthenticated
local services such as model servers).

Plain containers share the host kernel and, on a default Docker bridge, can
reach each other and the LAN.

## Decision

We will:

1. Give **each user their own sandbox**, never shared, with a persistent
   workspace and resource limits.
2. Run sandboxes under a **strong isolation runtime: gVisor by default**,
   with Kata Containers (lightweight VMs) as a supported option for operators
   hosting untrusted tenants. Providers are pluggable behind one interface
   (Docker with gVisor, Docker with Kata, Kubernetes with the agent-sandbox
   controller later).
3. **Fail closed:** if the configured isolation runtime is unavailable, no
   sandbox starts. There is no silent fallback to plain containers.
4. Allow **internet egress** and deny everything local: private, loopback,
   link-local, CGNAT (including VPN overlays such as Tailscale), multicast,
   IPv6 unique-local and link-local ranges, and the host's own addresses.
   Sandboxes cannot reach each other.
5. Keep **no secrets** inside sandboxes. Credentials stay in the control
   plane; the agent uses them only through mediated tools (ADR-0012).
6. Give the **container runtime only to a dedicated sandbox driver** with a
   minimal, authenticated API. The control plane never holds the Docker
   socket.
7. Allow root *inside* the sandbox (so users can install software), but never
   privileged containers, host namespaces or host mounts.

Access to household services (e.g. home automation) happens only through
mediated tools in the control plane, never through the sandbox network.

## Consequences

- A compromised sandbox can damage only its own workspace, which holds no
  secrets. It can still send that workspace's data to the internet; this is
  an accepted residual risk.
- Supported hosts must provide gVisor (or Kata); some NAS platforms and
  Docker Desktop are therefore unsupported.
- Network policy is implemented with host firewall rules (e.g. the
  `DOCKER-USER` chain) or Kubernetes network policies, and verified by
  security tests from inside a sandbox.

## Alternatives considered

- **Plain Docker containers:** shared kernel, too weak for code written by a
  model reading untrusted content.
- **One shared container with a Linux user per person:** explicitly not a
  security boundary.
- **No network access in the sandbox:** safe, but prevents most of what
  makes the assistant useful.
- **Third-party hosted sandboxes:** contrary to keeping data in the house.
