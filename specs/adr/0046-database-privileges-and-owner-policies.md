# ADR-0046: Database privileges, owner policies and guarded user changes

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0009, ADR-0025, ADR-0041, ADR-0042, ADR-0045, AUTH-001, AUTH-004, AUTH-006, AUTH-007, TEN-002, TEN-003, TEN-004, TEN-006

## Context

The first tests of tenant isolation were run against a throwaway schema
written from the database contract. Three gaps appeared:

1. Row-level security is forced on every table, so it also applies to the
   table owner. The pre-authentication functions run as `mzm_owner` before any
   request context exists: as written, `auth_find_login` sees no users and
   `auth_record_login_attempt` cannot write to `login_attempts`, which has no
   policies.
2. The `users` policy lets users update their own row, with no limit on the
   columns: a member could set their own `role` to `tenant_admin`, or
   `instance_admin` to true. A tenant admin could also create an instance
   admin.
3. Foreign keys between private tables include the tenant but not the owner,
   so a user could attach their own rows, such as a run, to another user's
   conversation in the same tenant. Nothing leaks, since row-level security
   hides those rows from the other user, but the data is wrong.

The contract also did not list the privileges of `mzm_app`, although TEN-004
requires it to hold only the listed ones.

## Decision

1. **Owner policies.** The tables the pre-authentication functions use get
   policies `TO mzm_owner` for exactly the operations those functions need,
   with no condition. They are the only policies for `mzm_owner`; all others
   are `TO mzm_app`. `mzm_owner` stays a role that no running service
   connects as, so these policies open the tables only to the functions'
   code and to migrations.
2. **Guarded user changes.** `mzm_app` may update only `display_name`,
   `password_hash`, `role` and `disabled_at` of `users`. Changing `role` or
   `disabled_at` requires a tenant admin context, enforced by a
   `BEFORE UPDATE` trigger, since policies cannot compare old and new values.
   Only an instance admin may insert a user with `instance_admin` set.
3. **Owner in private foreign keys.** Every foreign key between private tables
   includes the owner column next to `tenant_id`. Foreign keys that set null
   on delete name the column they clear.
4. **Listed privileges.** The contract lists every privilege of `mzm_app`.
   Stored messages and cost ledger entries are insert-only for the
   application (ADR-0041, ADR-0042); rows removed or detached when a
   conversation is deleted are handled by foreign keys.

## Consequences

- The pre-authentication functions work under forced row-level security
  without a role that bypasses it.
- Data migrations that touch tables without an owner policy must lift forced
  row-level security for their duration, inside the migration's transaction.
- Design tests can check the exact privileges and policies, not only the
  absence of the dangerous ones.
- Private tables need unique keys on (`tenant_id`, owner, `id`) for the
  foreign keys to reference.

## Alternatives considered

- **A separate role with `BYPASSRLS` owning the functions:** shorter policies,
  but a role that bypasses every policy, on every table, is exactly what
  TEN-004 keeps out of reach.
- **Security-definer functions for every change to `users`:** works, but
  moves ordinary updates of a user's own name out of plain SQL for a rule
  that a trigger states in a few lines.
- **Column privileges alone:** cannot tell a tenant admin from a member,
  since both connect as `mzm_app`.
