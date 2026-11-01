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

## Migrations

`python -m alembic -c migrations/alembic.ini upgrade head`, from the
repository root.

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `MZM_DATABASE_URL` | yes | — | The same URL form, for `mzm_owner`. |
