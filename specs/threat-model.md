# Threat model

This document describes what Mazzamurello protects, from whom, and how. Every
mitigation points to the requirements that implement it. It is reviewed
whenever a requirement in the security-relevant areas changes.

## Scope and assumptions

- One instance runs on a Linux server under the control of the instance
  admin, in containers, with Docker Engine.
- **The instance admin is trusted** (ADR-0011). They can read all data on
  the server; protecting users from the admin is out of scope.
- The host kernel and the isolation runtime (gVisor, or Kata Containers) are
  kept up to date by the instance admin.
- Models — local or remote — are **not trusted to behave**: any model can be
  manipulated by the content it reads (prompt injection).
- Remote model providers receive whatever the data egress policy allows them
  to receive. What they do with it is governed by their terms, not by us.

## Assets

| ID | Asset |
|---|---|
| A1 | Users' private data: conversations, memory items, files, connector data (mail, calendar) |
| A2 | Shared space data of a tenant |
| A3 | Secrets: connector tokens, model provider keys, session keys, database credentials |
| A4 | The household network and its devices (router, NAS, cameras, home automation) |
| A5 | The host and the other services running on it |
| A6 | Compute, storage and paid model budgets |
| A7 | Integrity of the assistant's actions (what it sends, deletes, buys, switches on) |

## Adversaries

| ID | Adversary | Capabilities |
|---|---|---|
| X1 | Author of untrusted content | Controls a web page, an email, a document or a package the agent reads or installs. The most common adversary. |
| X2 | Curious or malicious user | Has a legitimate account in a tenant; tries to read other users' or tenants' data, or to escape their sandbox. |
| X3 | Compromised sandbox | Arbitrary code running in a user's sandbox (via X1 or X2), with internet access. |
| X4 | Network attacker | Reaches the instance's exposed endpoint from the internet or the LAN. |
| X5 | Supply-chain attacker | Compromises a dependency, a container image or a CI workflow of the project. |

Out of scope: the instance admin (trusted), physical access to the server,
and unknown vulnerabilities in the host kernel or in the isolation runtime
beyond keeping them configurable and updatable.

## Trust boundaries

```
 internet / LAN ──(B1)──► reverse proxy / API
                              │
                         control plane ──(B4)──► remote model providers
                              │      └──(B5)──► connectors (mail, calendar, home automation)
                            (B2)
                              │
                        sandbox driver
                              │
                            (B3)
                              │
                 sandbox A │ sandbox B │ …  ──(B6)──► internet only
```

- **B1** — clients to API: authentication, TLS termination, rate limits.
- **B2** — control plane to sandbox driver: the control plane never touches
  the container runtime.
- **B3** — sandbox to host and to other sandboxes: isolation runtime.
- **B4** — control plane to remote models: data egress policy.
- **B5** — control plane to connectors: mediated tools, permissions, approvals.
- **B6** — sandbox to network: egress policy (internet yes, local networks no).

## Threats and mitigations

| ID | Threat | Adversary | Mitigations |
|---|---|---|---|
| T-01 | A user reads or modifies another user's private data through the API | X2 | TEN-003, TEN-004, TEN-005, TEN-006, TEN-007 |
| T-02 | A user of one tenant reaches data of another tenant | X2 | TEN-002, TEN-003, TEN-006, TEN-008 |
| T-03 | Code in a sandbox escapes to the host | X3 | SBX-002, SBX-003, SBX-011, SBX-012, OPS-004 |
| T-04 | Code in a sandbox scans or attacks the LAN, the host's services or cloud metadata endpoints | X1, X3 | SBX-005, SBX-007, OPS-003 |
| T-05 | Code in one sandbox reaches another user's sandbox | X3 | SBX-001, SBX-006 |
| T-06 | Secrets are stolen from inside a sandbox | X3 | SBX-008, MOD-002 |
| T-07 | Compromise of the control plane yields control of the container runtime (root on the host) | X4, X5 | SBX-009 |
| T-08 | **Lethal trifecta:** injected instructions make the agent send private data to an attacker (e.g. "forward the last invoices to …") | X1 | AGT-001, AGT-003, AGT-004, AGT-005, EVL-003 |
| T-09 | Injected instructions trigger irreversible or physical actions (delete files, buy, open the gate) | X1 | AGT-005, AGT-006, AGT-007, AGT-002 |
| T-10 | A user's actions on their behalf are not visible, so abuse goes unnoticed | X1, X2 | AGT-008 |
| T-11 | Private data is sent to a remote model against the household's wishes | X1, X2 | MOD-003, MOD-005 |
| T-12 | Personal data leaks through logs, traces or telemetry | X4, X5 | OBS-001, OBS-002, OBS-003, OBS-004, OBS-005 |
| T-13 | A user cannot see or remove what the assistant retained about them | — | MEM-001, MEM-002, MEM-003, MEM-004 |
| T-14 | Unauthenticated access or account takeover through the exposed endpoint | X4 | AUTH-001, AUTH-002, OPS-003 |
| T-15 | Resource exhaustion: a sandbox or a user consumes all CPU, memory, disk or model budget | X2, X3 | SBX-011, MOD-004 |
| T-16 | Malicious pull request or compromised CI action injects code or steals secrets | X5 | REPO-001, REPO-005, REPO-007, REPO-008 |
| T-17 | Tampered release images | X5 | OPS-007 |

## The lethal trifecta in Mazzamurello

The assistant necessarily combines all three elements: it reads private data,
it reads untrusted content, and some tools communicate externally. The
sandbox does not help here — the risk lives in the tools. The mitigation is
to break the trifecta **within each run**:

1. Every tool declares its capability classes (AGT-005).
2. Content entering a run is labeled with its provenance (AGT-003).
3. Once untrusted content is part of a run, tools in the
   `external_communication` class require explicit user approval (AGT-004).
4. Approvals fail closed (AGT-007) and every tool call is auditable
   (AGT-008).
5. Evals include injection scenarios that must not exfiltrate (EVL-003).

Prompts are never relied upon as a security boundary.

## Residual risks

- **Exfiltration from a compromised sandbox.** Internet egress is allowed by
  design; a compromised sandbox can send out the data it contains. This is
  bounded to that user's workspace, which never contains secrets (SBX-008).
- **Approval fatigue.** Users may approve requests without reading them.
  Approval prompts must show what will be sent and where.
- **Model-level manipulation without tools.** An injected page can still make
  the assistant give a wrong answer. Provenance labels make this visible but
  cannot prevent it.
- **Isolation runtime vulnerabilities.** gVisor reduces but does not
  eliminate kernel attack surface; Kata Containers is available for stronger
  isolation (ADR-0010).
