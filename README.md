# Mazzamurello

**A private, self-hosted AI assistant for your household.**

> **Status: phase 1 has started.** Accounts, separate conversations with
> versions, streamed answers from a model you configure, and a per-user
> gVisor sandbox where the assistant runs commands, through a web app you can
> install on your phone and computer. Do not rely on it for anything
> important yet.

In the folklore of central Italy, the *mazzamurello* is a small household
spirit: it lives in the house, knows everything that happens there, and
quietly helps the family. This project aims to be exactly that — an assistant
that lives on your own server, works for your family, and keeps what it
knows inside your home.

## What it will be

- **Self-hosted, server only.** One installation per household, deployed with
  Docker Compose on a Linux home server. Like Immich or Home Assistant, but for
  an AI assistant.
- **Private by design.** Your data stays on your server. Every user has private
  data, and every conversation a private, strongly isolated sandbox. Nothing
  runs on the host on behalf of users.
- **Capable.** The assistant can search the web, read pages, run code, install
  software and launch programs — inside each conversation's sandbox, with internet
  access but no view of your home network. Searches go through a search
  engine running on your server, never through the model's provider.
- **Model-agnostic.** Local models (Ollama, llama.cpp, any OpenAI-compatible
  server) or remote providers (e.g. OpenRouter), with per-user and per-space
  rules on what may leave the house.
- **Multi-user, multi-tenant ready.** Built for a family from day one, with a
  tenant model that also allows serving several households or a small
  organization with isolated, private data.
- **Separate conversations.** Many independent chats, one per purpose — on the
  web and on your phone.
- **Transparent memory.** Users can see, edit and delete everything the
  assistant remembers about them.

See [VISION.md](VISION.md) for the full picture, including what Mazzamurello
is deliberately **not**.

## Architecture at a glance

```
 phone / browser
        │  one public HTTP API (OpenAPI, SSE streaming)
 ┌──────▼─────────────────────────────┐   ┌──────────────┐
 │ control plane                      ├──►│ search       │  SearXNG: asks public
 │ (FastAPI, Pydantic AI, Postgres)   │   │ (queries     │  search engines, keeps
 └──────┬─────────────────────────────┘   │  only)       │  no logs
        │ minimal, authenticated API      └──────────────┘
 ┌──────▼──────┐
 │ sandbox     │  the only component allowed to manage containers
 │ driver      │
 └──────┬──────┘
 ┌──────▼──────┐ ┌─────────────┐ ┌─────────────┐
 │ sandbox A   │ │ sandbox B   │ │ sandbox C   │  one per conversation, gVisor,
 │ workspace A │ │ workspace B │ │ workspace C │  internet yes, LAN no, no secrets
 └─────────────┘ └─────────────┘ └─────────────┘
```

The reasoning behind every component is recorded in the
[architecture decision records](specs/adr/), and the security model in the
[threat model](specs/threat-model.md).

## Installation

Mazzamurello runs on one Linux host (x86_64 or arm64) with Docker Compose.
Hardware virtualization is not needed (OPS-009).

**Prerequisites**

- Docker Engine with the Compose plugin.
- gVisor, release `20261026` or newer, installed from
  [gVisor's official repository](https://gvisor.dev/docs/user_guide/install/)
  and registered with Docker as the `runsc` runtime (`sudo runsc install`,
  then reload Docker). Distribution packages are usually far too old.
- About 3 GB of disk for the images, and internet access to build them.

**Install**

```bash
git clone https://github.com/mazzamurello/mazzamurello.git
cd mazzamurello/deploy
docker compose run --rm --no-deps init
docker compose up --detach --build --wait
docker compose run --rm setup
```

1. `init` writes `deploy/.env` with fresh random secrets. Keep it private; it
   is never overwritten. There are no default passwords anywhere (AUTH-007).
2. `up` builds the images and starts the database, the API, the worker, the
   search service, the backup service, the sandbox driver and the network
   guard. The guard installs the `nftables`
   table `inet mazzamurello` on the host, which keeps sandboxes away from your
   home network and from the host itself; it removes the table when it stops.
3. `setup` asks for the household's name and creates its first administrator,
   with the password you choose. It works only once.

The web app now opens at `http://127.0.0.1:8080/` on the server itself, and
the API answers at `http://127.0.0.1:8080/v1`; `curl
http://127.0.0.1:8080/v1/health` says `degraded` until a model is configured.

**Connect a model**

Sign in to the web app as the administrator, open **Settings**, then
**Models**, and choose **Add a connection** (MOD-008):

- **OpenRouter** needs only its API key, and brings every OpenRouter model,
  most used first.
- **Your own server**, such as Ollama, llama.cpp, vLLM or LM Studio, needs
  its address, like `http://192.168.1.10:11434/v1`, and brings every model it
  serves. Addresses on your home network work only for the server's
  administrator, the account `setup` created (MOD-009).

The connection is tested step by step before it is saved; if it fails, the
test says which step failed and why. Then choose the **Default model** that
new conversations start with. Anyone in the household can switch models in a
conversation, from the message box. API keys are stored encrypted and never
shown again.

The same can be done through the API. With Ollama on your network:

```bash
TOKEN=$(curl -s http://127.0.0.1:8080/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username": "YOUR-USERNAME", "password": "YOUR-PASSWORD", "device_name": "terminal"}' \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])')
CONNECTION=$(curl -s http://127.0.0.1:8080/v1/tenant/connections \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "Home server", "kind": "openai", "base_url": "http://192.168.1.10:11434/v1", "location": "local"}' \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])')
curl -s -X PUT http://127.0.0.1:8080/v1/tenant/default-model \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"connection_id\": \"$CONNECTION\", \"model\": \"llama3.2\"}"
```

For OpenRouter, send `{"name": "OpenRouter", "kind": "openrouter",
"api_key": "sk-or-..."}` instead; it reports the cost of each answer, which
is recorded as it is, in US dollars.

**Updating before the first release**

Until the first release, the database schema is rewritten instead of
migrated (ADR-0071). After an update that changes it, set the installation
up again, which deletes its conversations, accounts and settings; `deploy/.env`
and its secrets stay:

```bash
cd deploy
docker compose down --volumes
docker compose up --detach --build --wait
docker compose run --rm setup
```

**Reaching it from other devices**

By default the web app and the API listen only on `127.0.0.1:8080`. To reach
them from your phone, put them behind the reverse proxy you already use for
HTTPS (Caddy, Traefik, nginx), then set in `deploy/.env`:

```bash
MZM_PUBLISH=127.0.0.1:8080
MZM_TRUSTED_PROXIES=172.18.0.1
```

`MZM_TRUSTED_PROXIES` is the address the API sees the proxy connect from, so
that rate limits count the real client (ADR-0047). For a proxy on the same
host it is the gateway of the deployment's network:
`docker network inspect mazzamurello_internal --format '{{(index .IPAM.Config 0).Gateway}}'`.
Run `docker compose up --detach --wait` again after changing `.env`.

The web app needs HTTPS, or `localhost`: it signs in with a `Secure` cookie,
which browsers keep only over HTTPS (ADR-0067). Through the proxy, open the
app's address on your phone and use the browser's **Add to Home Screen** to
install it. Publishing plain HTTP on your network
(`MZM_PUBLISH=0.0.0.0:8080`) leaves only the API usable, and sends passwords
and tokens unencrypted: do it only on a network you fully trust.

The proxy must also let large uploads through: a file attached to a message
can be up to 1 GB (`MZM_UPLOAD_MAX_MB`), and nginx refuses anything over
1 MB unless told otherwise. In nginx, add to the app's `server` block:

```nginx
client_max_body_size 1g;
```

**Web search**

The assistant searches the web through SearXNG, a search engine that runs
on your server as the `search` service and asks public search engines on
the assistant's behalf: they see your server's address and the query, never
who asked (ADR-0075). It keeps no logs. The engines it uses are set in
`deploy/search/settings.yml`: SearXNG's defaults, plus Google. Edit the file
and run `docker compose restart search` to change them. Pages the assistant
reads are fetched from the conversation's sandbox.

Every setting is listed in the
[configuration contract](specs/contracts/configuration.md).

**Sandboxes and workspaces**

Every conversation has a sandbox of its own, which no other conversation
sees (ADR-0078). It keeps one folder, `/workspace`, for what the user wants
to keep from that conversation: scripts, results and notes the assistant
made. Everything else, including software installed into it and programs it
started, is discarded when the answer ends, and the next answer gets a new
sandbox (ADR-0076). Deleting a conversation deletes its workspace; a fork
starts with a copy. Each workspace has a quota, 2 GiB by default
(`MZM_SANDBOX_WORKSPACE_QUOTA_MB`); the assistant is told when it nears it.

**Files** opens a conversation's workspace beside it, or full screen on a
phone: browse it as a tree, preview text, images, PDF, audio and video,
download a file or a folder as a `.zip`, upload, rename, move and delete
(ADR-0079). Files attached to a message upload at once into
`/workspace/uploads/`, and the assistant can offer a file as a card with a
download button. Previews never run a file: an HTML page shows as its
source.

Workspaces from before sandboxes were per conversation are no longer used:
`docker volume ls --filter label=dev.mazzamurello.sandbox=workspace` lists
them, and those without a third identifier in their name can be removed.

**Backups**

The `backup` service backs everything up every night at 03:00 UTC
(`MZM_BACKUP_TIME`) into `deploy/backups/` (`MZM_BACKUP_DIR`), and keeps the
newest 14 archives (`MZM_BACKUP_KEEP`). Each archive is one encrypted file
with the database, the secret key and every workspace (ADR-0077). To make
one now:

```bash
docker compose exec backup python -m mazzamurello_server backup
```

Archives are encrypted with `MZM_BACKUP_KEY` from `deploy/.env`. **Keep a
copy of that key away from the server**, for example in your password
manager: without it, no archive can be restored. An installation from
before backups gets its key with `docker compose run --rm --no-deps init`,
which adds only missing secrets. `/health` reports `degraded` when the last
backup failed or is more than two days old.

Copy the archives elsewhere too, for example with restic:
`restic -r sftp:nas:/backups/mazzamurello backup deploy/backups`. They are
already encrypted.

**Restore**

Into a fresh installation, on this server or another one, with the same
version of Mazzamurello:

1. Install as above with `init` and `up`, but without `setup`.
2. In the new `deploy/.env`, replace `MZM_BACKUP_KEY` with your saved key,
   then put the archive into `deploy/backups/`.
3. Restore, then restart with the restored secret key:

```bash
docker compose run --rm restore /backups/mazzamurello-20261106T030000Z.tar.age
docker compose up --detach --wait
```

To bring back only one user's workspaces from an earlier archive, for example
after something went wrong in them, in a running instance:

```bash
docker compose run --rm restore --workspace alice /backups/mazzamurello-20261101T030000Z.tar.age
```

**Uninstall**

```bash
cd mazzamurello/deploy
docker compose stop sandboxd
docker ps -aq --filter label=dev.mazzamurello.sandbox | xargs -r docker rm -f
docker volume ls -q --filter label=dev.mazzamurello.sandbox | xargs -r docker volume rm
docker network rm mazzamurello-sandboxes
docker compose down --volumes
```

This removes the users' sandboxes and their workspaces, then the deployment;
`down --volumes` deletes the database, with every account and conversation.

## How this project is built

Mazzamurello is written and reviewed by AI agents under strict human
direction. The method is simple to state:

1. **Specs are the source of truth.** Requirements have IDs, priorities and
   verification methods ([specs/](specs/)).
2. **Tests are the executable form of the specs.** They are written before the
   code, and implementation changes may not modify them.
3. **Code is ephemeral; contracts are not.** Code can be regenerated. Database
   schemas, public APIs, on-disk formats and security invariants cannot.
4. **Rules are enforced by CI, not by good intentions.** Pull request types,
   allowed paths, spec format and sign-offs are checked mechanically.

The rules every agent (and human) follows are in [AGENTS.md](AGENTS.md); the
full workflow is in [docs/development/workflow.md](docs/development/workflow.md).

## Repository map

| Path | Contents |
|---|---|
| [`VISION.md`](VISION.md) | What the project is, for whom, and what it is not |
| [`ROADMAP.md`](ROADMAP.md) | Phases and their exit criteria |
| [`AGENTS.md`](AGENTS.md) | Rules of engagement for AI agents and humans |
| [`specs/`](specs/) | Requirements, ADRs, contracts, glossary, threat model |
| [`docs/`](docs/) | Documentation (development workflow today, user docs later) |
| [`src/`](src/) | The server, the web app, the sandbox driver and the network guard |
| [`migrations/`](migrations/) | The database schema, as migrations |
| [`deploy/`](deploy/) | The Compose deployment and its images |
| [`tests/`](tests/) | The executable specs: design, integration, security, web and end-to-end tests |
| [`tools/`](tools/) | Repository governance checks run by CI |

## Contributing

Contributions are welcome, and they start from the specs: a new feature begins
as a spec proposal, not as code. Read [CONTRIBUTING.md](CONTRIBUTING.md) first.
All commits require a [Developer Certificate of Origin](https://developercertificate.org/)
sign-off (`git commit -s`).

Please report security issues privately — see [SECURITY.md](SECURITY.md).

This project has a [Code of Conduct](CODE_OF_CONDUCT.md).
Governance is described in [GOVERNANCE.md](GOVERNANCE.md).

## License

Mazzamurello is free software: the server is licensed under the
[GNU Affero General Public License v3.0 or later](LICENSE). If you run a
modified version as a service for others, you must offer them its source.

Specifications and documentation are licensed under
[CC BY 4.0](LICENSES/CC-BY-4.0.txt). Licensing of every file is declared in
[`REUSE.toml`](REUSE.toml) following the [REUSE](https://reuse.software/)
specification. See [ADR-0002](specs/adr/0002-licensing-agpl-dco-reuse.md).
