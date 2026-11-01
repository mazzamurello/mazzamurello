# Mazzamurello

**A private, self-hosted AI assistant for your household.**

> **Status: phase 0, walking skeleton.** The server runs: accounts, separate
> conversations, streamed answers from a model you configure, and a per-user
> gVisor sandbox where the assistant runs commands. There is no user
> interface yet; everything goes through the HTTP API (ADR-0024). Do not rely
> on it for anything important.

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
  data and a private, strongly isolated sandbox. Nothing runs on the host on
  behalf of users.
- **Capable.** The assistant can search the web, read pages, run code, install
  software and launch programs — inside a per-user sandbox with internet
  access but no view of your home network.
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
 ┌──────▼─────────────────────────────┐
 │ control plane                      │  auth, conversations, memory, agent loop,
 │ (FastAPI, Pydantic AI, Postgres)   │  mediated tools, model gateway, secrets
 └──────┬─────────────────────────────┘
        │ minimal, authenticated API
 ┌──────▼──────┐
 │ sandbox     │  the only component allowed to manage containers
 │ driver      │
 └──────┬──────┘
 ┌──────▼──────┐ ┌─────────────┐ ┌─────────────┐
 │ sandbox A   │ │ sandbox B   │ │ sandbox C   │  one per user, gVisor by default,
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
   sandbox driver and the network guard. The guard installs the `nftables`
   table `inet mazzamurello` on the host, which keeps sandboxes away from your
   home network and from the host itself; it removes the table when it stops.
3. `setup` asks for the household's name and creates its first administrator,
   with the password you choose. It works only once.

The API now answers on `http://127.0.0.1:8080/v1`; `curl
http://127.0.0.1:8080/v1/health` says `degraded` until a model is configured.

**Configure a model**

Models are configured through the API by the administrator (MOD-008); the
settings screen of the web client will use the same API. With a local
OpenAI-compatible server such as Ollama on your network:

```bash
TOKEN=$(curl -s http://127.0.0.1:8080/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username": "YOUR-USERNAME", "password": "YOUR-PASSWORD", "device_name": "terminal"}' \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])')
curl -s http://127.0.0.1:8080/v1/instance/models \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "Local model", "base_url": "http://192.168.1.10:11434/v1", "model": "llama3.2", "paid": false, "is_default": true}'
```

For OpenRouter, set `"api": "openrouter"`, so that the cost it reports for
each answer is recorded as it is, in US dollars:

```bash
curl -s http://127.0.0.1:8080/v1/instance/models \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "OpenRouter", "api": "openrouter", "base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-4o-mini", "api_key": "sk-or-...", "paid": true, "is_default": true}'
```

For another remote OpenAI-compatible provider, use its endpoint, add
`"api_key"`, set `"paid": true` and, optionally, its prices per million
tokens. API keys are stored encrypted and never returned.

**Reaching it from other devices**

By default the API listens only on `127.0.0.1:8080`. To reach it from your
phone, put it behind the reverse proxy you already use for HTTPS (Caddy,
Traefik, nginx), then set in `deploy/.env`:

```bash
MZM_PUBLISH=127.0.0.1:8080
MZM_TRUSTED_PROXIES=172.18.0.1
```

`MZM_TRUSTED_PROXIES` is the address the API sees the proxy connect from, so
that rate limits count the real client (ADR-0047). For a proxy on the same
host it is the gateway of the deployment's network:
`docker network inspect mazzamurello_internal --format '{{(index .IPAM.Config 0).Gateway}}'`.
Run `docker compose up --detach --wait` again after changing `.env`.
Publishing plain HTTP on
your network (`MZM_PUBLISH=0.0.0.0:8080`) sends passwords and tokens
unencrypted: do it only on a network you fully trust.

Every setting is listed in the
[configuration contract](specs/contracts/configuration.md).

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
| [`src/`](src/) | The server, the sandbox driver and the network guard |
| [`migrations/`](migrations/) | The database schema, as migrations |
| [`deploy/`](deploy/) | The Compose deployment and its images |
| [`tests/`](tests/) | The executable specs: design, integration, security and end-to-end tests |
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
