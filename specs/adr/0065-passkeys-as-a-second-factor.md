# ADR-0065: Passkeys as a second factor

- **Status:** Proposed
- **Date:** 2026-11-02
- **Deciders:** @tapionx
- **Related:** ADR-0025, ADR-0047, AUTH-001, AUTH-006, AUTH-010

## Context

Accounts are protected by a password and rate limits (AUTH-001, AUTH-006). A
household instance reachable from the internet, and soon able to act on the
household's machines, deserves a stronger sign-in. Phones and laptops can
verify their user with a fingerprint or a face and prove it with a passkey,
through WebAuthn, which installed web apps can use. A second factor that can
be lost must not lock its owner out.

## Decision

1. **Passkeys strengthen the password,** they do not replace it. A user may
   register any number of passkeys; once they have one, signing in needs the
   password and a passkey.
2. **Recovery by an administrator.** A tenant admin can remove the passkeys of
   a user of their tenant; the instance admin's are removed by an operator
   command on the server, like `setup`. No recovery codes: in a household the
   admin is near, and codes are one more secret to keep.
3. **Not for approvals.** Approving a tool call stays a button: asking for a
   fingerprint on every call would make approvals a chore.

## Consequences

- A stolen password alone no longer opens an account that has a passkey.
- Registering a second passkey, such as on a laptop, is the user's protection
  against losing their phone.
- The tenant admin can remove a member's second factor, which the threat model
  accepts: they already manage the member's account (AUTH-008).

## Alternatives considered

- **Passkeys instead of passwords:** simpler sign-in, but losing every passkey
  would lose the account.
- **A fingerprint for every approval:** binds an approval to the person, at the
  cost of a gesture per tool call.
- **Recovery codes:** work without an admin, but must be stored safely by each
  user.
