# ADR-0048: Disabling an account revokes its sessions

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0025, ADR-0046, AUTH-004, AUTH-008, AUTH-009

## Context

A tenant admin disables an account by setting `users.disabled_at`. Token
verification on every request, `auth_find_session`, does not report whether
the user is disabled, so a disabled user's open sessions keep working until
they expire or are revoked. Revoking them is not possible for the tenant
admin: row-level security limits `device_sessions` to the sessions of the
current user.

## Decision

We will revoke every session of an account when it is disabled, in the
database, in the same transaction:

- An `AFTER UPDATE` trigger on `users` sets `revoked_at` on every unrevoked
  session of the user when `disabled_at` changes from null to a value.
- Its function is `SECURITY DEFINER`, owned by `mzm_owner`, with a fixed
  `search_path`, and not executable by `mzm_app`. It works through the
  existing owner policies on `device_sessions` (ADR-0046).
- Re-enabling an account leaves its sessions revoked; the user signs in again.

## Consequences

- A disabled account cannot be used from any device from the moment the
  change commits, whatever the server does.
- Tenant admins still cannot see or change other users' sessions directly.
- There is one more `SECURITY DEFINER` function, listed in the contract and
  checked by the design tests like the others.

## Alternatives considered

- **Report `disabled` from `auth_find_session` and reject in the server:**
  equally effective while the server checks it, but every new path that
  verifies tokens must remember to; the sessions would also come back to life
  when the account is re-enabled.
- **A policy letting tenant admins revoke sessions in their tenant:** would
  also expose those sessions, device names included, to tenant admins.
- **Revoke from the server, in the request that disables the account:**
  blocked by row-level security, for the reason above.
