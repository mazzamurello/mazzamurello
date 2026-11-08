# Configuration contract

How the server is configured (ADR-0050). Each process reads only the
environment variables listed for it. In the API process, a required variable
that is missing, a value that is invalid, or an `MZM_*` variable not listed
for it stops the process before it listens, with an error naming the
variable.

## API process

`python -m mazzamurello_server api`

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `MZM_DATABASE_URL` | yes | — | `postgresql://USER:PASSWORD@HOST:PORT/DATABASE`. The API connects as `mzm_app` (TEN-004). |
| `MZM_HTTP_HOST` | no | `0.0.0.0` | Address the API listens on. |
| `MZM_HTTP_PORT` | no | `8000` | Port the API listens on, from 1 to 65535. |
| `MZM_TRUSTED_PROXIES` | no | empty | Comma-separated IP addresses or CIDR networks of trusted proxies. The source address of a request from a trusted proxy is the rightmost address of `X-Forwarded-For` that is not a trusted proxy; from any other peer, it is the peer's address. |
| `MZM_WEB_ROOT` | no | the web app built into the image | Directory of the built web app, served at `/` (ADR-0067). When it does not exist, only the API is served. |
| `MZM_SANDBOXD_URL` | yes | — | Base URL of the sandbox driver's API, for `/health` (ADR-0054). |
| `MZM_SANDBOXD_TOKEN` | yes | — | The secret shared with the sandbox driver. |
| `MZM_SECRET_KEY` | yes | — | 32 random bytes, base64url-encoded (for example `python -c "import secrets; print(secrets.token_urlsafe(32))"`). Encrypts the API keys of connections (ADR-0051, ADR-0069). The API and the worker must share it; changing it makes stored API keys unusable. |
| `MZM_UPLOAD_MAX_MB` | no | `1024` | The largest file one upload may bring into a workspace, in MiB, from 1 to 1048576 (CNV-017, ADR-0079). A reverse proxy in front of the API must let bodies this large through. |
| `MZM_BACKUP_STATUS` | no | empty | Path of the backup service's `status.json` (ADR-0077). When set, `/health` is `degraded` when the file is missing, when the newest attempt failed, or when neither the last success nor the schedule's start is within the last two days (OPS-011). |

## Worker

`python -m mazzamurello_server worker` (ADR-0052)

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `MZM_DATABASE_URL` | yes | — | The same URL form, for `mzm_app` (TEN-004). |
| `MZM_SECRET_KEY` | yes | — | The same key as the API's. |
| `MZM_RUN_RETENTION_DAYS` | no | `30` | Days after a run finishes before its durable workflow and event stream are deleted (TEN-009), from 1 to 3650. |
| `MZM_TEMPORARY_SWEEP_SECONDS` | no | `600` | Seconds between two sweeps for temporary conversations to delete (CNV-011, ADR-0082), from 1 to 86400. |
| `MZM_SANDBOXD_URL` | yes | — | Base URL of the sandbox driver's API, such as `http://sandboxd:8100/v1`, on the internal network (ADR-0022). |
| `MZM_SANDBOXD_TOKEN` | yes | — | The secret shared with the sandbox driver, at least 32 characters (ADR-0022). |
| `MZM_SEARCH_URL` | no | empty | Base URL of the search service, such as `http://search:8080`, on the `search` network (ADR-0075). When empty, the agent has no `web_search` tool (AGT-020). |

The same rules apply as for the API: a missing, invalid or unknown `MZM_*`
variable stops the worker before it takes work.

## Search service

The `search` service runs SearXNG (ADR-0075) with the settings in
`deploy/search/settings.yml`, which the deployment mounts read-only. An
instance admin changes the engines there, and restarts the service. The
service reads no `MZM_*` variable and generates its own secret at start.

## Backup service

`python -m mazzamurello_server backup` makes one archive and exits;
`backup --schedule` makes one every day at `MZM_BACKUP_TIME` and runs until
stopped (ADR-0077, OPS-006, OPS-010). When the schedule starts, and after
each attempt, it writes `status.json` into `MZM_BACKUP_DIR`: `{"started",
"last_attempt", "last_success", "outcome", "archive", "error"}`, with times
in UTC, `null` for what has not happened yet, and `outcome` `succeeded` or
`failed`.

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `MZM_DATABASE_URL` | yes | — | The database URL, for PostgreSQL's superuser, so that row-level security hides nothing from `pg_dump`. |
| `MZM_SECRET_KEY` | yes | — | The instance's secret key, which the archive holds. |
| `MZM_BACKUP_KEY` | yes | — | The backup key: an age identity, `AGE-SECRET-KEY-1…`, whose recipient encrypts archives and which decrypts them. |
| `MZM_SANDBOXD_URL`, `MZM_SANDBOXD_TOKEN` | yes | — | The sandbox driver, which exports workspaces (SBX-020). |
| `MZM_BACKUP_DIR` | no | `/backups` | Where archives and `status.json` are written. |
| `MZM_BACKUP_TIME` | no | `03:00` | When the daily backup starts, `HH:MM` in UTC. |
| `MZM_BACKUP_KEEP` | no | `14` | How many of the newest archives are kept, from 1 to 365; older ones are deleted after a successful backup. |

`python -m mazzamurello_server restore FILE` restores an archive into a
fresh installation, decrypting it with `MZM_BACKUP_KEY`, which must be the
key of the instance that made it; with `--config PATH` it writes the
archive's secret key into that `.env` file. `restore --workspace
USERNAME FILE` restores the workspaces of that user's conversations into a running instance. Both
read the variables above.

## Sandbox driver

`python -m mazzamurello_sandboxd` (ADR-0022, ADR-0053). It reaches Docker
through the standard `DOCKER_HOST` variable, or the default socket. The same
rules apply: a missing, invalid or unknown `MZM_*` variable stops it before
it listens.

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `MZM_SANDBOXD_HOST` | no | `0.0.0.0` | Address the driver listens on, on the internal network only (OPS-003). |
| `MZM_SANDBOXD_PORT` | no | `8100` | Port the driver listens on. |
| `MZM_SANDBOXD_TOKEN` | yes | — | The secret every request must present, at least 32 characters. |
| `MZM_SANDBOX_IMAGE` | yes | — | The sandbox image, built from `deploy/images/sandbox`. |
| `MZM_SANDBOX_RUNTIME` | no | `runsc` | The Docker runtime name of gVisor; the canary checks that it is gVisor (SBX-002, SBX-003). |
| `MZM_NETGUARD_CONTAINER` | no | `mazzamurello-netguard` | The network guard's container, whose health the driver follows (ADR-0053). |
| `MZM_SANDBOX_MINIMUM_GVISOR_RELEASE` | no | the built-in minimum | A gVisor release such as `release-20261101.0`, newer than the built-in minimum, that the driver requires instead; an older one is an error (ADR-0058, SBX-017). |
| `MZM_SANDBOX_RESOLVER` | no | `9.9.9.9` | IPv4 address of the resolver written into sandboxes (ADR-0021, ADR-0053). |
| `MZM_SANDBOX_CPUS` | no | `1` | CPUs per sandbox, from 0.1 to 64 (SBX-011). |
| `MZM_SANDBOX_MEMORY_MB` | no | `1024` | Memory per sandbox in MiB, from 64 to 262144. |
| `MZM_SANDBOX_PROCESSES` | no | `512` | Processes per sandbox, from 16 to 65536, enforced as `RLIMIT_NPROC`. |
| `MZM_SANDBOX_COMMAND_TIMEOUT_SECONDS` | no | `300` | The longest a command may run, from 1 to 86400. |
| `MZM_SANDBOX_MAX_OUTPUT_BYTES` | no | `1048576` | The most output a command returns, from 1024 to 67108864. |
| `MZM_SANDBOX_WORKSPACE_QUOTA_MB` | no | `2048` | The workspace quota in MiB, from 1 to 1048576 (SBX-019). |
| `MZM_SANDBOX_IDLE_MINUTES` | no | `5` | Minutes without commands before a sandbox is stopped and its container removed, for a run that ended without stopping it (SBX-018, ADR-0078), from 1 to 10080. |

The minimum gVisor release is `release-20261026.0` (SBX-017, ADR-0053).

## Network guard

`python -m mazzamurello_netguard`, in a container with host networking and
`NET_ADMIN`, named as the driver's `MZM_NETGUARD_CONTAINER` (ADR-0021,
ADR-0053). It reads no configuration: the table `inet mazzamurello` and the
interface `mzmsbx0` are fixed.

## Operator commands

`python -m mazzamurello_server init --output PATH` writes a deployment's
`.env` file with fresh random secrets (ADR-0054). When `PATH` exists, it adds
only the secrets missing from it, such as a backup key, and
changes nothing else. It reads no configuration.

`python -m mazzamurello_server setup` creates the first tenant and its first
user, instance admin and tenant admin, through `bootstrap_instance`
(AUTH-007). It asks, in this order, for the tenant's name, the username, the
display name and the password; on a terminal the password is hidden and asked
twice, otherwise each answer is one line of standard input and the password
is read once. It refuses when any user exists.

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `MZM_DATABASE_URL` | yes | — | The database URL, for `mzm_owner`. |

## Deployment

`deploy/compose.yaml` reads `deploy/.env` (ADR-0054) and gives each service
only its own variables above. `init` writes the file into the directory named
by `MZM_CONFIG_DIR` in the environment of the `docker compose` command,
`deploy/` by default. The file holds:

| Variable | Written by `init` | Meaning |
|---|---|---|
| `MZM_POSTGRES_PASSWORD` | yes | Password of PostgreSQL's superuser, used by the database initialization, backups and restores. |
| `MZM_OWNER_PASSWORD` | yes | Password of `mzm_owner`, used by migrations and `setup`. |
| `MZM_APP_PASSWORD` | yes | Password of `mzm_app`, used by the API and the worker. |
| `MZM_SECRET_KEY` | yes | As above. |
| `MZM_SANDBOXD_TOKEN` | yes | As above. |
| `MZM_BACKUP_KEY` | yes | As above. Keep a copy away from the server: without it, no archive can be restored. |
| `MZM_BACKUP_DIR` | no | The host folder for archives, relative to `deploy/` or absolute; default `./backups`. |
| `MZM_PUBLISH` | no | Where the API is published, `HOST:PORT`; default `127.0.0.1:8080`. |
| `MZM_TRUSTED_PROXIES`, `MZM_RUN_RETENTION_DAYS`, `MZM_TEMPORARY_SWEEP_SECONDS`, `MZM_SANDBOX_MINIMUM_GVISOR_RELEASE`, `MZM_SANDBOX_RESOLVER`, `MZM_SANDBOX_CPUS`, `MZM_SANDBOX_MEMORY_MB`, `MZM_SANDBOX_PROCESSES`, `MZM_SANDBOX_COMMAND_TIMEOUT_SECONDS`, `MZM_SANDBOX_MAX_OUTPUT_BYTES`, `MZM_SANDBOX_IDLE_MINUTES`, `MZM_SANDBOX_WORKSPACE_QUOTA_MB`, `MZM_BACKUP_TIME`, `MZM_BACKUP_KEEP`, `MZM_UPLOAD_MAX_MB` | no | Passed to the services that read them, with the defaults above. |

## Migrations

`python -m alembic -c migrations/alembic.ini upgrade head`, from the
repository root. After the Alembic revisions it runs the DBOS system
migrations in the `dbos` schema, granting `mzm_app` access (ADR-0052).

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `MZM_DATABASE_URL` | yes | — | The same URL form, for `mzm_owner`. |
