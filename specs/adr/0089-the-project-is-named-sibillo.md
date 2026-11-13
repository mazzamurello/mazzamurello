# ADR-0089: The project is named Sibillo

- **Status:** Accepted
- **Date:** 2026-11-13
- **Deciders:** @tapionx
- **Related:** ADR-0002, ADR-0070, ADR-0071

## Context

The project was named Mazzamurello, after the house sprite of central
Italian folklore that its sprite draws (ADR-0070). The word is long and hard
to spell for anyone outside Italy, which hurts a project meant for
households anywhere. The short prefix `mzm`, used for configuration,
database roles, events and names in the deployment, is opaque to anyone who
does not already know it.

## Decision

1. **The project, the app and the assistant are named Sibillo.** Sibillo is
   a mazzamurello, by name: the folklore, the sprite and its drawing stay.
2. **No abbreviation.** Every name that used `mzm` uses `sibillo` in full:
   configuration variables start with `SIBILLO_`, the database roles are
   `sibillo_owner` and `sibillo_app`, the session cookie is
   `sibillo_session`, the client's request header is `X-Sibillo-Request`,
   and the run's own events are `sibillo.title`, `sibillo.plan` and
   `sibillo.usage`.
3. **One change.** The rename touches specs, code, tests, deployment,
   documentation and the project's rules at once, so it is made in a single
   commit, outside the typed commits of ADR-0060, by the maintainer.
4. **No migration.** Until the first release the schema is rewritten rather
   than migrated (ADR-0071): an installation is set up again, with its
   `.env` variables renamed.
5. **The repository moves with the name:** it is `sibillo-ai/sibillo` on
   GitHub, and its links say so; GitHub keeps the old address working.

## Consequences

- Existing installations start again from an empty database, and their
  users sign in again: the cookie has a new name.
- Configuration written for the old name stops working: every `MZM_`
  variable must be renamed to `SIBILLO_`.
- The narrative of the house sprite is unchanged; only its name is new.

## Alternatives considered

- **Keep Mazzamurello:** see the context.
- **Generic names without the project's name** for configuration and the
  database: a variable such as `SECRET_KEY` exported in an operator's shell
  would silently override the installation's own, since Compose prefers the
  shell to `.env`; the full name avoids that without an abbreviation.
