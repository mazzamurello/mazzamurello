# Database contract

The PostgreSQL schema for phase 0. The schema is a contract (ADR-0003): it
changes only through `spec/*` pull requests, and migrations in `migrations/`
implement it. Background: ADR-0009, ADR-0025, ADR-0031, ADR-0033, ADR-0034.

## Roles

| Role | Used by | Properties |
|---|---|---|
| `mzm_owner` | Migrations only | Owns every table and function. Never used by running services. |
| `mzm_app` | API and worker | `NOSUPERUSER`, `NOBYPASSRLS`, `NOCREATEDB`, `NOCREATEROLE`; owns nothing; granted only the privileges listed below (TEN-004). |

Every table below has row-level security **enabled and forced** (TEN-003),
including tables that are not tenant-scoped, so that no table is readable by
`mzm_app` without an explicit policy.

## Request context

At the start of every transaction, after authentication, the server sets
transaction-local settings derived only from the authenticated identity
(TEN-005):

| Setting | Value |
|---|---|
| `app.tenant_id` | Tenant of the authenticated user (UUID) |
| `app.user_id` | Authenticated user (UUID) |
| `app.role` | `member` or `tenant_admin` |
| `app.instance_admin` | `true` or `false` |

They are set with `set_config(name, value, true)`, so they vanish at the end
of the transaction. Policies read them with `current_setting(name, true)`;
when a setting is missing, the comparison is `NULL` and the policy denies
access.

Helper functions used in the policies below, all `STABLE`:

```sql
app_tenant_id()      -> current_setting('app.tenant_id', true)::uuid
app_user_id()        -> current_setting('app.user_id', true)::uuid
app_is_tenant_admin() -> current_setting('app.role', true) = 'tenant_admin'
app_is_instance_admin() -> current_setting('app.instance_admin', true) = 'true'
```

## Pre-authentication functions

Login and token verification happen before any context exists. Instead of
weakening policies, `mzm_app` may call exactly these `SECURITY DEFINER`
functions, owned by `mzm_owner`, with a fixed `search_path`. They return the
minimum needed and nothing else.

| Function | Returns | Purpose |
|---|---|---|
| `auth_find_login(username text)` | `user_id, tenant_id, password_hash, role, instance_admin, disabled` | Password verification (AUTH-001) |
| `auth_find_session(token_hash bytea)` | `session_id, user_id, tenant_id, role, instance_admin, expires_at, revoked` | Token verification on every request (AUTH-004) |
| `auth_touch_session(session_id uuid)` | — | Updates `last_used_at` |
| `auth_record_login_attempt(username text, source inet, success boolean)` | `allowed boolean, retry_after_seconds integer` | Rate limiting (AUTH-006) |
| `bootstrap_instance(tenant_name text, username text, display_name text, password_hash text)` | `tenant_id, user_id` | Creates the first tenant and instance admin; fails if any user exists (AUTH-007). Executable only by `mzm_owner`, run by the setup command |

## Tables

Conventions: identifiers are `uuid` (version 7); timestamps are
`timestamptz`; every foreign key to a tenant-scoped row also includes
`tenant_id`, so that a row can never reference another tenant's data.

### `tenants`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `name` | text | not null, unique |
| `created_at` | timestamptz | not null |

Policies: `SELECT` where `id = app_tenant_id()` or `app_is_instance_admin()`;
`INSERT` when `app_is_instance_admin()`. No `UPDATE` or `DELETE` in phase 0.

### `users`

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id` | uuid | not null, references `tenants` |
| `username` | text | not null, unique across the instance |
| `display_name` | text | not null |
| `password_hash` | text | not null; Argon2id encoded hash (AUTH-001) |
| `role` | text | `member` or `tenant_admin` |
| `instance_admin` | boolean | not null, default false |
| `created_at` | timestamptz | not null |
| `disabled_at` | timestamptz | null while active |

Policies:
- `SELECT` where `tenant_id = app_tenant_id()`.
- `INSERT` where (`tenant_id = app_tenant_id()` and `app_is_tenant_admin()`)
  or `app_is_instance_admin()` (to create a new tenant's first admin).
- `UPDATE` where `tenant_id = app_tenant_id()` and (`id = app_user_id()` or
  `app_is_tenant_admin()`).

Column privileges: `mzm_app` cannot `SELECT` `password_hash`; only
`auth_find_login` reads it.

### `device_sessions` (private)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id` | uuid | not null |
| `user_id` | uuid | not null; (`tenant_id`, `user_id`) references `users` |
| `token_hash` | bytea | not null, unique; SHA-256 of the token (AUTH-004) |
| `device_name` | text | not null |
| `created_at` | timestamptz | not null |
| `last_used_at` | timestamptz | not null |
| `expires_at` | timestamptz | not null |
| `revoked_at` | timestamptz | null while valid |

Policies: all operations where `tenant_id = app_tenant_id()` and
`user_id = app_user_id()`. `INSERT` at login happens after the context is set
from the verified credentials.

### `login_attempts`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint | identity |
| `username` | text | as submitted |
| `source` | inet | client address |
| `success` | boolean | not null |
| `created_at` | timestamptz | not null |

No policies for `mzm_app`: accessed only through
`auth_record_login_attempt`. Rows older than the rate-limit window are deleted.

### `conversations` (private)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key; also Pydantic AI's `conversation_id` (ADR-0031) |
| `tenant_id` | uuid | not null |
| `owner_id` | uuid | not null; (`tenant_id`, `owner_id`) references `users` |
| `title` | text | not null |
| `usage` | jsonb | Pydantic AI conversation usage |
| `pending_approvals` | jsonb | serialized `DeferredToolRequests` while an interrupt is pending (ADR-0033), else null |
| `approvals_expire_at` | timestamptz | expiry of the pending interrupt (AGT-007), else null |
| `archived_at` | timestamptz | null when active |
| `created_at` | timestamptz | not null |
| `updated_at` | timestamptz | not null; updated when a run adds messages |

### `conversation_messages` (private)

The source of truth of a conversation: Pydantic AI messages, in order
(ADR-0031). History served to clients is a projection of these rows.

| Column | Type | Notes |
|---|---|---|
| `conversation_id` | uuid | (`tenant_id`, `conversation_id`) references `conversations` on delete cascade |
| `seq` | integer | position in the conversation, starting at 1, no gaps |
| `tenant_id`, `owner_id` | uuid | as in `conversations` |
| `run_id` | uuid | the run that produced the message |
| `message` | jsonb | one `ModelMessage`, serialized with Pydantic AI's `ModelMessagesTypeAdapter` |
| `created_at` | timestamptz | not null |

Primary key (`conversation_id`, `seq`).

### `runs` (private)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key; also Pydantic AI's `run_id` and the DBOS workflow ID (ADR-0034) |
| `tenant_id`, `owner_id` | uuid | as in `conversations` |
| `conversation_id` | uuid | not null; references `conversations` on delete cascade |
| `status` | text | `queued`, `running`, `interrupted`, `completed`, `failed` |
| `error_code` | text | stable error code when failed (API-007) |
| `model_provider`, `model_name` | text | set when known (MOD-005) |
| `last_event_seq` | integer | sequence number of the last event written to the run's stream |
| `created_at`, `started_at`, `finished_at` | timestamptz | |

Constraint: at most one run with status `queued` or `running` per
conversation (partial unique index), in addition to the per-conversation
queue partition of ADR-0034.

### Policies for private tables

`device_sessions`, `conversations`, `conversation_messages` and `runs` use the
same policy for every operation:

```sql
USING      (tenant_id = app_tenant_id() AND owner_id = app_user_id())
WITH CHECK (tenant_id = app_tenant_id() AND owner_id = app_user_id())
```

(`device_sessions` uses `user_id` in place of `owner_id`.)

## Durable execution schema (`dbos`)

DBOS (ADR-0034) keeps its own tables in the `dbos` schema, created and
migrated by DBOS itself: workflow status, inputs and outputs, step outputs,
notifications and streams. They hold user content (prompts, model responses,
run events) **without row-level security**, which DBOS cannot apply. Rules
(TEN-009):

- Application code reads or writes DBOS data only for workflow IDs that are
  run IDs obtained from the row-level-secured `runs` table in the same
  request.
- Deleting a conversation deletes the DBOS workflows of its runs.
- Finished workflows are deleted after the retention period configured by the
  instance admin.
- Workflow inputs carry the tenant and user IDs of the run; the worker sets
  the request context from them.

## Deletion

Deleting a conversation deletes its messages and runs in the same transaction,
and the DBOS workflows of those runs (API-003, TEN-009). Deletion is physical;
there is no soft delete for user content.

## Properties verified by design tests

- Every table of the application schema has row-level security enabled and
  forced (TEN-003); the `dbos` schema is the documented exception (TEN-009).
- Every table holding user data has `tenant_id`, and private tables have an
  owner column (TEN-002).
- `mzm_app` is not a superuser, lacks `BYPASSRLS` and owns no table or
  function (TEN-004).
- Every `SECURITY DEFINER` function is in the list above, owned by `mzm_owner`
  and has a fixed `search_path`.
- Every foreign key between tenant-scoped tables includes `tenant_id`.
