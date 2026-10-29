# ADR-0020: Prefer open protocols and standards

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** ADR-0004, ADR-0012, AUTH-003

## Context

An assistant with access to "your life" needs connectors: calendar,
contacts, mail, files, home automation, identity. Proprietary APIs tie the
project to specific vendors and exclude self-hosted alternatives.

## Decision

We will prefer open protocols and standards wherever they exist:

| Concern | Standard |
|---|---|
| Calendar and contacts | CalDAV, CardDAV |
| Mail | IMAP, SMTP |
| Files | WebDAV |
| Identity | OpenID Connect |
| Tools | Model Context Protocol (MCP) |
| API description | OpenAPI |
| Telemetry plumbing | OpenTelemetry |
| Agent instructions | AGENTS.md |
| Licensing metadata | REUSE / SPDX |

Vendor-specific connectors may be added when no standard covers the need,
always as mediated tools (ADR-0012).

## Consequences

- Connectors work with many providers, including self-hosted ones.
- Some vendor-specific features may be unavailable through standard protocols.

## Alternatives considered

- **Vendor APIs first:** faster for popular services, at the cost of lock-in.
