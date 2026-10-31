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
