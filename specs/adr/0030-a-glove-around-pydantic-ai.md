# ADR-0030: Shape Mazzamurello as a glove around Pydantic AI

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0008, ADR-0027, ADR-0031, ADR-0032, ADR-0033, ADR-0034, ADR-0035, ADR-0036, REPO-010

## Context

Pydantic AI is the agent framework of the server (ADR-0008). It is stable
(2.x), evolves quickly — releases are frequent — and already provides much of
what an assistant needs: a conversation model, streaming events, tool
approvals, durable execution integrations, workspaces, UI protocol adapters,
usage limits, instrumentation, and a harness of ready-made capabilities.

Early designs built parallel concepts next to it: our own message format, our
own event vocabulary, our own approval flow. Each parallel concept is code to
write and maintain, a translation layer to keep correct, and a source of
friction with every framework upgrade.

## Decision

We will shape Mazzamurello **as a glove around Pydantic AI**:

1. **Prefer native concepts.** When Pydantic AI (or its harness) provides a
   concept we need — messages, conversations, events, tools, toolsets,
   capabilities, deferred tools, workspaces, durable execution integrations,
   UI protocols, limits, instrumentation — we use it, and our identifiers and
   data shapes follow it, rather than defining an equivalent of our own.
2. **Deviate only with a reason.** We build something of our own only when the
   native concept does not meet a requirement — typically security,
   isolation or privacy — and the ADR that decides it states why.
3. **Extend at the framework's extension points.** Project-specific behavior
   (egress policy, approval rules, sandbox access) is implemented as
   capabilities, toolsets, hooks or workspace backends, so it composes with the
   framework instead of wrapping it.
4. **Keep the security boundary ours.** Isolation between users and tenants,
   sandboxing and egress restrictions are never delegated to framework
   defaults; framework features that would execute code, fetch URLs or reach
   MCP servers from the control plane are not used there (AGT-013).
5. **Follow the project's evolution.** Upgrades of Pydantic AI and its
   harness are reviewed against their release notes (REPO-010). New features
   that could replace code of ours, or change a decision, are recorded and
   evaluated — as an issue, or as an ADR when a decision changes.

## Consequences

- Less code of our own, and upgrades that bring features instead of
  migrations.
- The project is coupled to Pydantic AI's evolution; this is a deliberate
  bet, mitigated by pinned versions, release-note reviews and the conformance
  and contract tests the framework provides.
- The harness is 0.x: its APIs may change between minor releases, so it is
  pinned exactly and upgraded deliberately.

## Alternatives considered

- **Framework-agnostic core with adapters:** portable in theory, but doubles
  the concepts to maintain and loses most of the framework's value.
