# ADR-0023: gVisor as the single isolation runtime

- **Status:** Accepted
- **Date:** 2026-10-30
- **Deciders:** @tapionx
- **Related:** ADR-0007, ADR-0010, ADR-0021, ADR-0022, SBX-002, SBX-017, OPS-002, OPS-009

## Context

ADR-0010 chose gVisor by default and left Kata Containers as an option behind
a provider interface. Since then, two constraints became explicit:

- **Mazzamurello must be self-hostable on a cloud VM.** Many VPS offerings
  do not expose hardware virtualization (`/dev/kvm`) to their guests; nested
  virtualization is available only on some providers and instance types.
- **The project ships one sandbox implementation.** Supporting several
  runtimes multiplies testing, documentation and security review, and
  fragments a small project.

Every microVM technology evaluated — Firecracker, Cloud Hypervisor, Kata
Containers, libkrun and the products built on it (microsandbox, smolvm,
BoxLite) — requires KVM. Some of them, notably microsandbox, offer excellent
built-in egress controls, but cannot run where KVM is absent.

gVisor does not require hardware virtualization: its default platform
(`systrap`) relies on seccomp. Spikes on 2026-10-30 confirmed, on a Debian 12
server and on an Ubuntu 26.04 machine without `/dev/kvm`, that the target
workloads run under gVisor (apt, pip, ffmpeg, ImageMagick, poppler,
LibreOffice, matplotlib) with acceptable overhead: CPU-bound work at native
speed, up to about 70% slower for syscall-heavy steps such as package
installation and LibreOffice startup.

## Decision

We will use **gVisor (`runsc`) as the only isolation runtime** for sandboxes.

- Hardware virtualization is **not** required. Where `/dev/kvm` is available,
  administrators may configure gVisor's KVM platform for better performance;
  this is a runtime option of the same runtime, not a different provider.
- gVisor must come from the **project's official repository**: distribution
  packages may be years old (Debian 12 ships a 2022 snapshot). The sandbox
  driver refuses to start below a documented minimum release (SBX-017).
- The provider interface of ADR-0022 remains an internal design boundary, with
  a single implementation.
- Egress enforcement follows ADR-0021, because gVisor's networking bypasses
  netfilter rules in the sandbox's network namespace.

This decision amends ADR-0010 on one point: Kata Containers is no longer a
supported option.

## Consequences

- One runtime to install, document, test and secure.
- Runs on bare metal, home servers and cloud VMs alike.
- Isolation is that of a user-space kernel, weaker than a dedicated guest
  kernel per sandbox; this trade-off is accepted for portability.
- Under gVisor, Docker's `--pids-limit` does not count sandbox processes
  (they are emulated by the Sentry); process limits use `RLIMIT_NPROC`, which
  gVisor enforces even for root inside the sandbox (ADR-0022).

## Alternatives considered

- **microsandbox (libkrun microVMs):** strongest out-of-the-box fit — its
  default egress policy blocks private ranges, host, metadata and
  `100.64.0.0/10` outside the guest — but requires KVM and is beta software.
  To be reconsidered if KVM becomes a reasonable requirement.
- **A custom layer on libkrun, Firecracker or Cloud Hypervisor:** requires KVM,
  and the glue (images, guest agent, networking) would be security-critical
  code to maintain.
- **Two providers (microVM where KVM exists, gVisor elsewhere):** rejected to
  avoid fragmentation.
- **Plain containers with namespaces and seccomp:** too weak for code written
  by a model reading untrusted content.
