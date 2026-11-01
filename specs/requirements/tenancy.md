# TEN — Tenancy and data isolation

How data is organized and how users and tenants are isolated from each
other. Background: ADR-0009, ADR-0011.

## TEN-001: Tenant hierarchy

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

The data model MUST organize data as one instance containing tenants, each
tenant containing users and shared spaces. Every user and every shared space
belongs to exactly one tenant.

## TEN-002: Ownership columns

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

Every row of tenant-scoped data in the application schema MUST carry the
identifier of its tenant.
Every row of private data MUST also carry the identifier of the user who owns
it.

## TEN-003: Row-level security on every tenant-scoped table

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** design

Every tenant-scoped table of the application schema MUST have PostgreSQL
row-level security enabled and forced, with policies restricting access to the current tenant and, for
private data, to the owning user. A design test MUST fail when a
tenant-scoped table lacks enabled and forced row-level security.

## TEN-004: Unprivileged application database role

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The application MUST connect to the database with a role that is not a
superuser, does not have `BYPASSRLS` and does not own any tenant-scoped
table. Schema migrations MUST run with a separate role.

## TEN-005: Tenant context from the authenticated identity

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** integration

The tenant and user context of every database transaction MUST be derived
only from the authenticated identity and set with transaction-local settings
at the start of the transaction. It MUST NOT be taken from request
parameters, and it MUST NOT persist across transactions on a pooled
connection.

## TEN-006: No cross-user or cross-tenant access

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security

A user MUST NOT be able to read, list, modify or delete another user's
private data, or any data of another tenant, through any API endpoint.
Security tests MUST attempt such access for every endpoint that handles
tenant-scoped data.

## TEN-007: Private by default, explicit sharing

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** integration

New data MUST be private to the user who creates it, unless the user
explicitly creates it in, or moves it to, a shared space they belong to.

## TEN-008: Partitioned file storage

- **Status:** draft
- **Priority:** MUST
- **Phase:** 1
- **Verification:** security

Stored files MUST be partitioned by tenant and user. Storage paths MUST NOT be
built from unvalidated user input, and a user MUST NOT be able to access a
file outside their own partition or the shared spaces they belong to.

## TEN-009: Durable execution data

- **Status:** implemented
- **Priority:** MUST
- **Phase:** 0
- **Verification:** security, design

Data stored by the durable execution engine outside the application schema
(ADR-0034) MUST be reached by application code only through run identifiers
read from row-level-secured tables, MUST be deleted together with the
conversation it belongs to, and MUST be deleted once its run has finished and
the retention period configured by the instance admin has passed.
