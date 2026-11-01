# Database contract

The PostgreSQL schema for phase 0. The schema is a contract (ADR-0003): it
changes only through `spec/*` pull requests, and migrations in `migrations/`
implement it. Background: ADR-0009, ADR-0025, ADR-0031, ADR-0033, ADR-0034,
ADR-0037, ADR-0042, ADR-0046, ADR-0047, ADR-0048, ADR-0049, ADR-0051,
ADR-0052.

## Roles

| Role | Used by | Properties |
|---|---|---|
| `mzm_owner` | Migrations, and the pre-authentication functions it owns | Owns every table and function. Never used by running services to connect. |
| `mzm_app` | API and worker | `NOSUPERUSER`, `NOBYPASSRLS`, `NOCREATEDB`, `NOCREATEROLE`; owns nothing; granted only the privileges listed below (TEN-004). |

Every table below has row-level security **enabled and forced** (TEN-003),
including tables that are not tenant-scoped, so that no table is readable by
`mzm_app` without an explicit policy. Forced row-level security applies to the
table owner too: `mzm_owner` reaches rows only through the owner policies of
the pre-authentication functions. The policies of each table below are
created `TO mzm_app`.

## Initialization

The schema targets PostgreSQL 17. Roles and the database are created once per
instance, before any migration, by a superuser: by the deployment's database
initialization and by the test harness ([test-harness.md](test-harness.md)).
Migrations never create roles, and the superuser is not used afterwards.

```sql
CREATE ROLE mzm_owner LOGIN PASSWORD '...'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE ROLE mzm_app LOGIN PASSWORD '...'
  NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE DATABASE mazzamurello OWNER mzm_owner;
REVOKE ALL ON DATABASE mazzamurello FROM PUBLIC;
GRANT CONNECT ON DATABASE mazzamurello TO mzm_app;
```

Migrations, run as `mzm_owner`, create every schema object and grant
`mzm_app` exactly the privileges this contract lists.

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
| `auth_find_login(username text)` | `user_id, tenant_id, password_hash, role, instance_admin, disabled` | Password verification (AUTH-001); matches the username ignoring case |
| `auth_find_session(token_hash bytea)` | `session_id, user_id, tenant_id, role, instance_admin, expires_at, revoked` | Token verification on every request (AUTH-004) |
| `auth_touch_session(session_id uuid)` | — | Sets `last_used_at` to now and `expires_at` to 90 days later, for a session that is neither revoked nor expired (ADR-0049) |
| `auth_record_login_attempt(username text, source inet, success boolean)` | `allowed boolean, retry_after_seconds integer` | Rate limiting (AUTH-006), by the rules below |
| `retention_expired_runs(days integer)` | `run_id` for every run whose `finished_at` is more than `days` days ago | Retention of durable workflows (TEN-009, ADR-0052): only identifiers, so the worker can delete their workflows across tenants |
| `bootstrap_instance(tenant_name text, username text, display_name text, password_hash text)` | `tenant_id, user_id` | Creates the first tenant and its first user, who is instance admin and tenant admin; fails if any user exists (AUTH-007). Executable only by `mzm_owner`, run by the setup command |

Rate limiting (ADR-0047): `auth_record_login_attempt` is called once per
login attempt, after the password is verified, with its outcome. It counts
the failed attempts recorded in the 15 minutes before the call. The attempt
is refused when 5 of them are for the same username, ignoring case, or 20 are
from the same source address. A refused attempt is not recorded, and the
server answers it the same whether or not the password was right; an allowed
attempt is recorded with its outcome. When refused, `retry_after_seconds` is
the time, rounded up to whole seconds, until the oldest failure counted toward
a reached limit leaves the window (the longer, when both are reached); when
allowed, it is 0. Each call deletes attempts older than the window.

These functions run as `mzm_owner`, which forced row-level security does not
exempt. They work through **owner policies**, created `TO mzm_owner`, and
these are the only policies for that role:

| Table | Operations for `mzm_owner` | Used by |
|---|---|---|
| `tenants` | `SELECT`, `INSERT` | `bootstrap_instance` |
| `users` | `SELECT`, `INSERT` | `auth_find_login`, `auth_find_session`, `bootstrap_instance` |
| `device_sessions` | `SELECT`, `UPDATE` | `auth_find_session`, `auth_touch_session`, `revoke_sessions_of_disabled_user` |
| `login_attempts` | `SELECT`, `INSERT`, `DELETE` | `auth_record_login_attempt`, which also deletes rows older than the rate-limit window |
| `runs` | `SELECT` | `retention_expired_runs` |

Owner policies have no condition (`USING (true)`): `mzm_owner` is never used
by running services, so they open these tables only to the code of the
`SECURITY DEFINER` functions of this contract and to migrations.

## Tables

Conventions: identifiers are `uuid` (version 7); timestamps are
`timestamptz`; every foreign key to a tenant-scoped row also includes
`tenant_id`, so that a row can never reference another tenant's data; every
foreign key from a private table to another private table also includes the
owner column, so that a row can never be attached to another user's data. A
foreign key that sets null on delete lists the column it sets
(`ON DELETE SET NULL (column)`), so that the tenant and owner columns keep
their values.

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
| `username` | text | not null, unique across the instance ignoring case |
| `display_name` | text | not null |
| `password_hash` | text | not null; Argon2id encoded hash (AUTH-001) |
| `role` | text | `member` or `tenant_admin` |
| `instance_admin` | boolean | not null, default false |
| `created_at` | timestamptz | not null |
| `disabled_at` | timestamptz | null while active |

Policies:
- `SELECT` where `tenant_id = app_tenant_id()`.
- `INSERT` where (`tenant_id = app_tenant_id()` and `app_is_tenant_admin()`
  and not `instance_admin`) or `app_is_instance_admin()` (to create a new
  tenant's first admin). Only an instance admin creates instance admins
  (AUTH-008).
- `UPDATE` where `tenant_id = app_tenant_id()` and (`id = app_user_id()` or
  `app_is_tenant_admin()`).

Column privileges: `mzm_app` cannot `SELECT` `password_hash`; only
`auth_find_login` reads it. `mzm_app` may `UPDATE` only `display_name`,
`password_hash`, `role` and `disabled_at`; identifiers, `username` and
`instance_admin` never change through the application.

Changing `role` or `disabled_at` requires `app_is_tenant_admin()`, so that
users cannot promote themselves or re-enable their account (AUTH-008). Row-level
security cannot compare a row's old and new values, so a `BEFORE UPDATE`
trigger on `users` enforces this rule.

Disabling an account revokes its sessions (AUTH-009, ADR-0048). When
`disabled_at` changes from null to a value, an `AFTER UPDATE` trigger on
`users` sets `revoked_at` to the current time on every session of that user
that is not yet revoked, in the same transaction. Its function,
`revoke_sessions_of_disabled_user()`, is `SECURITY DEFINER`, owned by
`mzm_owner`, with a fixed `search_path`, and not executable by `mzm_app`; it
changes `device_sessions` through the owner policies. Re-enabling an account
leaves its sessions revoked.

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
| `expires_at` | timestamptz | not null; 90 days after the last use (ADR-0049) |
| `revoked_at` | timestamptz | null while valid |

Policies: all operations where `tenant_id = app_tenant_id()` and
`user_id = app_user_id()`. `INSERT` at login happens after the context is set
from the verified credentials.

### `login_attempts`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint | identity |
| `username` | text | as submitted; compared ignoring case |
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
| `title` | text | not null; empty while untitled (ADR-0052) |
| `active_run_id` | uuid | the last run of the active path (ADR-0037); null before the first run; (`tenant_id`, `owner_id`, `active_run_id`) references `runs` on delete set null (`active_run_id`) |
| `usage` | jsonb | Pydantic AI conversation usage |
| `pending_approvals` | jsonb | serialized `DeferredToolRequests` while an interrupt is pending (ADR-0033), else null |
| `approvals_expire_at` | timestamptz | expiry of the pending interrupt (AGT-007), else null |
| `archived_at` | timestamptz | null when active |
| `created_at` | timestamptz | not null |
| `updated_at` | timestamptz | not null; updated when a run adds messages |

### `conversation_messages` (private)

The source of truth of a conversation: Pydantic AI messages, grouped by the
run that produced them (ADR-0031, ADR-0037). The history of a path is the
messages of its runs, from the first run, each run's messages in order.
History served to clients is a projection of these rows.

| Column | Type | Notes |
|---|---|---|
| `run_id` | uuid | (`tenant_id`, `owner_id`, `run_id`) references `runs` on delete cascade |
| `seq` | integer | position within the run, starting at 1, no gaps |
| `tenant_id`, `owner_id` | uuid | as in `conversations` |
| `conversation_id` | uuid | (`tenant_id`, `owner_id`, `conversation_id`) references `conversations` on delete cascade |
| `message` | jsonb | one `ModelMessage`, serialized with Pydantic AI's `ModelMessagesTypeAdapter` |
| `created_at` | timestamptz | not null |

Primary key (`run_id`, `seq`).

### `runs` (private)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key; also Pydantic AI's `run_id` and the DBOS workflow ID (ADR-0034) |
| `tenant_id`, `owner_id` | uuid | as in `conversations` |
| `conversation_id` | uuid | not null; (`tenant_id`, `owner_id`, `conversation_id`) references `conversations` on delete cascade |
| `parent_run_id` | uuid | the run this run continues (ADR-0037); null for the first run; (`tenant_id`, `owner_id`, `parent_run_id`) references `runs` on delete cascade; indexed |
| `kind` | text | `message` (a new turn or a version of one) or `resume` (answers to an interrupt, ADR-0033) |
| `status` | text | `queued`, `running`, `interrupted`, `completed`, `failed`, `cancelled` |
| `error_code` | text | stable error code when failed (API-007) |
| `model_provider`, `model_name` | text | set when known (MOD-005) |
| `last_event_seq` | integer | sequence number of the last event written to the run's stream |
| `created_at`, `started_at`, `finished_at` | timestamptz | |

Constraints:

- at most one run with status `queued` or `running` per conversation (partial
  unique index), in addition to the per-conversation queue partition of
  ADR-0034;
- a run's parent belongs to the same conversation;
- a run of kind `resume` has the interrupted run as parent, and is its only
  child.

### `usage_ledger` (private)

One entry per model request made by the model gateway (MOD-006, ADR-0042).
It never contains content.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `tenant_id`, `owner_id` | uuid | the user the request was made for; (`tenant_id`, `owner_id`) references `users` |
| `conversation_id` | uuid | null for requests outside a conversation; (`tenant_id`, `owner_id`, `conversation_id`) references `conversations` on delete set null (`conversation_id`) |
| `run_id` | uuid | null outside a run; (`tenant_id`, `owner_id`, `run_id`) references `runs` on delete set null (`run_id`) |
| `purpose` | text | `run`, `title`, `compaction`, `speech` or `memory` |
| `provider`, `model` | text | not null; the host of the model configuration's endpoint and its model name (MOD-005) |
| `input_tokens`, `cached_input_tokens`, `cache_write_tokens`, `output_tokens` | bigint | not null, default 0 |
| `cost` | numeric(20, 10) | null when the price is unknown |
| `currency` | text | ISO 4217 code, such as `USD`; null when `cost` is null |
| `price_source` | text | `provider`, `admin`, `catalog`, `free` or `unknown` |
| `created_at` | timestamptz | not null; indexed with `owner_id` |

Totals per message, conversation, day and month are computed from these rows.
Per-user totals for tenant admins arrive in phase 1, through a function that
returns only sums per user.

### `instance_models`

Model configurations of the instance, available to every tenant (MOD-008,
ADR-0051). Like `tenants`, this is configuration of the instance, not data of
a tenant, and has no `tenant_id`.

| Column | Type | Notes |
|---|---|---|
| `id` | uuid | primary key |
| `name` | text | not null, unique; shown to users |
| `base_url` | text | not null; the endpoint of an OpenAI-compatible API |
| `model` | text | not null; the model name the endpoint expects |
| `api_key_ciphertext` | bytea | the API key, encrypted with AES-256-GCM under `MZM_SECRET_KEY` (ADR-0051); null when the endpoint needs no key |
| `paid` | boolean | not null; whether the provider charges per token |
| `input_price`, `cached_input_price`, `output_price` | numeric(20, 10) | price per million tokens set by the admin, or null |
| `currency` | text | ISO 4217 code; not null exactly when a price is set |
| `is_default` | boolean | not null, default false; at most one row is the default |
| `created_at`, `updated_at` | timestamptz | not null |

Policies: `SELECT` when `app_user_id()` is not null; `INSERT`, `UPDATE` and
`DELETE` when `app_is_instance_admin()`.

### `tenant_models`

Model configurations of one tenant (MOD-008, ADR-0051): the columns of
`instance_models`, plus:

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | uuid | not null, references `tenants` |

`name` is unique within the tenant, and at most one row per tenant is the
default. Policies: `SELECT` where `tenant_id = app_tenant_id()`; `INSERT`,
`UPDATE` and `DELETE` where `tenant_id = app_tenant_id()` and
`app_is_tenant_admin()`.

A run uses the default model of its tenant, or else the default instance
model (ADR-0051).

### Policies for private tables

`device_sessions`, `conversations`, `conversation_messages`, `runs` and
`usage_ledger` use the same policy for every operation:

```sql
USING      (tenant_id = app_tenant_id() AND owner_id = app_user_id())
WITH CHECK (tenant_id = app_tenant_id() AND owner_id = app_user_id())
```

(`device_sessions` uses `user_id` in place of `owner_id`.)

## Privileges of `mzm_app`

`mzm_app` holds exactly these privileges, and nothing else (TEN-004). Rows
that a conversation's deletion removes or detaches are handled by the foreign
keys, not by privileges of `mzm_app`.

| Object | Privileges |
|---|---|
| `tenants` | `SELECT`, `INSERT` |
| `users` | `SELECT` on every column except `password_hash`; `INSERT`; `UPDATE` of `display_name`, `password_hash`, `role`, `disabled_at` |
| `device_sessions` | `SELECT`, `INSERT`, `DELETE`; `UPDATE` of `revoked_at` |
| `login_attempts` | none |
| `conversations` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `conversation_messages` | `SELECT`, `INSERT`: stored messages never change (ADR-0041) |
| `runs` | `SELECT`, `INSERT`, `UPDATE` |
| `usage_ledger` | `SELECT`, `INSERT`: entries never change (ADR-0042) |
| `instance_models` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| `tenant_models` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` |
| Helper functions | `EXECUTE` on `app_tenant_id()`, `app_user_id()`, `app_is_tenant_admin()`, `app_is_instance_admin()` |
| Pre-authentication functions | `EXECUTE` on every function of that section except `bootstrap_instance` |

`EXECUTE` on functions is revoked from `PUBLIC`.

## Durable execution schema (`dbos`)

DBOS (ADR-0034) keeps its own tables in the `dbos` schema, created and
migrated by the DBOS system migrations, which the migration command runs as
`mzm_owner` after the Alembic revisions, granting `mzm_app` the access DBOS
needs (ADR-0052): workflow status, inputs and outputs, step outputs,
notifications and streams. They hold user content (prompts, model responses,
run events) **without row-level security**, which DBOS cannot apply. Rules
(TEN-009):

- Application code reads or writes DBOS data only for workflow IDs that are
  run IDs obtained from the row-level-secured `runs` table in the same
  request.
- Deleting a conversation deletes the DBOS workflows of its runs.
- Workflows of runs whose `finished_at` is more than `MZM_RUN_RETENTION_DAYS`
  days ago (default 30) are deleted by the worker, when it starts and then
  every hour (ADR-0052).
- Workflow inputs carry the tenant and user IDs of the run; the worker sets
  the request context from them.

## Deletion

Deleting a conversation deletes its messages and runs in the same transaction,
and the DBOS workflows of those runs (API-003, TEN-009). Its entries in the
cost ledger are kept, detached from the conversation and its runs, so that
spending totals stay correct (ADR-0042). Deletion is physical;
there is no soft delete for user content.

## Properties verified by design tests

- Every table of the application schema has row-level security enabled and
  forced (TEN-003); the `dbos` schema is the documented exception (TEN-009).
- Every table holding user data has `tenant_id`, and private tables have an
  owner column (TEN-002).
- `mzm_app` is not a superuser, lacks `BYPASSRLS` and owns no table or
  function (TEN-004).
- Every `SECURITY DEFINER` function is a pre-authentication function or
  `revoke_sessions_of_disabled_user()`, is owned by `mzm_owner` and has a fixed
  `search_path`.
- `mzm_app` holds exactly the privileges listed in "Privileges of `mzm_app`"
  (TEN-004).
- Policies for `mzm_owner` are exactly the owner policies listed with the
  pre-authentication functions; every other policy is for `mzm_app`.
- Every foreign key between tenant-scoped tables includes `tenant_id`, and
  every foreign key between private tables also includes the owner column.
- Users cannot change their own `role` or `disabled_at`, and only instance
  admins create instance admins (AUTH-008).
