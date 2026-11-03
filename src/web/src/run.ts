// A run as it streams: its text and tool calls, built from AG-UI events (ADR-0032).
import { useCallback, useRef, useState } from "react";

import { api } from "./api/client";
import { followRun, startRun, type RunEvent, type StartRun } from "./api/stream";

export type LivePart =
  | { kind: "text"; id: string; text: string }
  | { kind: "tool"; id: string; name: string; args: string; result?: string };

export interface LiveRun {
  runId: string;
  userText: string | null;
  parts: LivePart[];
  status: "running" | "finished" | "failed";
  errorCode?: string;
}

/** Fold one event into the run's parts. */
export function apply(run: LiveRun, event: RunEvent): LiveRun {
  const parts = [...run.parts];
  const text = (key: string) => String(event[key] ?? "");
  switch (event.type) {
    case "TEXT_MESSAGE_START":
      parts.push({ kind: "text", id: text("messageId"), text: "" });
      break;
    case "TEXT_MESSAGE_CONTENT": {
      const index = parts.findIndex((part) => part.kind === "text" && part.id === text("messageId"));
      const part = parts[index];
      if (part?.kind === "text") parts[index] = { ...part, text: part.text + text("delta") };
      else parts.push({ kind: "text", id: text("messageId"), text: text("delta") });
      break;
    }
    case "TOOL_CALL_START":
      parts.push({ kind: "tool", id: text("toolCallId"), name: text("toolCallName"), args: "" });
      break;
    case "TOOL_CALL_ARGS":
    case "TOOL_CALL_RESULT": {
      const index = parts.findIndex((part) => part.kind === "tool" && part.id === text("toolCallId"));
      const part = parts[index];
      if (part?.kind === "tool") {
        parts[index] =
          event.type === "TOOL_CALL_ARGS" ? { ...part, args: part.args + text("delta") } : { ...part, result: text("content") };
      }
      break;
    }
    case "RUN_FINISHED":
      return { ...run, parts, status: "finished" };
    case "RUN_ERROR":
      return { ...run, parts, status: "failed", errorCode: text("code") || "internal.error" };
  }
  return { ...run, parts };
}

/** Start or follow one run at a time, and stop it. */
export function useLiveRun(onEnd: () => Promise<void>) {
  const [live, setLive] = useState<LiveRun | null>(null);
  const runId = useRef<string | null>(null);

  const consume = useCallback(
    async (initial: LiveRun, events: Promise<AsyncGenerator<RunEvent>>) => {
      runId.current = initial.runId;
      let current = initial;
      setLive(current);
      try {
        for await (const event of await events) {
          current = apply(current, event);
          setLive(current);
        }
      } catch (error) {
        const code = error instanceof Error && "code" in error ? String(error.code) : "internal.error";
        current = { ...current, status: "failed", errorCode: code };
        setLive(current);
      }
      runId.current = null;
      await onEnd();
      // A failed run stays visible until the next one; a finished one is in the history now.
      setLive(current.status === "failed" ? current : null);
    },
    [onEnd],
  );

  const start = useCallback(
    (run: Omit<StartRun, "runId">) => {
      const id = crypto.randomUUID();
      void consume({ runId: id, userText: run.text, parts: [], status: "running" }, startRun({ ...run, runId: id }));
    },
    [consume],
  );

  const follow = useCallback(
    (id: string) => {
      if (runId.current === id) return;
      void consume({ runId: id, userText: null, parts: [], status: "running" }, followRun(id));
    },
    [consume],
  );

  const stop = useCallback(async () => {
    if (runId.current !== null) {
      await api.POST("/runs/{run_id}/cancel", { params: { path: { run_id: runId.current } } });
    }
  }, []);

  return { live, start, follow, stop, running: live?.status === "running" };
}
