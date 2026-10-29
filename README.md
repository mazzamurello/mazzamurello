# Mazzamurello

**A private, self-hosted AI assistant for your household.**

> **Status: design phase.** There is no runnable software yet. This repository
> currently contains the project's specifications, architecture decisions and
> governance. Code will follow the specs, not the other way around.

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
