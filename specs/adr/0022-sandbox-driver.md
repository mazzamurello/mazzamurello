# ADR-0022: A minimal sandbox driver as the only holder of container runtime access

- **Status:** Accepted
- **Date:** 2026-10-30
- **Deciders:** @tapionx
- **Related:** ADR-0010, ADR-0021, ADR-0023, SBX-001, SBX-002, SBX-003, SBX-008, SBX-009, SBX-010, SBX-011, SBX-012, SBX-014, SBX-015, SBX-016, SBX-017

## Context

Access to the Docker API is equivalent to root on the host. Whoever holds it
is the most sensitive component of the system. ADR-0010 and SBX-009 require
that only a dedicated sandbox driver has it, and that the control plane talks
to sandboxes only through the driver.

Users need the sandbox to do real work on their files: convert documents,
generate and read PDFs, process audio, video and photos, and return the
results. Files must therefore move between the control plane and a user's
workspace.

## Decision

We will build the sandbox driver as a separate service, `sandboxd`:

1. **Sole holder of container runtime access.** It is the only container
   with access to the Docker API. The control plane never mounts the Docker
   socket (SBX-009).
2. **Internal only.** It listens only on an internal network shared with the
   control plane, is never published on a host port (OPS-003), and
   authenticates every request with a secret shared with the control plane
   (phase 0); mutual TLS may replace the secret later.
3. **Minimal API**, specified in `specs/contracts/sandbox-driver.yaml`:

   | Operation | Purpose |
   |---|---|
   | `health` | Report readiness, the gVisor release and the state of the egress rules |
   | `ensure` | Create or wake the sandbox of a user (idempotent) |
   | `exec` | Run a command, stream stdout and stderr, return the exit code, enforce a timeout |
   | `put_file` | Stream a file into the user's workspace, with a size limit |
   | `get_file` | Stream a file out of the user's workspace, with a size limit |
   | `stop` | Stop the sandbox of a user |

4. **No knowledge of users or permissions.** The driver receives a tenant ID
   and a user ID from the control plane, which has already authorized the
   request. It derives container and volume names from them.
5. **Fixed, non-negotiable policy.** Whatever the request, the driver only
   creates containers with:
   - the `runsc` runtime (ADR-0023);
   - the project's sandbox image;
   - the sandbox bridge of ADR-0021, and a `resolv.conf` pointing to the
     instance's resolver (SBX-007);
   - limits on CPU, memory and processes (`RLIMIT_NPROC`, since Docker's
     `--pids-limit` does not count processes inside gVisor) and an execution
     timeout (SBX-011);
   - no privileged mode, no added capabilities, no host namespaces and no host
     mounts other than the user's workspace (SBX-012);
   - no credentials (SBX-008).

   The API offers no parameter to change any of this, so even a compromised
   control plane cannot obtain a privileged container.
6. **One long-lived sandbox per user** (SBX-001), stopped after a period of
   inactivity and woken up by the next `ensure`. Commands run inside it with
   `exec`, which keeps installed software and avoids starting a container per
   command.
7. **Workspaces with a disk limit** (SBX-010, SBX-016). Docker cannot limit a
   container's disk usage on common filesystems such as ext4 (verified by the
   spike: `--storage-opt size` is unsupported). Each workspace is therefore a
   fixed-size filesystem image, mounted as a Docker volume. The exact
   mechanism is validated in phase 1, together with persistent workspaces.
8. **Fail closed** (SBX-003, SBX-015, SBX-017). Before reporting itself
   healthy, and before starting any sandbox, the driver checks that:
   - `runsc` is registered with Docker and not older than the minimum release;
   - the egress table of ADR-0021 is in place;
   - a canary sandbox really runs under gVisor and cannot reach a blocked
     address.

   It re-checks the egress table periodically and stops running sandboxes if
   it disappears.
9. **A capable base image.** The sandbox image includes common tools for
   documents, media and data (for example Python, ffmpeg, poppler, ImageMagick,
   pandoc), and users can install more, as root inside the sandbox.
10. **Small and boring code**, with few dependencies, so that it can be
    reviewed thoroughly; it never interprets user content beyond what it
    executes or transfers.

## Consequences

- A compromise of the control plane does not grant root on the host.
- The driver is a single point of failure for all execution; it must be
  simple and well tested, including its startup self-test.
- File transfer through the driver adds a hop, which is acceptable for
  documents and media of household scale.

## Alternatives considered

- **Docker socket in the control plane:** the largest component would hold
  root-equivalent access.
- **One container per command:** stronger isolation between commands, but
  slow and loses installed software.
- **A per-sandbox network sidecar:** rejected by ADR-0021 after spike v1.
- **A filtering proxy in front of the Docker socket, or a dedicated rootless
  Docker daemon for sandboxes:** valuable defense in depth, considered for a
  later ADR; not needed to meet the phase 0 requirements.
