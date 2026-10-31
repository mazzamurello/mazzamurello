# ADR-0044: Editable instructions and skills in the open Agent Skills format

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0012, ADR-0030, ADR-0035, ADR-0043, AGT-003, AGT-017, CNV-013, CNV-014

## Context

Journey J13 of the [product description](../product.md) asks to replace or
extend the assistant's instructions, and to write or import skills. Skills
are reusable packages of instructions and files that the model loads only
when relevant. The Agent Skills specification (agentskills.io) is an open
format, a folder with a `SKILL.md` file, adopted by several agent tools. The
harness `Skills` capability implements it: it lists skills by name and
description and gives the model tools to load a skill and its bundled files
from a workspace.

The threat model never relies on prompts as a security boundary: permissions,
approvals, row-level security and the sandbox enforce the rules.

## Decision

1. **Instructions** have two independent layers, each with a user default and
   a per-conversation value (CNV-014):
   - **base instructions**, which the user may replace entirely and restore
     to the instance default;
   - **additional instructions**, appended after the base instructions.
   Because no security control depends on instructions, users may change them
   freely. The text the system adds for safety in specific situations, such as
   provenance labels (AGT-003), is not part of either layer and cannot be
   removed by them.
2. **Skills** use the Agent Skills format and the harness `Skills` capability
   (ADR-0043). A user's skills are stored by the control plane as private
   data and copied into a reserved, read-only directory of the user's
   workspace, from which `Skills` reads them through the workspace backend
   (ADR-0035).
3. Skills can be created and edited in the client, uploaded as an archive, or
   imported from a URL; the download happens in the user's sandbox. Imported
   skills are untrusted content: their text carries untrusted provenance
   (AGT-003), and their scripts run only in the sandbox (AGT-017).
4. Skills are enabled per user; a conversation can disable some of them
   (CNV-013).

## Consequences

- Skills written for other agent tools work unchanged when they need only
  instructions, files and a shell.
- A skill can make the assistant worse but cannot grant it new permissions.
- Sharing skills with the household is possible later as an explicit copy
  (CNV-010).

## Alternatives considered

- **Fixed base instructions, additions only:** safer-looking, but security
  does not depend on instructions, and power users need full control.
- **Our own skill format:** no reuse of existing skills, and a translation
  layer for no benefit.
