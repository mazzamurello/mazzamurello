// The web client's handling of a run's events (ADR-0032, ADR-0067).
import { describe, expect, it } from "vitest";

import { parseBlock } from "../../../src/web/src/api/stream";
import { apply, type LiveRun } from "../../../src/web/src/run";

const start: LiveRun = { runId: "r", userText: "hi", parts: [], status: "running" };

describe("parseBlock", () => {
  it("reads the sequence number and the event", () => {
    expect(parseBlock('id: 3\nevent: RUN_STARTED\ndata: {"type":"RUN_STARTED"}')).toEqual({ type: "RUN_STARTED", seq: 3 });
  });

  it("ignores comments and messages without data", () => {
    expect(parseBlock(": keep-alive")).toBeUndefined();
  });
});

describe("apply", () => {
  it("builds text from its deltas", () => {
    let run = apply(start, { type: "TEXT_MESSAGE_START", messageId: "m", seq: 1 });
    run = apply(run, { type: "TEXT_MESSAGE_CONTENT", messageId: "m", delta: "Hel", seq: 2 });
    run = apply(run, { type: "TEXT_MESSAGE_CONTENT", messageId: "m", delta: "lo", seq: 3 });
    expect(run.parts).toEqual([{ kind: "text", id: "m", text: "Hello" }]);
  });

  it("builds a tool call with its arguments and result", () => {
    let run = apply(start, { type: "TOOL_CALL_START", toolCallId: "t", toolCallName: "run_command", seq: 1 });
    run = apply(run, { type: "TOOL_CALL_ARGS", toolCallId: "t", delta: '{"command":', seq: 2 });
    run = apply(run, { type: "TOOL_CALL_ARGS", toolCallId: "t", delta: '"ls"}', seq: 3 });
    run = apply(run, { type: "TOOL_CALL_RESULT", toolCallId: "t", content: "a.txt", seq: 4 });
    expect(run.parts).toEqual([{ kind: "tool", id: "t", name: "run_command", args: '{"command":"ls"}', result: "a.txt" }]);
  });

  it("ends with the run's outcome", () => {
    expect(apply(start, { type: "RUN_FINISHED", seq: 9 }).status).toBe("finished");
    const failed = apply(start, { type: "RUN_ERROR", code: "run.cancelled", seq: 9 });
    expect(failed.status).toBe("failed");
    expect(failed.errorCode).toBe("run.cancelled");
  });
});
