# Vision

## The problem

Capable AI assistants today are cloud services. To get an assistant that can
search the web, run code, remember context and act on your behalf, you hand
your life — mail, calendar, documents, family details — to a third party.

Open-source alternatives exist, but they tend to fall into two camps:

- **Chat front ends** that are pleasant to use but cannot *do* much: no real
  execution environment, no scheduling, weak agentic behavior.
- **Powerful agents** designed for a single technical user on their own
  machine, executing commands directly on the host, with permissive security
  defaults and no notion of multiple users.

Neither is suitable for a family that wants a capable assistant, privately,
on a server in the house.

## The goal

Mazzamurello is a **self-hosted, private, capable AI assistant for a
household**. One installation serves one family. Every member has:

- private conversations — many of them, one per purpose;
- private memory that they can inspect, edit and delete;
- a private, strongly isolated sandbox where the assistant can browse,
  install software and run programs;
- access through the web and their phone, by text and by voice;
- an experience that does not ask them to give anything up compared with
  hosted assistants: rich answers, files and photos, artifacts, versions,
  notifications.

The family can also have **shared spaces** — a shared calendar, a shopping
list, household documents — that are explicitly shared, never by accident.

The project's first user is its author, who needs it every day. It is built
in the open so that anyone can have the same: a local, private and secure
assistant.

## Principles

1. **Privacy is the default, not a setting.** Data stays on the server. What
   may be sent to a remote model is governed by explicit policy.
2. **Strong isolation.** Users are isolated from each other, sandboxes from
   the host and from the home network. Isolation is enforced by the database
   and the runtime, not by application code paths alone.
3. **Nothing runs on the host on behalf of users.** All execution happens in
   per-user sandboxes.
4. **The assistant acts through mediated tools.** Permissions, approvals and
   audit logs live in the control plane, not in prompts.
5. **Transparency.** Users can see what the assistant remembers, which model
   answered, and what tools it used.
6. **Model freedom.** Local and remote models are first-class citizens.
7. **Open standards.** OpenAPI, OIDC, MCP, CalDAV/CardDAV, IMAP, WebDAV,
   AGENTS.md — before proprietary integrations.
8. **Built for a family, ready for more.** The data model is multi-tenant
   from the start, so the same software can serve several households or a
   small organization.

## Who it is for

- **Primary:** a technically capable person who runs a home server (the kind
  of person who self-hosts Immich, Nextcloud or Home Assistant) and wants a
  private assistant for themselves and their family.
- **Secondary:** small organizations or community operators who want to host
  isolated assistants for several households or a small team.

## What Mazzamurello is not

- **Not a cloud service.** There is no hosted offering by this project.
- **Not a desktop or laptop app.** The server runs only in containers on a
  Linux server. It is not installed on a Mac or Windows workstation, and it
  never executes commands on the host.
- **Not a single-chat messaging bot.** It is organized around separate
  conversations, not around one endless thread in a messaging app.
- **Not an enterprise agent platform.** No agent marketplaces, department
  hierarchies or billing. Multi-tenancy exists for isolation, not for sales.
- **Not a parental-control product.** Tenant admins configure per-user tool
  permissions; the software does not implement age-specific behavior.
- **Not protection against a malicious server administrator.** The instance
  administrator is trusted (see [ADR-0011](specs/adr/0011-instance-admin-is-trusted.md)).
