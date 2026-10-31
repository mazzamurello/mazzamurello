# ADR-0047: Login rate limits, case-insensitive usernames and the first administrator's role

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0025, ADR-0046, AUTH-001, AUTH-006, AUTH-007, AUTH-008

## Context

Writing the migrations for the database contract surfaced three gaps:

1. AUTH-006 requires login attempts to be rate-limited per account and per
   source address, but no limits, window or behavior are specified.
   `auth_record_login_attempt` cannot be written without them.
2. Usernames are unique across the instance, but whether `Alice` and `alice`
   are the same account is not stated. It matters for login, for uniqueness and
   for counting attempts per account.
3. `bootstrap_instance` creates the first instance admin, but not their role
   in the first tenant. A member could never become a tenant admin, since
   AUTH-008 forbids users from raising their own privileges.

Families often share one home address, so a per-address limit that is too
tight locks out a whole household after a child mistypes a few times.

## Decision

1. **Rate limits.** Only failed attempts count. An attempt is refused when, in
   the 15 minutes before it, 5 failed attempts were recorded for the same
   username, ignoring case, or 20 failed attempts from the same source address.
   A refused attempt is not recorded, so a refusal never extends itself, and
   the answer to it does not depend on whether the password was right. The
   delay before a retry is the time until the oldest counted failure leaves
   the window. Attempts older than the window are deleted.
2. **Case-insensitive usernames.** Usernames are stored as entered, unique
   ignoring case, and matched ignoring case at login and when counting
   attempts.
3. **First administrator.** The user created by `bootstrap_instance` is both
   instance admin and tenant admin of the first tenant.

## Consequences

- An attacker gets at most 5 guesses per account every 15 minutes, and at
  most 20 per address across all accounts.
- An attacker can keep an account locked by failing on purpose every few
  minutes. The per-address limit bounds this from one address; a session
  already open on a device is not affected (ADR-0025).
- The limits are fixed for phase 0; making them configurable can come later
  without changing the rule.
- Tests can check the limits exactly.

## Alternatives considered

- **10 per account and 50 per address:** kinder to shared addresses, but
  doubles the guesses an attacker gets.
- **Limits set by the instance admin from the start:** more flexible, but
  adds configuration and its validation before anyone has asked for it.
- **Recording refused attempts as failures:** stops guessing as well, but
  any steady stream of attempts would keep an account locked forever.
- **Case-sensitive usernames:** what the contract literally said, but
  `Alice` and `alice` would be two accounts, and mobile keyboards that
  capitalize the first letter would make logins fail.
