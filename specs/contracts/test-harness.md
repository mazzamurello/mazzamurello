# Test harness contract

How tests reach the system under test. Tests are written before the
implementation by authors who do not read it (ADR-0045), so this interface is
fixed here and both sides conform to it. Interfaces to the server application
are added before the first tests that need them.

## Database

Tests that need a database use this procedure, once per test session:

1. Start PostgreSQL 17 from the official `postgres` image, with
   testcontainers (ADR-0008). The test suite pins the exact image version.
   Where Docker is not available, these tests fail; they never skip.
2. As the image's superuser, run the initialization of the
   [database contract](database.md#initialization), with passwords chosen by
   the test suite.
3. From the repository root, run the migrations as `mzm_owner`:

   ```
   python -m alembic -c migrations/alembic.ini upgrade head
   ```

   with the environment variable `MZM_DATABASE_URL` set to a URL of the form
   `postgresql://mzm_owner:PASSWORD@HOST:PORT/mazzamurello`. The migration
   environment reads only this variable and chooses its own driver. A failing
   migration fails the session.

## Connections used by tests

| Role | Used for |
|---|---|
| `mzm_app` | Every assertion about what the application may read or write. Tests set the request context of the database contract themselves, with `set_config(name, value, true)` inside the transaction. |
| `mzm_owner` | Nothing. Running services never use it either (TEN-004). |
| Superuser | Inspecting the catalogs in design tests, and arranging test data that the application would otherwise create through flows not under test. Never for an assertion about what `mzm_app` can do. |

Tests use psycopg 3. Each test creates its own tenants and users with fresh
identifiers, so tests do not depend on each other or on their order, and the
database is not reset between tests.

## Server

Tests that need the API use this procedure, once per test session, after the
database procedure (ADR-0050):

1. From the repository root, start the API process,
   `python -m mazzamurello_server api`, with this environment
   ([configuration](configuration.md)):

   | Variable | Value |
   |---|---|
   | `MZM_DATABASE_URL` | The database of the test session, as `mzm_app` |
   | `MZM_HTTP_HOST` | `127.0.0.1` |
   | `MZM_HTTP_PORT` | A free port chosen by the test suite |
   | `MZM_TRUSTED_PROXIES` | `127.0.0.1` |
   | `MZM_SECRET_KEY` | A random key chosen by the test suite |
   | `MZM_SANDBOXD_URL`, `MZM_SANDBOXD_TOKEN` | Those of the sandbox driver below |

2. The server is ready when `GET /v1/me` without a token answers `401`. A
   server that is not ready within 30 seconds, or exits, fails the session,
   with its output in the failure.
3. Start the worker, `python -m mazzamurello_server worker`, from the
   repository root, with `MZM_DATABASE_URL` and `MZM_SECRET_KEY` as for the
   API (ADR-0052), and `MZM_SANDBOXD_URL` and `MZM_SANDBOXD_TOKEN` of the
   sandbox driver below. The worker has no readiness signal: tests wait for the
   outcome of runs, with a timeout.
4. Tests call the API over HTTP at `http://127.0.0.1:PORT/v1` and stop both
   processes at the end of the session. To check recovery (AGT-010), a test
   may stop the worker, with `SIGKILL`, and start it again with the same
   environment.

Tests choose the source address of each request with `X-Forwarded-For`, so
that rate limits (ADR-0047) count only the attempts of the test that made
them. Users that a test does not create through the API are arranged in the
database as superuser, with password hashes in the Argon2id encoded format
(AUTH-001), which the server verifies.

## Models

Tests never reach a real model. The test suite serves its own model: an
OpenAI-compatible chat completions endpoint on `127.0.0.1`, whose answers
the tests script, and configures it through the API as an instance model
(ADR-0051). Endpoints on the loopback address are allowed only for instance
models, so tests use instance models for runs.

## Sandboxes

Tests that need sandboxes, and the server, which needs the sandbox driver,
use this procedure once per test session, before starting the worker
(ADR-0053). It needs Docker with gVisor registered as the `runsc` runtime;
where it is missing, these tests fail; they never skip.

1. Build the images `deploy/images/sandbox` and `deploy/images/netguard`,
   with tags chosen by the test suite.
2. Start the network guard: the `netguard` image as a container named by the
   test suite, with `--network host` and `--cap-add NET_ADMIN`, and nothing
   else. Wait until Docker reports it healthy.
3. From the repository root, start the sandbox driver,
   `python -m mazzamurello_sandboxd`, with `MZM_SANDBOXD_HOST` `127.0.0.1`, a
   free port, a random `MZM_SANDBOXD_TOKEN`, `MZM_SANDBOX_IMAGE` and
   `MZM_NETGUARD_CONTAINER` from the steps above, and limits small enough for
   tests to reach them. It is ready when `GET /v1/health` with the token
   answers `200`, within 120 seconds.
4. At the end of the session, stop the driver, then the network guard, which
   removes its table, and remove every container and volume the session's
   driver created, and the sandbox bridge.

Security tests check isolation from inside sandboxes, through the driver's
`exec`, and may remove the table with `nft` inside the network guard's
container to check that sandboxes stop (SBX-015).

## End-to-end

The end-to-end test follows the README on a fresh deployment (ADR-0054).
It runs before the tests that use the procedures above, because the
deployment's network guard and sandbox bridge are those of the host.

1. Copy `deploy/` to a temporary directory and run, from there, the README's
   commands: `init`, then `docker compose up` with a Compose project name
   chosen by the test suite and `MZM_PUBLISH` set to a free port of
   `127.0.0.1`, then `setup`, with the answers on standard input.
2. Sign in as the first administrator, configure the model the tests serve
   as the instance's default model, at an address of the host that the
   deployment's containers reach, and hold a conversation that runs a command
   in the sandbox.
3. At the end, `docker compose down` with its volumes, and remove the
   temporary directory and the deployment's images.

