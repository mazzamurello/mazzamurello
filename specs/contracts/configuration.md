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
| `MZM_SECRET_KEY` | yes | — | 32 random bytes, base64url-encoded (for example `python -c "import secrets; print(secrets.token_urlsafe(32))"`). Encrypts the API keys of model configurations (ADR-0051). The API and the worker must share it; changing it makes stored API keys unusable. |

## Worker

`python -m mazzamurello_server worker` (ADR-0052)

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `MZM_DATABASE_URL` | yes | — | The same URL form, for `mzm_app` (TEN-004). |
| `MZM_SECRET_KEY` | yes | — | The same key as the API's. |
| `MZM_RUN_RETENTION_DAYS` | no | `30` | Days after a run finishes before its durable workflow and event stream are deleted (TEN-009), from 1 to 3650. |
| `MZM_SANDBOXD_URL` | yes | — | Base URL of the sandbox driver's API, such as `http://sandboxd:8100/v1`, on the internal network (ADR-0022). |
| `MZM_SANDBOXD_TOKEN` | yes | — | The secret shared with the sandbox driver, at least 32 characters (ADR-0022). |

The same rules apply as for the API: a missing, invalid or unknown `MZM_*`
variable stops the worker before it takes work.

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
| `MZM_SANDBOX_RESOLVER` | no | `9.9.9.9` | IPv4 address of the resolver written into sandboxes (ADR-0021, ADR-0053). |
| `MZM_SANDBOX_CPUS` | no | `1` | CPUs per sandbox, from 0.1 to 64 (SBX-011). |
| `MZM_SANDBOX_MEMORY_MB` | no | `1024` | Memory per sandbox in MiB, from 64 to 262144. |
| `MZM_SANDBOX_PROCESSES` | no | `512` | Processes per sandbox, from 16 to 65536, enforced as `RLIMIT_NPROC`. |
| `MZM_SANDBOX_COMMAND_TIMEOUT_SECONDS` | no | `300` | The longest a command may run, from 1 to 86400. |
| `MZM_SANDBOX_MAX_OUTPUT_BYTES` | no | `1048576` | The most output a command returns, from 1024 to 67108864. |
| `MZM_SANDBOX_IDLE_MINUTES` | no | `30` | Minutes without commands before a sandbox is stopped, from 1 to 10080. |

The minimum gVisor release is `release-20261026.0` (SBX-017, ADR-0053).

## Network guard

`python -m mazzamurello_netguard`, in a container with host networking and
`NET_ADMIN`, named as the driver's `MZM_NETGUARD_CONTAINER` (ADR-0021,
ADR-0053). It reads no configuration: the table `inet mazzamurello` and the
interface `mzmsbx0` are fixed.

## Migrations

`python -m alembic -c migrations/alembic.ini upgrade head`, from the
repository root. After the Alembic revisions it runs the DBOS system
migrations in the `dbos` schema, granting `mzm_app` access (ADR-0052).

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `MZM_DATABASE_URL` | yes | — | The same URL form, for `mzm_owner`. |
