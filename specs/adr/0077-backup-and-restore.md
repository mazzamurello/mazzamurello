# ADR-0077: Backup and restore

- **Status:** Accepted
- **Date:** 2026-11-05
- **Deciders:** @tapionx
- **Related:** ADR-0011, ADR-0022, ADR-0051, ADR-0054, ADR-0071, ADR-0076, OPS-006, OPS-010, OPS-011, SBX-009, SBX-020

## Context

A household's data is its database (accounts, conversations, connections,
costs, stored runs), its users' workspaces (ADR-0076), and the secret key
that encrypts its connections' API keys (ADR-0051): a database restored
without that key has every stored API key unreadable.

Self-hosted projects handle this in a few ways (survey of 2026-11-05):
Immich dumps its database every night and keeps 14 dumps, and warns never
to copy a live database folder; Home Assistant encrypts its backups with a
key the user must keep in an "emergency kit", without which nothing can be
restored; Nextcloud's all-in-one image restores a whole instance from an
archive and its password; Vaultwarden, Paperless-ngx and Forgejo offer a
backup or export command, while restoring is often manual. Off-site copies
are left to tools such as restic or Borg.

Only the sandbox driver may talk to the container runtime (SBX-009), so no
other component can read a workspace volume.

## Decision

1. **One command makes one archive.** `docker compose run --rm backup`
   writes `sibillo-<UTC date and time>.tar.age` into the backup folder
   of the host. The archive holds:
   - `manifest.json`: the Sibillo version, the time, and the size and
     SHA-256 of every other entry;
   - `database.dump`: `pg_dump` of the database in its custom format, made
     as PostgreSQL's superuser, so row-level security hides nothing;
   - `secret-key`: the instance's `SIBILLO_SECRET_KEY`;
   - `workspaces/<tenant>/<user>.tar`: every user's workspace.
2. **Workspaces go through the driver** (SBX-020): it streams a workspace as
   a tar archive, and replaces a stopped sandbox's workspace with one. The
   backup never touches Docker.
3. **Consistency:** the backup waits until no run is queued or running, up
   to ten minutes, then dumps the database and exports the workspaces right
   away. A run started during the export may leave a workspace a few
   seconds newer than the database; the archive says when each part was
   taken.
4. **Encrypted with a backup key** (`age`): `init` writes a new age
   identity into `.env` as `SIBILLO_BACKUP_KEY`, and archives are encrypted to
   its recipient. The household must keep a copy of it away from the
   server: without it, no archive can be restored. Since the archive is
   encrypted, it can hold the secret key, and a restore needs only the
   archive and the backup key. A key rather than a passphrase: `age` reads
   passphrases only from a terminal, while a key encrypts and decrypts
   unattended, as nightly backups and tests need (spike of 2026-11-05).
5. **Restore into a fresh installation.** With the household's backup key
   in the new installation's `.env`, `docker compose run --rm restore FILE`
   decrypts the archive, checks the manifest and the checksums, refuses a
   database that has users and an archive of another Sibillo version
   (before the first release, ADR-0071), loads the database, writes the
   archive's secret key into `.env`, and imports the workspaces. It runs
   nothing from the archive.
6. **One workspace from an older archive:** `restore --workspace USERNAME
   FILE` replaces only that user's workspace, in a running instance, after
   stopping their sandbox: the way back from a workspace that went wrong
   (T-33).
7. **Every night, by itself** (OPS-010): a `backup` service in the Compose
   deployment makes an archive every day at `SIBILLO_BACKUP_TIME` (03:00 UTC by
   default) and keeps the newest `SIBILLO_BACKUP_KEEP` (14). It writes the
   outcome of each attempt to `status.json` in the backup folder.
8. **A failing backup does not go unnoticed** (OPS-011): `/health` reports
   `degraded` when the newest backup attempt failed, or when the last
   successful one is older than two days.
9. **Off-site copies are the household's:** the README shows how to copy
   the backup folder elsewhere with restic or Borg; the archives are already
   encrypted.
10. **Checked by CI** (OPS-006): the end-to-end test backs up a deployment
    with a conversation, a connection and a file in a workspace, restores
    the archive into a new deployment, and finds all three working.

## Consequences

- A household restores everything from one file and one key, and
  has two weeks of nightly archives without setting anything up.
- Losing the backup key loses every archive, as with Home Assistant's key;
  the README and `init` say so.
- The backup folder needs space for fourteen archives of the database and
  the workspaces; the workspace quota (ADR-0076) keeps them small.
- Restoring before the first release needs the same version that made the
  archive; afterwards, OPS-005 makes older archives restorable.

## Alternatives considered

- **Copying the volumes while the instance runs:** a live database folder
  may not be restorable.
- **No encryption,** relying on where the archives are kept: simpler, but
  every conversation and every connection key would sit in plain files,
  often copied off-site.
- **A backup command only, with cron left to the household:** a schedule
  nobody sets up is a backup nobody has.
- **Backing up whole containers:** they are rebuilt from images, and their
  disks are discarded by design (ADR-0076).
