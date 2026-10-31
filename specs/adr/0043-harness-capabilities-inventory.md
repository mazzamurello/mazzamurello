# ADR-0043: Which Pydantic AI harness capabilities we use

- **Status:** Proposed
- **Date:** 2026-10-31
- **Deciders:** @tapionx
- **Related:** ADR-0030, ADR-0034, ADR-0035, ADR-0041, ADR-0042, ADR-0044, AGT-011, AGT-013, AGT-014, AGT-015, AGT-016, AGT-017, REPO-010

## Context

ADR-0030 asks us to use Pydantic AI's concepts and extension points before
building our own, and REPO-010 to follow its releases. Pydantic AI Harness
(0.63 as of this decision) is a library of capabilities on top of Pydantic AI.
We reviewed every capability it ships, and the core capabilities relevant to
the product, on 2026-10-31.

Several capabilities have a local mode that runs on the machine of the agent
process: local web search and page fetching, browsers, code interpreters,
local sandboxes and workspaces. In Mazzamurello that machine is the control
plane, which can reach the household's network.

## Decision

1. **Nothing runs on the host on behalf of users** (AGT-013): when a
   capability would execute code, fetch URLs or start processes in the
   control plane, we use the provider's own implementation (for example a
   provider's native web search) or run it in the user's sandbox; otherwise we
   do not use it.
2. **We adopt** these capabilities, each pinned to an exact version:

   | Capability | For | Phase |
   |---|---|---|
   | `Shell`, `FileSystem` on our workspace backend; `Coder` | AGT-011 (ADR-0035) | 0, 1 |
   | `ToolOutputLimits`, `RepairToolArguments`, `ClampOversizedMessages` | AGT-014; robustness with local models | 0 |
   | Compaction strategies and `ReportContextUsage` | AGT-016, MOD-007 (ADR-0041) | 1 |
   | `SpendLimits` with genai-prices | MOD-004, MOD-006 (ADR-0042) | 1 |
   | Core `caching`, `Thinking`, `SelectModel` | cost, CNV-013 | 1 |
   | Core `FileUnderstanding`, `citations` | CNV-012, web answers with sources | 1 |
   | `Memory`, with a store under row-level security | MEM | 1 |
   | `AskUser`, through interrupts | AGT-015 | 1 |
   | `Skills` | AGT-017 (ADR-0044) | 1 |
   | `DetectLoops`, `SystemReminders`, `Planning` | long tasks, UX-009 | 1 |

3. **Later candidates**, to be decided by their own ADRs: `Researcher` and
   `SubAgents` for multi-step research, browser automation (`Playwright`,
   `BrowserUse`) with the browser in the sandbox, `BackgroundTools`, core MCP
   with `ToolSearch` for connectors, core `ImageGeneration`, `Guardrails` and
   `PromptInjectionDefender` judged by evals, `ConversationSearch` adapted to
   our storage, and hosted connectors as optional connectors (ADR-0020).
4. **We do not use**:
   - second-model judges of actions (`ApprovalReviewer`, `ToolCallJudge`,
     `TrajectoryJudge`, `Advisor`): a model approving actions can be
     manipulated by the content it judges, which weakens fail-closed
     approvals;
   - code execution in the control plane (`CodeMode`, `IPythonCodeMode`,
     `CapabilityCreation`);
   - `StepPersistence` and `Media`: it records checkpoints but does not
     execute runs, and creates its own tables without row-level security; DBOS
     (ADR-0034) and our tree of runs (ADR-0037) cover its uses;
   - other sandboxes, workspaces and durable execution engines (ADR-0023,
     ADR-0034);
   - developer and vendor tooling unrelated to the product, including
     configuration managed by an external observability service (OBS-001).
5. Each framework upgrade reviews this list (REPO-010): new capabilities are
   classified, and changes to adopted ones are checked against the
   requirements they serve.

## Consequences

- Most agent behavior comes from maintained capabilities; our code is the
  security boundary, storage and product glue around them.
- Harness 0.x may change between minor releases; exact pins and the upgrade
  review contain that.

## Alternatives considered

- **Deciding capability by capability when needed:** less work now, but the
  boundary rule of point 1 would be rediscovered each time.
