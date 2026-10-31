"""Initial schema: the phase 0 database contract (specs/contracts/database.md).

Tables, row-level security, policies, privileges and the pre-authentication
functions (TEN-001 to TEN-004, TEN-006, AUTH-001, AUTH-004, AUTH-006 to
AUTH-008; ADR-0009, ADR-0046, ADR-0047). Roles and the database itself are
created before any migration, by the initialization of the contract.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

CONTRACT_TABLES = (
    "tenants",
    "users",
    "device_sessions",
    "login_attempts",
    "conversations",
    "runs",
    "conversation_messages",
    "usage_ledger",
)
PRIVATE_TABLES = ("conversations", "runs", "conversation_messages", "usage_ledger")

HELPER_FUNCTIONS = [
    # Request context (TEN-005). A setting that was never set, or was reset at
    # the end of a transaction, reads as NULL or as an empty string: both mean
    # no context, and every policy comparison with NULL denies.
    """
    CREATE FUNCTION app_tenant_id() RETURNS uuid LANGUAGE sql STABLE
    AS $$ SELECT nullif(current_setting('app.tenant_id', true), '')::uuid $$
    """,
    """
    CREATE FUNCTION app_user_id() RETURNS uuid LANGUAGE sql STABLE
    AS $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$
    """,
    """
    CREATE FUNCTION app_is_tenant_admin() RETURNS boolean LANGUAGE sql STABLE
    AS $$ SELECT coalesce(current_setting('app.role', true) = 'tenant_admin', false) $$
    """,
    """
    CREATE FUNCTION app_is_instance_admin() RETURNS boolean LANGUAGE sql STABLE
    AS $$ SELECT coalesce(current_setting('app.instance_admin', true) = 'true', false) $$
    """,
    # Version 7 UUIDs for rows created inside the database; PostgreSQL 17 has
    # no built-in generator. The time in milliseconds replaces the first 48
    # bits of a random UUID, and the version nibble becomes 7.
    """
    CREATE FUNCTION uuid7() RETURNS uuid LANGUAGE sql VOLATILE
    SET search_path = pg_catalog, pg_temp
    AS $$
      SELECT encode(
        set_bit(set_bit(
          overlay(uuid_send(gen_random_uuid())
                  PLACING substring(int8send((extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3)
                  FROM 1 FOR 6),
          52, 1), 53, 1),
        'hex')::uuid
    $$
    """,
]

TABLES = [
    """
    CREATE TABLE tenants (
      id uuid PRIMARY KEY,
      name text NOT NULL UNIQUE,
      created_at timestamptz NOT NULL
    )
    """,
    """
    CREATE TABLE users (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL REFERENCES tenants (id),
      username text NOT NULL,
      display_name text NOT NULL,
      password_hash text NOT NULL,
      role text NOT NULL CHECK (role IN ('member', 'tenant_admin')),
      instance_admin boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL,
      disabled_at timestamptz,
      UNIQUE (tenant_id, id)
    )
    """,
    # Usernames are unique across the instance, ignoring case (ADR-0047).
    "CREATE UNIQUE INDEX users_username_key ON users (lower(username))",
    """
    CREATE TABLE device_sessions (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL,
      user_id uuid NOT NULL,
      token_hash bytea NOT NULL UNIQUE,
      device_name text NOT NULL,
      created_at timestamptz NOT NULL,
      last_used_at timestamptz NOT NULL,
      expires_at timestamptz NOT NULL,
      revoked_at timestamptz,
      FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id)
    )
    """,
    "CREATE INDEX device_sessions_user_idx ON device_sessions (tenant_id, user_id)",
    """
    CREATE TABLE login_attempts (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      username text NOT NULL,
      source inet,
      success boolean NOT NULL,
      created_at timestamptz NOT NULL
    )
    """,
    "CREATE INDEX login_attempts_username_idx ON login_attempts (lower(username), created_at)",
    "CREATE INDEX login_attempts_source_idx ON login_attempts (source, created_at)",
    "CREATE INDEX login_attempts_created_at_idx ON login_attempts (created_at)",
    """
    CREATE TABLE conversations (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL,
      owner_id uuid NOT NULL,
      title text NOT NULL,
      active_run_id uuid,
      usage jsonb,
      pending_approvals jsonb,
      approvals_expire_at timestamptz,
      archived_at timestamptz,
      created_at timestamptz NOT NULL,
      updated_at timestamptz NOT NULL,
      UNIQUE (tenant_id, owner_id, id),
      FOREIGN KEY (tenant_id, owner_id) REFERENCES users (tenant_id, id)
    )
    """,
    """
    CREATE TABLE runs (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL,
      owner_id uuid NOT NULL,
      conversation_id uuid NOT NULL,
      parent_run_id uuid,
      kind text NOT NULL CHECK (kind IN ('message', 'resume')),
      status text NOT NULL CHECK (status IN ('queued', 'running', 'interrupted', 'completed', 'failed', 'cancelled')),
      error_code text,
      model_provider text,
      model_name text,
      last_event_seq integer,
      created_at timestamptz NOT NULL,
      started_at timestamptz,
      finished_at timestamptz,
      UNIQUE (tenant_id, owner_id, id),
      UNIQUE (tenant_id, owner_id, conversation_id, id),
      FOREIGN KEY (tenant_id, owner_id) REFERENCES users (tenant_id, id),
      FOREIGN KEY (tenant_id, owner_id, conversation_id)
        REFERENCES conversations (tenant_id, owner_id, id) ON DELETE CASCADE,
      FOREIGN KEY (tenant_id, owner_id, parent_run_id)
        REFERENCES runs (tenant_id, owner_id, id) ON DELETE CASCADE,
      -- A run's parent belongs to the same conversation.
      FOREIGN KEY (tenant_id, owner_id, conversation_id, parent_run_id)
        REFERENCES runs (tenant_id, owner_id, conversation_id, id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX runs_conversation_idx ON runs (conversation_id)",
    "CREATE INDEX runs_parent_run_idx ON runs (parent_run_id)",
    # At most one queued or running run per conversation.
    """
    CREATE UNIQUE INDEX runs_one_active_per_conversation ON runs (conversation_id)
    WHERE status IN ('queued', 'running')
    """,
    """
    ALTER TABLE conversations ADD FOREIGN KEY (tenant_id, owner_id, active_run_id)
      REFERENCES runs (tenant_id, owner_id, id) ON DELETE SET NULL (active_run_id)
    """,
    "CREATE INDEX conversations_active_run_idx ON conversations (active_run_id)",
    """
    CREATE TABLE conversation_messages (
      run_id uuid NOT NULL,
      seq integer NOT NULL CHECK (seq >= 1),
      tenant_id uuid NOT NULL,
      owner_id uuid NOT NULL,
      conversation_id uuid NOT NULL,
      message jsonb NOT NULL,
      created_at timestamptz NOT NULL,
      PRIMARY KEY (run_id, seq),
      FOREIGN KEY (tenant_id, owner_id, run_id) REFERENCES runs (tenant_id, owner_id, id) ON DELETE CASCADE,
      FOREIGN KEY (tenant_id, owner_id, conversation_id)
        REFERENCES conversations (tenant_id, owner_id, id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX conversation_messages_conversation_idx ON conversation_messages (conversation_id)",
    """
    CREATE TABLE usage_ledger (
      id uuid PRIMARY KEY,
      tenant_id uuid NOT NULL,
      owner_id uuid NOT NULL,
      conversation_id uuid,
      run_id uuid,
      purpose text NOT NULL CHECK (purpose IN ('run', 'title', 'compaction', 'speech', 'memory')),
      provider text NOT NULL,
      model text NOT NULL,
      input_tokens bigint NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
      cached_input_tokens bigint NOT NULL DEFAULT 0 CHECK (cached_input_tokens >= 0),
      cache_write_tokens bigint NOT NULL DEFAULT 0 CHECK (cache_write_tokens >= 0),
      output_tokens bigint NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
      cost numeric(20, 10),
      currency text CHECK (currency ~ '^[A-Z]{3}$'),
      price_source text NOT NULL CHECK (price_source IN ('provider', 'admin', 'catalog', 'free', 'unknown')),
      created_at timestamptz NOT NULL,
      -- A currency exactly when there is a cost.
      CHECK ((cost IS NULL) = (currency IS NULL)),
      FOREIGN KEY (tenant_id, owner_id) REFERENCES users (tenant_id, id),
      FOREIGN KEY (tenant_id, owner_id, conversation_id)
        REFERENCES conversations (tenant_id, owner_id, id) ON DELETE SET NULL (conversation_id),
      FOREIGN KEY (tenant_id, owner_id, run_id) REFERENCES runs (tenant_id, owner_id, id) ON DELETE SET NULL (run_id)
    )
    """,
    "CREATE INDEX usage_ledger_owner_created_at_idx ON usage_ledger (owner_id, created_at)",
    "CREATE INDEX usage_ledger_conversation_idx ON usage_ledger (conversation_id)",
    "CREATE INDEX usage_ledger_run_idx ON usage_ledger (run_id)",
]

TRIGGERS = [
    # Row-level security cannot compare old and new values, so this trigger
    # keeps users from changing their own role or account state (AUTH-008,
    # ADR-0046). It runs as the caller, whose request context it reads.
    """
    CREATE FUNCTION users_guard() RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, pg_temp
    AS $$
    BEGIN
      IF (NEW.role IS DISTINCT FROM OLD.role OR NEW.disabled_at IS DISTINCT FROM OLD.disabled_at)
         AND NOT public.app_is_tenant_admin() THEN
        RAISE EXCEPTION 'changing a role or disabling an account requires a tenant admin'
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN NEW;
    END
    $$
    """,
    "CREATE TRIGGER users_guard BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION users_guard()",
    # A run of kind `resume` has the interrupted run as parent and is its only
    # child (ADR-0033, ADR-0037). The parent row is locked, so concurrent
    # children of the same run are checked one after the other.
    """
    CREATE FUNCTION runs_check_parent() RETURNS trigger LANGUAGE plpgsql
    SET search_path = pg_catalog, pg_temp
    AS $$
    DECLARE
      parent_status text;
    BEGIN
      IF NEW.parent_run_id IS NULL THEN
        IF NEW.kind = 'resume' THEN
          RAISE EXCEPTION 'a resume run continues an interrupted run' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
      END IF;
      SELECT r.status INTO parent_status FROM public.runs r WHERE r.id = NEW.parent_run_id FOR UPDATE;
      IF EXISTS (SELECT 1 FROM public.runs r
                 WHERE r.parent_run_id = NEW.parent_run_id AND r.kind = 'resume' AND r.id <> NEW.id) THEN
        RAISE EXCEPTION 'a run continued by a resume run has no other child' USING ERRCODE = 'check_violation';
      END IF;
      IF NEW.kind = 'resume' THEN
        IF parent_status IS DISTINCT FROM 'interrupted' THEN
          RAISE EXCEPTION 'a resume run continues an interrupted run' USING ERRCODE = 'check_violation';
        END IF;
        IF EXISTS (SELECT 1 FROM public.runs r WHERE r.parent_run_id = NEW.parent_run_id AND r.id <> NEW.id) THEN
          RAISE EXCEPTION 'a resume run is the only child of its parent' USING ERRCODE = 'check_violation';
        END IF;
      END IF;
      RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER runs_check_parent BEFORE INSERT OR UPDATE OF parent_run_id, kind ON runs
    FOR EACH ROW EXECUTE FUNCTION runs_check_parent()
    """,
]

PRE_AUTHENTICATION_FUNCTIONS = [
    # Parameters are referred to by position: their names are those of the
    # contract and would otherwise be taken for columns.
    """
    CREATE FUNCTION auth_find_login(username text)
    RETURNS TABLE (user_id uuid, tenant_id uuid, password_hash text, role text, instance_admin boolean,
                   disabled boolean)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
      SELECT u.id, u.tenant_id, u.password_hash, u.role, u.instance_admin, u.disabled_at IS NOT NULL
      FROM public.users u
      WHERE lower(u.username) = lower($1)
    $$
    """,
    """
    CREATE FUNCTION auth_find_session(token_hash bytea)
    RETURNS TABLE (session_id uuid, user_id uuid, tenant_id uuid, role text, instance_admin boolean,
                   expires_at timestamptz, revoked boolean)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
      SELECT s.id, s.user_id, s.tenant_id, u.role, u.instance_admin, s.expires_at, s.revoked_at IS NOT NULL
      FROM public.device_sessions s
      JOIN public.users u ON u.tenant_id = s.tenant_id AND u.id = s.user_id
      WHERE s.token_hash = $1
    $$
    """,
    """
    CREATE FUNCTION auth_touch_session(session_id uuid) RETURNS void
    LANGUAGE sql SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$ UPDATE public.device_sessions SET last_used_at = now() WHERE id = $1 $$
    """,
    # Rate limits of ADR-0047: a 15-minute window, 5 failures per username and
    # 20 per source address. For each limit, the failure that the limit counts
    # first is the one with as many failures after it, in the window, as the
    # limit allows (OFFSET limit - 1): when it leaves the window, the limit is
    # no longer reached. Attempts for the same username are serialized by a
    # lock.
    """
    CREATE FUNCTION auth_record_login_attempt(username text, source inet, success boolean)
    RETURNS TABLE (allowed boolean, retry_after_seconds integer)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
    #variable_conflict use_column
    DECLARE
      window_start timestamptz := now() - interval '15 minutes';
      username_limit_since timestamptz;
      source_limit_since timestamptz;
      retry_at timestamptz;
    BEGIN
      PERFORM pg_advisory_xact_lock(hashtextextended('mzm.login_attempts:' || lower($1), 0));
      DELETE FROM public.login_attempts a WHERE a.created_at < window_start;
      SELECT a.created_at INTO username_limit_since FROM public.login_attempts a
      WHERE NOT a.success AND lower(a.username) = lower($1)
      ORDER BY a.created_at DESC OFFSET 4 LIMIT 1;
      IF $2 IS NOT NULL THEN
        SELECT a.created_at INTO source_limit_since FROM public.login_attempts a
        WHERE NOT a.success AND a.source = $2
        ORDER BY a.created_at DESC OFFSET 19 LIMIT 1;
      END IF;
      retry_at := greatest(username_limit_since, source_limit_since) + interval '15 minutes';
      IF retry_at IS NOT NULL THEN
        RETURN QUERY SELECT false, greatest(1, ceil(extract(epoch FROM retry_at - now())))::integer;
        RETURN;
      END IF;
      INSERT INTO public.login_attempts (username, source, success, created_at) VALUES ($1, $2, $3, now());
      RETURN QUERY SELECT true, 0;
    END
    $$
    """,
    # The first tenant and its first user, instance admin and tenant admin
    # (AUTH-007, ADR-0047). The lock makes two concurrent setups fail
    # rather than both succeed.
    """
    CREATE FUNCTION bootstrap_instance(tenant_name text, username text, display_name text, password_hash text)
    RETURNS TABLE (tenant_id uuid, user_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, pg_temp
    AS $$
    #variable_conflict use_column
    DECLARE
      new_tenant_id uuid := public.uuid7();
      new_user_id uuid := public.uuid7();
    BEGIN
      LOCK TABLE public.users IN EXCLUSIVE MODE;
      IF EXISTS (SELECT 1 FROM public.users) THEN
        RAISE EXCEPTION 'the instance already has users' USING ERRCODE = 'object_not_in_prerequisite_state';
      END IF;
      INSERT INTO public.tenants (id, name, created_at) VALUES (new_tenant_id, $1, now());
      INSERT INTO public.users (id, tenant_id, username, display_name, password_hash, role, instance_admin, created_at)
      VALUES (new_user_id, new_tenant_id, $2, $3, $4, 'tenant_admin', true, now());
      RETURN QUERY SELECT new_tenant_id, new_user_id;
    END
    $$
    """,
]

ROW_LEVEL_SECURITY = [
    statement
    for table in CONTRACT_TABLES
    for statement in (
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
    )
]

APPLICATION_POLICIES = [
    """
    CREATE POLICY tenants_app_select ON tenants FOR SELECT TO mzm_app
    USING (id = app_tenant_id() OR app_is_instance_admin())
    """,
    "CREATE POLICY tenants_app_insert ON tenants FOR INSERT TO mzm_app WITH CHECK (app_is_instance_admin())",
    "CREATE POLICY users_app_select ON users FOR SELECT TO mzm_app USING (tenant_id = app_tenant_id())",
    # Only an instance admin creates instance admins (AUTH-008).
    """
    CREATE POLICY users_app_insert ON users FOR INSERT TO mzm_app
    WITH CHECK (
      (tenant_id = app_tenant_id() AND app_is_tenant_admin() AND NOT instance_admin) OR app_is_instance_admin()
    )
    """,
    """
    CREATE POLICY users_app_update ON users FOR UPDATE TO mzm_app
    USING (tenant_id = app_tenant_id() AND (id = app_user_id() OR app_is_tenant_admin()))
    """,
    """
    CREATE POLICY device_sessions_app_own ON device_sessions TO mzm_app
    USING (tenant_id = app_tenant_id() AND user_id = app_user_id())
    WITH CHECK (tenant_id = app_tenant_id() AND user_id = app_user_id())
    """,
    *(
        f"""
        CREATE POLICY {table}_app_own ON {table} TO mzm_app
        USING (tenant_id = app_tenant_id() AND owner_id = app_user_id())
        WITH CHECK (tenant_id = app_tenant_id() AND owner_id = app_user_id())
        """
        for table in PRIVATE_TABLES
    ),
]

# Owner policies for the pre-authentication functions (ADR-0046).
OWNER_POLICIES = [
    "CREATE POLICY tenants_owner_select ON tenants FOR SELECT TO mzm_owner USING (true)",
    "CREATE POLICY tenants_owner_insert ON tenants FOR INSERT TO mzm_owner WITH CHECK (true)",
    "CREATE POLICY users_owner_select ON users FOR SELECT TO mzm_owner USING (true)",
    "CREATE POLICY users_owner_insert ON users FOR INSERT TO mzm_owner WITH CHECK (true)",
    "CREATE POLICY device_sessions_owner_select ON device_sessions FOR SELECT TO mzm_owner USING (true)",
    "CREATE POLICY device_sessions_owner_update ON device_sessions FOR UPDATE TO mzm_owner USING (true)",
    "CREATE POLICY login_attempts_owner_select ON login_attempts FOR SELECT TO mzm_owner USING (true)",
    "CREATE POLICY login_attempts_owner_insert ON login_attempts FOR INSERT TO mzm_owner WITH CHECK (true)",
    "CREATE POLICY login_attempts_owner_delete ON login_attempts FOR DELETE TO mzm_owner USING (true)",
]

# "Privileges of mzm_app" in the database contract (TEN-004).
PRIVILEGES = [
    "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
    "REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC",
    "ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC",
    "GRANT SELECT, INSERT ON tenants TO mzm_app",
    """
    GRANT SELECT (id, tenant_id, username, display_name, role, instance_admin, created_at, disabled_at)
    ON users TO mzm_app
    """,
    "GRANT INSERT ON users TO mzm_app",
    "GRANT UPDATE (display_name, password_hash, role, disabled_at) ON users TO mzm_app",
    "GRANT SELECT, INSERT, DELETE ON device_sessions TO mzm_app",
    "GRANT UPDATE (revoked_at) ON device_sessions TO mzm_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON conversations TO mzm_app",
    "GRANT SELECT, INSERT ON conversation_messages TO mzm_app",
    "GRANT SELECT, INSERT, UPDATE ON runs TO mzm_app",
    "GRANT SELECT, INSERT ON usage_ledger TO mzm_app",
    """
    GRANT EXECUTE ON FUNCTION app_tenant_id(), app_user_id(), app_is_tenant_admin(), app_is_instance_admin()
      TO mzm_app
    """,
    """
    GRANT EXECUTE ON FUNCTION auth_find_login(text), auth_find_session(bytea), auth_touch_session(uuid),
      auth_record_login_attempt(text, inet, boolean) TO mzm_app
    """,
]


def _execute(statements: list[str]) -> None:
    connection = op.get_bind()
    for statement in statements:
        # One statement at a time, sent as is: the driver prepares each one,
        # and the SQL contains no bind parameters.
        connection.exec_driver_sql(statement)


def upgrade() -> None:
    _execute(
        [
            *HELPER_FUNCTIONS,
            *TABLES,
            *TRIGGERS,
            *PRE_AUTHENTICATION_FUNCTIONS,
            *ROW_LEVEL_SECURITY,
            *APPLICATION_POLICIES,
            *OWNER_POLICIES,
            *PRIVILEGES,
        ]
    )


def downgrade() -> None:
    _execute(
        [
            "ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO PUBLIC",
            *(f"DROP TABLE {table} CASCADE" for table in reversed(CONTRACT_TABLES)),
            "DROP FUNCTION bootstrap_instance(text, text, text, text)",
            "DROP FUNCTION auth_record_login_attempt(text, inet, boolean)",
            "DROP FUNCTION auth_touch_session(uuid)",
            "DROP FUNCTION auth_find_session(bytea)",
            "DROP FUNCTION auth_find_login(text)",
            "DROP FUNCTION runs_check_parent()",
            "DROP FUNCTION users_guard()",
            "DROP FUNCTION uuid7()",
            "DROP FUNCTION app_is_instance_admin()",
            "DROP FUNCTION app_is_tenant_admin()",
            "DROP FUNCTION app_user_id()",
            "DROP FUNCTION app_tenant_id()",
        ]
    )
