# AUTH — Authentication and accounts

How people sign in and how accounts are created.

## AUTH-001: Local accounts

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The system MUST support local accounts with passwords hashed using Argon2id.
Passwords MUST never be logged or stored in reversible form.

## AUTH-002: Accounts created by administrators

- **Status:** draft
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

User accounts MUST be created by a tenant admin or the instance admin. Public
self-registration MUST be disabled by default.

## AUTH-003: OpenID Connect login

- **Status:** draft
- **Priority:** SHOULD
- **Phase:** 2
- **Verification:** integration

The system SHOULD support signing in through an external OpenID Connect
provider (e.g. a self-hosted identity provider), mapped to existing accounts.
