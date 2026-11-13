# ADR-0090: Tool permissions and approvals, with few prompts

- **Status:** Accepted
- **Date:** 2026-11-13
- **Deciders:** @tapionx
- **Related:** ADR-0012, ADR-0033, ADR-0034, ADR-0063, ADR-0064, ADR-0078, ADR-0083, ADR-0087, AGT-002, AGT-003, AGT-004, AGT-005, AGT-006, AGT-007, AGT-008, AGT-012, AGT-018, CNV-013, SBX-018, UX-022, UX-023

## Context

ADR-0012 breaks the lethal trifecta within each run: once untrusted content
is part of a run, tools that communicate externally need the user's
approval, and they need it by default anyway. ADR-0033 implements approvals
as interrupts. Neither decided which of today's tools fall in which class,
nor what an approval covers, and applied literally to the tools Sibillo has
now they would ask for approval almost all the time:

- The sandbox reaches the internet (SBX-004), so a command can send
  workspace files anywhere: `run_command` and `start_command` communicate
  externally. So do `read_page`, whose address can carry data, and
  `web_search`, whose query can.
- Sandbox output, web pages and search results are untrusted (AGT-003), so
  nearly every run has untrusted content after its first tool call.
- A conversation's history goes into every later run, so the untrusted
  content of one turn is part of every turn after it.
- "Approval by default" for external communication would ask before every
  search and every command, untrusted content or not.

A prompt on every step would train users to approve without reading, which
the threat model names as a residual risk. The assistant must stay safe and
mostly quiet.

## Decision

1. **Every tool declares its classes and its approval default.** A tool
   declares its capability classes, possibly none, and whether it is
   `allowed` or `asked` by default; a declaration is never left out (AGT-005).
   Tools that communicate externally are asked by default unless their
   declaration says why not. Tools in the `irreversible` or `physical`
   classes are always asked, for every call. Today's tools:

   | Tools | Classes | Default |
   |---|---|---|
   | `web_search`, `read_page` | `ingests_untrusted`, `external_communication` | allowed |
   | `run_command`, `start_command` | `reads_private_data`, `ingests_untrusted`, `external_communication` | allowed |
   | `check_command`, `read_file`, `list_directory`, `find_files`, `search_files`, `file_info` | `reads_private_data`, `ingests_untrusted` | allowed |
   | `stop_command`, `write_file`, `edit_file`, `create_directory`, `offer_download` | `reads_private_data` | allowed |
   | `ask_user_question`, the planning tools | none | allowed |
   | `read_tool_result`, which reads back a large result set aside (AGT-014) | `reads_private_data`, `ingests_untrusted` | allowed |

   `read_tool_result` belongs to the output limits, not to a tool group: the
   user has no switch for it (ADR-0087), and tool permissions reach it
   through its classes only.

   Web and command tools are allowed by default because the trifecta rule
   (point 3) already guards them where it matters. Nothing today is
   `irreversible` or `physical`: changes to the workspace are the
   assistant's ordinary work and the workspace is backed up (OPS-006). Those
   classes wait for tools such as sending mail or switching a light. Tools
   of connected devices and remote MCP servers are always asked, for every
   call (AGT-018).

2. **Provenance follows the conversation.** Untrusted content is the result
   of any call to a tool in the `ingests_untrusted` class, and every
   attachment or file of the file library given to a run (external files).
   The user's messages, their answers to questions (ADR-0083), and the
   instructions are trusted. A run **has untrusted content** when the
   conversation's active path, up to and including that run, holds any:
   untrusted content stays in the history that later runs read, so it
   counts in every later turn, also after compaction, and in a fork. Only a
   rewind to before it takes it away (ADR-0068).

3. **The trifecta rule.** In a run with untrusted content, every call to a
   tool in the `external_communication` class needs approval, unless an
   allowance covers it (point 4). For the four web and command tools,
   `web_search`, `read_page`, `run_command` and `start_command`, one
   approval covers all four, so a run asks at most once.

4. **What an approval covers.** The user answers an approval request with
   one of:

   - **Deny**: the call does not run; the model is told the user denied it,
     and the run goes on.
   - **Allow once**: this call only.
   - **Allow for this turn**: offered for the web and command tools under
     the trifecta rule; they are allowed until the turn ends. A turn is a
     user message and the runs that answer it: the run the message starts,
     and the resume runs that continue it.
   - **Allow in this conversation**: offered for the web and command tools
     under the trifecta rule, and for tools asked by default or by a tool
     permission (point 5); the tool, or all four web and command tools, are
     allowed in this conversation from now on.

   Tools in the `irreversible` or `physical` classes, and tools of devices
   and MCP servers, offer only Deny and Allow once. Allowances in a
   conversation are listed with it and its user can withdraw them; they
   are created only by answering a stored approval request (AGT-012), never
   by a settings change, and a fork does not copy them. There is no
   standing allowance beyond one conversation.

5. **Tool permissions.** A tenant admin sets, for each user, each tool or
   each capability class to `allow`, `ask` or `deny` (AGT-002); without a
   setting a tool follows its default. A setting for a tool wins over its
   classes; among a tool's classes the strictest wins (`deny`, then `ask`,
   then `allow`). `deny` takes the tool away: it is never offered to the
   model, a call to it is refused, and the user's tool switches show it off
   and locked, saying their household's admin turned it off. `ask` makes
   every call of the tool need approval. `allow` lifts the tool's default
   approval, but never the trifecta rule, the approval of every call to an
   `irreversible` or `physical` tool, or that of devices and MCP servers.
   The user's own switches only narrow what the permissions leave
   (CNV-013).

6. **Approval requests.** A run whose calls need approval ends with an
   interrupt, as in ADR-0033: the worker stores the deferred calls, and each
   call needing approval becomes an interrupt with the ID `apr-` followed by
   the tool call's ID and `reason` `approval`. It carries, built by the
   server from the stored call: the tool and its full arguments; what the
   call does; the data it sends and where it goes (for `read_page` the
   address, for `web_search` the query to the search service, for a
   command the command, which reaches the internet from the sandbox); why it
   needs approval (`untrusted_content`, `tool_default`, `permission`,
   `consequential` or `device`); and the answers offered. Questions and
   approvals of one run are pending together and answered together.

7. **Expiry.** An approval request is pending for **24 hours**. When it
   expires, a sweep of the worker resumes the conversation, answering its pending
   approvals as denied and its pending questions as declined (AGT-007).
   Questions alone still never expire (ADR-0083). A request that cannot be
   stored is denied.

8. **The sandbox waits for the answer.** A run that ends asking the user,
   for an approval or an answer to a question, leaves its sandbox running,
   so that the run that continues it finds its scratch folder and its
   background commands as they were. The driver's idle limit stops it when
   the answer is slow (SBX-018, ADR-0078); the answer is part of the same
   turn, so nothing outlives the answer that planted it (T-33).

9. **Audit events.** Every tool call, run or not, produces an audit event
   with the tool, the time, the run, the conversation, its approval outcome
   (`not_needed`, `allowed`, `approved`, `denied`, `expired` or `refused`)
   and the scope of the approval (AGT-008). Audit events are content-free:
   no arguments and no results, which stay in the conversation. They are
   kept after their conversation is deleted, naming it only by its ID, and
   deleted with their user. For tools that communicate externally or are
   irreversible or physical, the worker records the attempt, with the run
   and tool call IDs as the idempotency key, before the call runs. Tool
   calls are not durable steps: a run replayed after a crash calls its tools
   again, and records the attempt again. A call recorded twice may have run
   twice (ADR-0034), and its audit event says so. The user sees audit events on an
   Activity page of their settings, and the approval outcome of each call
   on the call itself in the conversation (UX-023).

## Consequences

- A conversation asks at most once for the web and commands, after which
  the user may allow them for the turn or the whole conversation. Future
  tools that send mail, delete things or act in the house ask as their
  classes demand.
- A user who allows the web and commands in a conversation accepts, for that
  conversation, that injected instructions could send its workspace out. The
  prompt says so; evals measure whether the model follows injected
  instructions (EVL-003).
- AGT-006 no longer asks for approval by default for every tool that
  communicates externally; the default is per tool, and its exceptions are
  written in this ADR's table.
- The interrupts of ADR-0033 and ADR-0083 carry approvals too; their
  expiry needs a scheduled job.
- Audit events add one row per tool call; Activity pages them.

## Alternatives considered

- **Ask before every command and search after untrusted content:** the
  strict reading of ADR-0012, rejected as approval fatigue.
- **Cut the sandbox's network once a run has untrusted content:** no
  prompts, but commands that need the network fail mid-task, and it needs
  per-sandbox egress changes during a run.
- **Untrusted content only of the current run:** fewer prompts, but
  injected text from an earlier turn could act before any prompt.
- **Standing allowances across conversations ("always allow"):** a
  setting that removes the prompt everywhere also removes the trifecta
  mitigation everywhere.
- **Content in audit events:** more useful at a glance, but a second copy of
  the user's data that outlives its deletion.
