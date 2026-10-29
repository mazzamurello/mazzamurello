# ADR-0012: Mediated tools, capability classes and per-run mitigation of the lethal trifecta

- **Status:** Accepted
- **Date:** 2026-10-29
- **Deciders:** @tapionx
- **Related:** AGT-001, AGT-002, AGT-003, AGT-004, AGT-005, AGT-006, AGT-007, AGT-008, EVL-003

## Context

A personal assistant necessarily combines what has been called the
**lethal trifecta**: access to private data, exposure to untrusted content,
and the ability to communicate externally. With all three, a single injected
instruction ("forward the last invoices to …") can exfiltrate private data.
Sandboxing does not address this: the risk lies in the tools, not in code
execution. Prompts cannot be a security boundary.

The assistant will also be able to act in the physical world (home
automation) and to take irreversible actions (sending, deleting, buying).

## Decision

We will:

1. Make **every tool a mediated tool**, executed by the control plane, which
   checks permissions, requests approvals and writes audit events. The agent
   has no other way to act.
2. Require every tool to declare its **capability classes**:
   `reads_private_data`, `ingests_untrusted`, `external_communication`,
   `irreversible`, `physical`.
3. Label all content entering a run with its **provenance** (trusted or
   untrusted).
4. **Break the trifecta per run:** once untrusted content is part of a run,
   tools in the `external_communication` class require explicit user
   approval.
5. Always require approval for `irreversible` and `physical` tools, and for
   `external_communication` tools by default, independently of rule 4.
6. Make approvals **fail closed** and show exactly what will be done, with
   what data, and where it goes.
7. Let tenant admins configure **per-user tool permissions**. These are
   generic (not age-specific): restricting what a child may do is the
   responsibility of whoever creates the account.
8. Verify behavior with evals that include injection scenarios (ADR-0015).

## Consequences

- More approval prompts; their design matters to avoid approval fatigue.
- Tool authors must classify their tools correctly; a design test rejects
  tools without classes.
- Some fully autonomous workflows (e.g. "every morning, read my mail and
  reply automatically") require explicit, narrowly scoped standing
  permissions, to be specified separately.

## Alternatives considered

- **Rely on the model to refuse injected instructions:** not reliable.
- **Disable external communication entirely:** removes core features.
- **Approval for every tool call:** unusable.
