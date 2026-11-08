# ADR-0081: Conversation settings and instructions

- **Status:** Accepted
- **Date:** 2026-11-08
- **Deciders:** @tapionx
- **Related:** ADR-0044, ADR-0052, ADR-0062, ADR-0069, ADR-0075, ADR-0076, ADR-0079, ADR-0080, CNV-013, CNV-014, MOD-012, MOD-014, AGT-002

## Context

Journey J13 asks to tailor the assistant: the model, how long it thinks,
which tools it may use, and its instructions, for every conversation or for
one. ADR-0044 decided the two layers of instructions. Today the model is the
only setting of a conversation, new conversations take the tenant's default
model (MOD-012), and the instructions are fixed in the worker; part of them
describes the workspace and the sandbox toolbox, which the assistant needs
to work at all (ADR-0076, ADR-0080).

Pydantic AI has one setting for reasoning across providers,
`ModelSettings.thinking`: off, the provider's default, or an effort level.
OpenRouter's catalog says which models take a reasoning parameter; a
household's own server does not say.

The household is a few people who each want their own assistant; an admin
choosing defaults for the others adds a screen nobody needs.

## Decision

1. **Settings of a conversation:** its model, its reasoning, one of `off`,
   `on` (the provider's default effort) and `deep` (high effort), and the
   tools it may use, each on its own: `web_search`, `read_page`, `shell`
   (running commands), `file_system` (reading and writing files) and
   `offer_download`. A conversation stores the tools that are off, so that a
   tool added later starts on. They apply from the next run.
2. **User defaults:** each user has one row of defaults, private to them:
   a model, a reasoning level, the tools that are off, base instructions and
   additional instructions, each optional. There are no admin defaults. A new
   conversation copies the model, reasoning and tools; with no default model,
   or one no longer offered, it takes the tenant's default model (MOD-012);
   without a default reasoning level, `on`; without tools set, all on.
   Forking copies the original conversation's settings and instructions.
3. **Instructions are live:** a conversation's base and additional
   instructions are each either its own text or, when null, the user's
   default as it is when a run starts; an empty text is a choice of nothing.
   Base instructions null at both levels are the built-in ones. Restoring the
   default sets the conversation's or the user's to null.
4. **What the model is told,** in this order: the base instructions; the
   working instructions, written by us, which describe the workspace, the
   toolbox, attachments and downloads, each part only when the tools it
   speaks of are on; then the additional instructions. Working instructions
   are not part of either layer, so no replacement removes them.
5. **Tools that are off are not given to the model**, through the same
   `prepare_tools` filter that withholds tools from models that cannot call
   them (MOD-014).
6. **Reasoning:** `connection_models` records whether a model can reason:
   for OpenRouter, `reasoning` in its supported parameters; null for another
   server. A model known not to reason runs without the setting, and clients
   show it disabled and say why; an unknown one is given it, and a server that refuses fails the
   run with its reason, as for tools (MOD-014). Reasoning parts are stored
   with the messages and reach clients as AG-UI reasoning events, shown
   folded above the answer.
7. **API:** `GET` and `PUT /me/settings` for the user defaults;
   `UpdateConversationRequest` takes `reasoning`, `disabled_tools`,
   `base_instructions` and `additional_instructions`; `ModelOption` says
   whether a model can reason. The user defaults come back with
   `built_in_base_instructions`, the text that applies when no one has
   replaced it, so clients can show it.
8. **Clients** call the base instructions the system prompt, the name model
   APIs give it, and the additional instructions the additional prompt. The
   additional prompt comes first; the system prompt comes last, in a danger
   zone, since replacing it changes who the assistant is. Each field starts
   with the text that applies: for the user defaults, theirs or the built-in
   one; for a conversation, its own or the user's default. A text saved
   unchanged from that is saved as null, so it keeps following the default.

## Consequences

- A user who changes nothing gets the assistant as it is today.
- Changing default instructions changes old conversations too; changing a
  default model or tool does not, which matches what each is for: who the
  assistant is, against what one conversation is doing.
- The working instructions now depend on the tools of the run, so tests of
  the instructions check each combination that changes them.
- AGT-002, when it comes, narrows the tools a user may switch on; until then
  every tool is permitted.
- Skills (AGT-017) will be switched on and off per conversation the same way.

## Alternatives considered

- **Defaults chosen by a tenant admin:** a screen for a few people who each
  choose for themselves; the tenant's default model stays, since a new user
  needs one that works.
- **Settings copied, instructions too:** editing one's instructions would not
  reach the conversations already open, which is what a user expects to
  change.
- **Settings live, like instructions:** changing a default would change the
  tools of a conversation in the middle of a task.
- **A free effort level or token budget:** providers disagree on what they
  take; three levels map onto all of them.
- **A list of enabled tools:** a tool added later would be off everywhere.
- **Hiding reasoning for a model that cannot reason:** the setting would
  vanish when the model changes, with nothing to say why.
- **An empty field for the default system prompt:** users would replace a
  text they cannot see.
- **Working instructions inside the base instructions:** a user replacing
  them would break the workspace and the toolbox without knowing why.
