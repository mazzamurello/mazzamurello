# ADR-0087: A switch for every tool

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** @tapionx
- **Related:** ADR-0081, ADR-0083, CNV-013, CNV-014, AGT-015, UX-009

## Context

ADR-0081 gave the user five switches: `web_search`, `read_page`, `shell`,
`file_system` and `offer_download`. Two of them stand for several tools each:
`shell` for the four command tools, `file_system` for the eight file tools.
The tools of questions to the user and of the task list (ADR-0083) came later
and have no switch at all. The settings name what a switch does, never the
tools behind it, so a user cannot tell which tools the model is given, nor
match a tool call they see in an answer to the switch that stops it.

## Decision

1. **One switch per tool:** the tools a user can switch off are every tool
   the assistant has, each by the name the model knows it by: `web_search`
   and `read_page`; `run_command`, `start_command`, `check_command` and
   `stop_command`; `read_file`, `write_file`, `edit_file`,
   `create_directory`, `list_directory`, `find_files`, `search_files` and
   `file_info`; `offer_download`; `ask_user_question`; and `write_plan`,
   `read_plan`, `add_task`, `update_task_status`, `update_task_statuses` and
   `remove_task`. A conversation and the user's defaults still store the
   tools that are off, so a tool added later starts on.
2. **Tool groups:** clients list the tools in groups, Web, Commands, Files,
   Showing files, Questions and Task list, each tool with its label and its
   name. Each group has a switch of its own, on when every tool of the group
   is on, which switches all of them on, or off when they all are. Groups
   exist in clients only; the API knows tools.
3. **Working instructions follow the tools:** the workspace instructions are
   given while any command or file tool is on, the toolbox while
   `run_command` or `start_command` is, the instructions for showing files
   while `offer_download` is, and the instructions of questions and of the
   task list only while every tool of their group is on, since they speak of
   several of them (CNV-014).
4. **Stored settings move over:** `shell` and `file_system` in stored
   settings are replaced with the tools they stood for.
5. **No tool is left out:** a test compares the switches a client lists with
   the tools the model is offered when every switch is on, so a tool added
   to the agent without a switch fails the build.

## Consequences

- The settings show 22 switches instead of 5. The group switches keep the
  common change, a whole kind of work, one click away.
- Switching off one tool of a group, such as `write_file` alone, gives the
  model the rest; a partly switched group may confuse a model, which is the
  user's choice to make.
- The contract's `ToolName` changes its values. Clients built for the old
  names stop matching; the web client is the only one.

## Alternatives considered

- **Keep the five switches and only show the names behind them:** a user
  could see the tools but not choose among them, and questions and the task
  list would still have no switch.
- **Groups in the API:** the API would carry a structure only the settings
  need, and a client would have to ask for it before showing them.
