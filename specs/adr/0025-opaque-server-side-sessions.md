# ADR-0025: Authenticate clients with opaque server-side sessions

- **Status:** Accepted
- **Date:** 2026-10-30
- **Deciders:** @tapionx
- **Related:** ADR-0016, AUTH-001, AUTH-002, AUTH-004, AUTH-005, AUTH-006

## Context

Clients are a web app (installable PWA), later native mobile apps, and
scripts. The server is a single instance with one database. Tokens must be
revocable at once — a lost phone must lose access immediately — and must not
be readable by JavaScript in the browser, so that a cross-site scripting bug
cannot steal them.

## Decision

We will use **opaque, server-side device sessions**:

1. On login, the server generates a random token (at least 256 bits) and
   stores only its hash, with the user, the device description, creation and
   last-use times and an expiry.
2. **Browsers** receive the token in a cookie marked `HttpOnly`, `Secure` and
   `SameSite=Lax`. State-changing requests authenticated by cookie must also
   carry a custom request header, which cross-site requests cannot set
   (CSRF protection).
3. **Native apps and scripts** send the same token as
   `Authorization: Bearer <token>`.
4. Users can list their sessions and revoke any of them; revocation takes
   effect on the next request. Logout revokes the current session.
5. Login attempts are rate-limited per account and per source address.
6. Passwords are hashed with Argon2id (AUTH-001).

## Consequences

- Revocation is immediate and simple: delete the row.
- Every authenticated request reads the session from the database; at the
  scale of a household or small organization this is negligible.
- One mechanism for every client type, with two transports.

## Alternatives considered

- **JWT access tokens:** stateless verification brings no benefit on a single
  server, and revocation requires the very server-side state JWTs avoid.
- **Tokens in browser storage:** readable by any script running on the page.
