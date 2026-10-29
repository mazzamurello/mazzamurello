# Security Policy

Mazzamurello is meant to hold a family's private data and to execute code on
its behalf. Security is a core requirement, and reports are taken seriously.

## Supported versions

The project is in its design phase and has no releases yet. Once releases
exist, security fixes will be provided for the latest minor version.

| Version | Supported |
|---|---|
| none yet | — |

## Reporting a vulnerability

**Do not open a public issue.** Report privately through GitHub's
[private vulnerability reporting](https://github.com/mazzamurello/mazzamurello/security/advisories/new).

Please include:

- a description of the issue and its impact;
- steps to reproduce, or a proof of concept;
- affected version or commit;
- whether the issue is already public.

## What to expect

- Acknowledgement within **7 days**.
- An initial assessment within **14 days**.
- Coordinated disclosure: we aim to release a fix and publish an advisory
  within **90 days** of the report, and will keep you informed. Credit is
  given unless you prefer otherwise.

## Scope

Especially relevant are issues that break the security model described in the
[threat model](specs/threat-model.md), for example:

- escaping a user sandbox, or reaching the host or the local network from it;
- reading or modifying another user's or tenant's data;
- exfiltrating secrets held by the control plane;
- bypassing tool approvals, including through prompt injection.

Out of scope: attacks that require a malicious instance administrator
(the administrator is trusted, see
[ADR-0011](specs/adr/0011-instance-admin-is-trusted.md)), and vulnerabilities
in third-party dependencies that are not exploitable through Mazzamurello
(please report those upstream).
