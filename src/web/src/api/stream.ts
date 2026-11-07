// Runs and their AG-UI events, as Server-Sent Events (ADR-0032).
import { ApiError, API_BASE, REQUEST_HEADER, type Schemas } from "./client";

export type RunEvent = Schemas["AgUiEvent"] & { seq: number };

/** The events of an SSE body, as they arrive. */
export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<RunEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    let end: number;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const event = parseBlock(block);
      if (event !== undefined) yield event;
    }
  }
}

/** One SSE message: its `id` is the sequence number and its `data` the AG-UI event. */
export function parseBlock(block: string): RunEvent | undefined {
  let id = 0;
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
    if (field === "id") id = Number(value);
    else if (field === "data") data += data ? `\n${value}` : value;
  }
  if (!data) return undefined;
  return { ...(JSON.parse(data) as Schemas["AgUiEvent"]), seq: id };
}

async function eventsOf(response: Response): Promise<AsyncGenerator<RunEvent>> {
  if (!response.ok || response.body === null) {
    let code = "internal.error";
    try {
      code = ((await response.json()) as { code?: string }).code ?? code;
    } catch {
      // Not a problem document.
    }
    throw new ApiError(response.status, code);
  }
  return readEvents(response.body);
}

export interface StartRun {
  conversationId: string;
  runId: string;
  text: string;
  // Files already uploaded to the workspace's `uploads/` (CNV-017).
  attachments?: { path: string; size: number }[];
  parentRunId?: string;
  signal?: AbortSignal;
}

/** Start a run with one user message, and read its events. */
export async function startRun(start: StartRun): Promise<AsyncGenerator<RunEvent>> {
  const input: Record<string, unknown> = {
    threadId: start.conversationId,
    runId: start.runId,
    messages: [{ id: crypto.randomUUID(), role: "user", content: start.text }],
  };
  if (start.parentRunId !== undefined) input.parentRunId = start.parentRunId;
  if (start.attachments !== undefined && start.attachments.length > 0) input.attachments = start.attachments.map((file) => file.path);
  const init: RequestInit = {
    method: "POST",
    credentials: "same-origin",
    headers: { ...REQUEST_HEADER, "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(input),
  };
  if (start.signal !== undefined) init.signal = start.signal;
  return eventsOf(await fetch(`${API_BASE}/conversations/${start.conversationId}/runs`, init));
}

/** Follow a run's events from the beginning, as a second device does (API-004). */
export async function followRun(runId: string, signal?: AbortSignal): Promise<AsyncGenerator<RunEvent>> {
  const init: RequestInit = { credentials: "same-origin", headers: { Accept: "text/event-stream" } };
  if (signal !== undefined) init.signal = signal;
  return eventsOf(await fetch(`${API_BASE}/runs/${runId}/events`, init));
}
