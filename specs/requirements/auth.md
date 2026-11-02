# AUTH — Authentication and accounts

How people sign in and how accounts are created.

## AUTH-001: Local accounts

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The system MUST support local accounts with passwords hashed using Argon2id.
Passwords MUST never be logged or stored in reversible form.

## AUTH-002: Accounts created by administrators

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

User accounts MUST be created by a tenant admin or the instance admin. Public
self-registration MUST be disabled by default.

## AUTH-003: OpenID Connect login

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 3
- **Verification:** integration

The system SHOULD support signing in through an external OpenID Connect
provider (e.g. a self-hosted identity provider), mapped to existing accounts.

## AUTH-004: Revocable device sessions

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Authentication MUST use opaque, random session tokens of at least 256 bits,
stored only as hashes, each bound to one user and one device and carrying an
expiry. A user MUST be able to list their sessions and revoke any of them, and
a revoked or expired token MUST be rejected on the next request (ADR-0025).

## AUTH-005: Cookie sessions protected against CSRF

- **Status:** accepted
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security

When a session token is carried in a cookie, the cookie MUST be `HttpOnly`,
`Secure` and `SameSite=Lax`, and every state-changing request authenticated by
cookie MUST also carry a custom request header that cross-site requests cannot
set.

## AUTH-006: Login rate limiting

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

Login attempts MUST be rate-limited per account and per source address.

## AUTH-007: First administrator without default credentials

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The first instance admin MUST be created during setup by an explicit,
one-time command run by whoever operates the instance. The system MUST NOT
ship or accept any default credentials.

## AUTH-008: Privileges changed only by administrators

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security

Changing a user's role, and disabling or re-enabling their account, MUST
require a tenant admin of the user's tenant. Creating an instance admin MUST
require an instance admin. A user MUST NOT be able to raise their own
privileges or re-enable their own account.

## AUTH-009: Disabling an account ends its sessions

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security

Disabling an account MUST revoke every session of that account in the same
change, so that none of its tokens is accepted afterwards. Re-enabling the
account MUST NOT restore any session.

## AUTH-010: Passkeys as a second factor

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration, security

A user MUST be able to register any number of passkeys (WebAuthn), including
ones that use the device's biometrics. Once a user has a passkey, signing in
MUST require their password and one of their passkeys. A tenant admin MUST be
able to remove the passkeys of a user of their tenant, and an operator
command MUST be able to remove the instance admin's, so that a lost passkey
never locks a user out for good (ADR-0065).

