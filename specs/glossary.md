# Glossary

The canonical vocabulary of Mazzamurello (its *ubiquitous language*). Code,
specs, docs and UI use exactly these terms. A new domain concept requires a
new entry here first (ADR-0005).

## Tenancy and identity

| Term | Definition |
|---|---|
| Instance | One installation of Mazzamurello, on one server. |
| Instance admin | The person who operates the instance (host, containers, configuration). Trusted (ADR-0011). |
| Tenant | An isolated group of users with its own data: typically a household, possibly a small organization. |
| Tenant admin | A user who manages a tenant's users, shared spaces and tool permissions. |
| User | A person with an account in exactly one tenant. |
| Private data | Data owned by one user and visible only to that user. The default for all data. |
| Shared space | A container of data explicitly shared among some or all users of a tenant (e.g. family calendar, shopping list). |

## Conversations and agent

| Term | Definition |
|---|---|
| Conversation | An independent chat between a user and the assistant, with its own history. A user has many. |
| Message | One entry in a conversation, from the user or the assistant. |
| Agent | The component that turns a user request into model calls and tool calls. |
| Run | One execution of the agent in response to a message, including all its model and tool calls. |
| Tool | A capability the agent can invoke. All tools are mediated tools. |
| Mediated tool | A tool executed by the control plane, which checks permissions, approvals and records audit events. |
| Capability class | A declared property of a tool used for safety decisions: `reads_private_data`, `ingests_untrusted`, `external_communication`, `irreversible`, `physical`. |
| Untrusted content | Any content not authored by the user or the system: web pages, received emails, external files, sandbox output. |
| Lethal trifecta | The combination of access to private data, exposure to untrusted content and the ability to communicate externally, which enables data exfiltration through prompt injection. |
| Approval | An explicit confirmation by the user before a tool call is executed. |
| Audit event | A record of a tool call, visible to the user it acted for. |
| Scheduled task | A run started by a schedule or trigger rather than by a message. |
| Memory item | A piece of information the assistant retains about a user across conversations. Visible, editable and deletable by the user. |
| Connector | An integration with an external system (calendar, mail, files, home automation), exposed to the agent as mediated tools. |

## Execution

| Term | Definition |
|---|---|
| Control plane | The server components that hold state and secrets: API, agent, memory, model gateway. Never executes user code. |
| Execution plane | Where user code runs: the sandboxes. |
| Sandbox | A per-user isolated execution environment with internet access and no access to local networks. |
| Workspace | The persistent storage of a user's sandbox. |
| Sandbox driver | The only component allowed to manage containers; exposes a minimal API to the control plane. |
| Sandbox bridge | The host network bridge, with a fixed interface name, to which all sandboxes attach; the egress table matches it (ADR-0021). |
| Network guard | A small infrastructure container, with host networking and `NET_ADMIN`, that installs and maintains the egress table on the host (ADR-0021). Never runs user code. |
| Egress table | The dedicated `nftables` table on the host that enforces the egress policy for traffic from the sandbox bridge (ADR-0021). |
| Canary sandbox | A short-lived sandbox the sandbox driver starts to verify isolation before accepting requests. |
| Isolation runtime | The container runtime that enforces sandbox isolation: gVisor (ADR-0023). |
| Egress policy | The network rules that decide which destinations a sandbox may reach. |

## Models

| Term | Definition |
|---|---|
| Model gateway | The component through which every model call passes; applies routing, budgets and the data egress policy. |
| Provider | A source of model inference: a local server or a remote service. |
| Local model | A model served from inside the instance or the household's network. |
| Remote model | A model served by a third party over the internet. |
| Data egress policy | The rules that decide which data may be sent to remote models, per tenant, user and shared space. |

## Process

| Term | Definition |
|---|---|
| Requirement | A numbered, normative statement in `specs/requirements/`. |
| ADR | Architecture decision record in `specs/adr/`. |
| Contract | An interface that outlives the code: public API, database schema, on-disk formats. |
| Invariant | A property that must always hold, typically a security property, verified by tests. |
| Eval | A repeatable scenario that measures agent behavior against one or more models. |
