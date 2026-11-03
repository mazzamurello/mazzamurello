# DEV — Connected devices

A user's own machines and phone, connected to the instance, offering tools
that run on them: diagnosing a server, installing updates, reading logs,
editing files. Background: ADR-0063.

## DEV-001: Pairing a device to one user

- **Status:** draft
- **Priority:** MUST
- **Phase:** 2
- **Verification:** integration

A user MUST be able to pair a device to their account by confirming, while
signed in, a code the device service shows. A paired device MUST belong to
exactly one user and MUST NOT be shared with or usable by any other user. The
user MUST be able to list their devices and revoke any of them; a revoked
device MUST be disconnected at once and unable to reconnect.

## DEV-002: Outbound connection

- **Status:** draft
- **Priority:** MUST
- **Phase:** 2
- **Verification:** integration

The device service MUST connect to the instance on its own initiative, over
the instance's public endpoint, so that a device never needs an open port.
Tool calls and their results MUST travel over that connection only.

## DEV-003: The device service's tools

- **Status:** draft
- **Priority:** MUST
- **Phase:** 2
- **Verification:** integration

On Linux, the device service MUST offer the tools `run_command`, `read_file`
(with line ranges), `write_file`, `edit_file` (replacing an exact piece of
text), `list_directory`, `find_files` and `search_text`. Output returned to
the instance MUST be bounded like the sandbox's (AGT-014), and the agent's
instructions MUST tell it to search before reading and to read only what it
needs.

## DEV-004: Several devices in one run

- **Status:** draft
- **Priority:** MUST
- **Phase:** 2
- **Verification:** integration

The tools of each connected device of the run's user MUST be offered to the
agent under the device's name, alongside the sandbox's tools, so that one run
can act on the sandbox and on several devices. Devices of other users MUST
NOT be offered.

## DEV-005: A call waits for an offline device

- **Status:** draft
- **Priority:** MUST
- **Phase:** 2
- **Verification:** integration

An approved tool call to a device that is offline MUST wait until the device
reconnects, without a timeout, unless the user gives up on it or answers it
themselves. A conversation with such a call MUST be marked as waiting in the
conversation list.

## DEV-006: Device status

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 2
- **Verification:** integration

A connected device SHOULD report a short status about once a minute: online
and last seen, uptime, operating system, free disk space, and, where
available, temperature and battery. Only the latest status is kept, and only
the device's owner can see it.

## DEV-007: Least privilege by default

- **Status:** draft
- **Priority:** MUST
- **Phase:** 2
- **Verification:** integration

The device service MUST run as a dedicated unprivileged user without `sudo`
by default. Running it with `sudo` rights or as root MUST be an explicit
choice of the device's owner at installation.

## DEV-008: The web app as a device

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 2
- **Verification:** e2e

While open in the foreground, the web app SHOULD act as a device of its user,
reporting its status and offering the tools `current_location`,
`take_photo` and `pick_file`, each subject to the browser's own permissions.

## DEV-009: Platforms

- **Status:** draft
- **Priority:** MUST
- **Phase:** 2
- **Verification:** e2e

The device service MUST support Linux. Support for macOS and Windows MAY
follow later.
