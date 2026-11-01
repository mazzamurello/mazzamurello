# OPS — Deployment and operations

How Mazzamurello is installed, exposed, upgraded and backed up. Background:
ADR-0007, ADR-0018.

## OPS-001: Docker Compose deployment

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** e2e

The system MUST be deployable on a single host with Docker Compose, with
every component running in a container, from a documented configuration file.

## OPS-002: Supported platforms are checked

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The supported platforms are Linux on x86_64 and arm64 with Docker Engine and
gVisor. At startup the system MUST check the platform, the availability of the
isolation runtime and the egress rules, and MUST report unsupported
configurations clearly.

## OPS-003: Minimal exposed surface

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

By default the deployment MUST publish a single HTTP entry point. Databases,
queues, the sandbox driver, model servers and other internal services MUST
NOT be published on host ports.

## OPS-004: No host execution

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

Components MUST NOT execute commands on the host on behalf of users or the
agent. All such execution MUST happen in sandboxes.

## OPS-005: Upgrades across versions

- **Status:** draft
- **Priority:** MUST
- **Phase:** 2
- **Verification:** e2e

Upgrading from any earlier released version to the current one MUST succeed
without manual data migration. CI MUST test upgrades from every supported
earlier version.

## OPS-006: Backup and restore

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** e2e

Backup and restore of an instance MUST be documented, and CI MUST verify that
a backup can be restored into a working instance.

## OPS-007: Verifiable release images

- **Status:** draft
- **Priority:** MUST
- **Phase:** 2
- **Verification:** review

Release container images MUST be published for amd64 and arm64, signed, and
accompanied by a software bill of materials.

## OPS-008: Models are not bundled

- **Status:** draft
- **Priority:** MUST
- **Phase:** 2
- **Verification:** review

Container images MUST NOT include model weights or voice models. They MUST be
downloaded at setup time, with their licenses shown to the instance admin.

## OPS-009: Cloud VMs without hardware virtualization

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** e2e

The system MUST run, with all its isolation guarantees, on a host without
hardware virtualization support (no `/dev/kvm`), such as a cloud VM without
nested virtualization. It MAY use hardware virtualization when available, for
performance only.
