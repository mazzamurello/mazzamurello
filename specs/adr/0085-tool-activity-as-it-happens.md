# ADR-0085: Tool activity as it happens

- **Status:** Accepted
- **Date:** 2026-11-08
- **Deciders:** @tapionx
- **Related:** ADR-0032, ADR-0035, ADR-0043, ADR-0070, UX-003, UX-009

## Context

A run's AG-UI events come in the order the model produced them: text, then a
tool call, then more text. The web client grouped every tool call above all
of the answer's text, so a streaming answer showed its tools first and its
words after, out of order. A call showed no sign of whether it was still
running, and a command showed only itself, which says little to anyone who
does not read shell: "Ran a command", then `python3 - <<'EOF' …`.

The harness's command tools, `run_command` and `start_command`, take the
command and nothing about why; Pydantic AI refuses arguments a tool does not
declare. A capability can change the tool definitions the model sees
(`prepare_tools`) and the raw arguments before they are validated
(`before_tool_validate`).

## Decision

1. **In order:** clients show an answer's parts in the order of its events,
   text, reasoning and tool calls interleaved; consecutive calls form one
   group, and each piece of reasoning is folded on its own, where it
   happened (CNV-013). Offered downloads stay at the end. Reasoning was
   first kept in one block above the answer, which put what the model
   thought about a tool's result before the call that gave it.
2. **Running or done:** a call without a result in a run that goes on is
   running, and shows a spinner; with a result it is done, and shows a check.
   Each says so to screen readers.
3. **Commands say what they are for:** a capability, `CommandPurposes`, adds
   a required `description` to the definitions of `run_command` and
   `start_command`: "what the command is for, in a few words the user reads".
   Before validation it removes `description` from the arguments, so the
   harness's tools are unchanged; the stored call keeps it, so the history
   shows it too. A call without one still runs.
4. **Shown as a sandbox command:** clients label these calls "Sandbox
   command" followed by the description, with the command's first line below,
   in monospace; the whole command and its output stay one click away.

## Consequences

- A long answer reads as it was produced: what the assistant said, then what
  it did, then what it found.
- The model spends a few tokens per command on its description, which the
  user reads instead of the command.
- The design test of the agent's capabilities lists `CommandPurposes`.

## Alternatives considered

- **Our own command tools:** would duplicate the harness's, its limits and
  its background commands, to add one argument.
- **Describing commands from the command text:** guesses, in a language the
  user may not read.
- **A description in a separate message before each call:** models do not
  reliably write one, and it would not be tied to its call.
