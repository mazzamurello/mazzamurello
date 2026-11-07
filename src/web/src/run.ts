// A run as it streams: its text and tool calls, built from AG-UI events (ADR-0032).
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";

import { api } from "./api/client";
import { followRun, startRun, type RunEvent, type StartRun } from "./api/stream";
import { CONVERSATIONS } from "./conversations";
import type { Pose } from "./components/Sprite";

export type LivePart =
  | { kind: "text"; id: string; text: string }
  | { kind: "tool"; id: string; name: string; args: string; result?: string };

export interface LiveRun {
  runId: string;
  userText: string | null;
  attachments?: { path: string; size: number }[];
  parts: LivePart[];
  status: "running" | "finished" | "failed";
  errorCode?: string;
  // What the provider said, when it refused the request (MOD-014).
  reason?: string;
  // The context in use and the run's cost so far, after each model response (MOD-007).
  usage?: RunUsage;
}

export interface RunUsage {
  context_window: number;
  context_tokens: number;
  cost: { amount: string; currency: string } | null;
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
    case "CUSTOM":
      if (event.name === "mzm.usage" && typeof event.value === "object" && event.value !== null) {
        return { ...run, parts, usage: event.value as RunUsage };
      }
      break;
    case "RUN_FINISHED":
      return { ...run, parts, status: "finished" };
    case "RUN_ERROR": {
      const code = text("code") || "internal.error";
      const message = text("message");
      const reason = message.startsWith(`${code}: `) ? message.slice(code.length + 2) : undefined;
      return { ...run, parts, status: "failed", errorCode: code, ...(reason ? { reason } : {}) };
    }
  }
  return { ...run, parts };
}

/** Start or follow one run at a time, and stop it. */
export function useLiveRun(onEnd: () => Promise<void>) {
  const [live, setLive] = useState<LiveRun | null>(null);
  const runId = useRef<string | null>(null);
  const queries = useQueryClient();

  const consume = useCallback(
    async (initial: LiveRun, events: Promise<AsyncGenerator<RunEvent>>) => {
      runId.current = initial.runId;
      let current = initial;
      setLive(current);
      try {
        for await (const event of await events) {
          current = apply(current, event);
          setLive(current);
          // The conversation got its title while it is answered (CNV-006).
          if (event.type === "CUSTOM" && event.name === "mzm.title") {
            void queries.invalidateQueries({ queryKey: CONVERSATIONS });
            void queries.invalidateQueries({ queryKey: ["conversation"] });
          }
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
    [onEnd, queries],
  );

  const start = useCallback(
    (run: Omit<StartRun, "runId">) => {
      const id = crypto.randomUUID();
      void consume({ runId: id, userText: run.text, attachments: run.attachments ?? [], parts: [], status: "running" }, startRun({ ...run, runId: id }));
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

/** What a tool does, from its name: the sprite's pose and the words for it (UX-013, ADR-0070). */
export function toolActivity(name: string): Exclude<Pose, "greeting" | "answering" | "waiting" | "error"> {
  const lower = name.toLowerCase();
  if (/search_web|web_search|fetch|browse|url/.test(lower)) return "searching";
  if (/run|shell|command|exec|bash/.test(lower)) return "running";
  if (/write|edit|create|delete|move|patch/.test(lower)) return "writing";
  if (/read|list|find|grep|glob|search|view|open/.test(lower)) return "reading";
  return "thinking";
}

/** The sprite's pose for a run: what it does now, or waiting once it ended. */
export function poseOf(run: LiveRun | null): Pose {
  if (run === null || run.status === "finished") return "waiting";
  if (run.status === "failed") return run.errorCode === "run.cancelled" ? "waiting" : "error";
  const last = run.parts.at(-1);
  if (last === undefined) return "thinking";
  if (last.kind === "tool") return last.result === undefined ? toolActivity(last.name) : "thinking";
  return "answering";
}
