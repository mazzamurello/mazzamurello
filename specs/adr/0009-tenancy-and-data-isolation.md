# ADR-0009: Multi-tenant data model with isolation enforced by PostgreSQL row-level security

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** ADR-0007, ADR-0011, TEN-001, TEN-002, TEN-003, TEN-004, TEN-005, TEN-006, TEN-007, TEN-008

## Context

Inside a family, each member's data must be private: a parent's mail is not
a teenager's business, and vice versa. Isolation between users is therefore
needed even in the simplest installation. Once users are isolated, adding a
tenant level above them costs little and lets the same software serve
several households or a small organization.

Application-level filtering ("remember to add `WHERE tenant_id = …`") fails
the first time someone forgets. Isolation must be enforced below the
application.

## Decision

We will:

1. Organize data as **instance → tenants → users**, with **shared spaces**
   belonging to one tenant. Data is **private by default**; sharing is an
   explicit act.
2. Put `tenant_id` on every tenant-scoped row, and the owning user on every
   private row.
3. Enforce isolation with **PostgreSQL row-level security**, enabled and
   **forced** on every tenant-scoped table.
4. Run the application with a dedicated database role that is not superuser,
   lacks `BYPASSRLS` and does not own the tables. Migrations run with a
   separate owner role.
5. Set the tenant and user context **once per transaction**, from the
   authenticated identity only, using transaction-local settings
   (`set_config(…, true)`). No endpoint builds tenant filters by hand.
6. Partition file storage by tenant and user.
7. Verify all of this with design tests (on the live schema) and security
   tests (cross-user and cross-tenant access attempts through the API).

## Consequences

- A forgotten filter in application code cannot leak data across users or
  tenants.
- Every query runs in a transaction with the right context; connection
  pooling must not leak settings across requests.
- Some operations (instance administration, migrations, backups) need the
  privileged role and are kept outside the request path.

## Alternatives considered

- **Database per tenant:** strong isolation between tenants, but does not
  solve isolation between users inside a tenant, and complicates operations.
- **Application-level filtering only:** one bug away from a data leak.
