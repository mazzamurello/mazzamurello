# ADR-0011: The instance admin is trusted

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** ADR-0009, ADR-0010

## Context

The person who runs the server has root on it and can, technically, read
everything: the database, the files, the memory of the processes. Protecting
users from the instance admin would require end-to-end encryption with keys
held by users. The agent, however, must read user data to be useful, and
scheduled tasks run while the user is not connected.

## Decision

We will treat the **instance admin as trusted**, as comparable self-hosted
software does (e.g. Immich, Nextcloud), and state this clearly in the
documentation and the threat model.

Isolation guarantees (ADR-0009, ADR-0010) protect users from **each other**,
tenants from **each other**, and the host and network from **sandboxes** —
not users from the admin.

Tenant admins are not instance admins: they manage users, shared spaces and
permissions within their tenant, but they cannot read other users' private
data through the application.

## Consequences

- The design stays simple enough to build and operate.
- Users must trust whoever runs the instance; in a household, that is
  usually a family member. Operators hosting for others must make this
  explicit to their users.
- Per-user encryption with user-held keys remains possible later for
  specific, highly sensitive spaces, through a new ADR.

## Alternatives considered

- **User-held encryption keys for all data:** protects against the admin, but
  breaks server-side agent work and scheduled tasks, and makes key loss
  catastrophic.
