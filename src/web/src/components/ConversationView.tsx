import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams } from "react-router";

import { ApiError, api, unwrap, type MessagePage, type PathRun } from "../api/client";
import { updateConversation, useRefreshConversations } from "../conversations";
import { type LivePart, useLiveRun } from "../run";
import { Composer } from "./Composer";
import { Markdown } from "./Markdown";

type AgUiMessage = MessagePage["items"][number] & {
  content?: unknown;
  toolCalls?: { id: string; function: { name: string; arguments: string } }[];
  toolCallId?: string;
};

interface Turn {
  run: PathRun;
  userText: string | null;
  parts: LivePart[];
}

/** The runs of the active path, each with its user message and what answered it. */
function turnsOf(page: MessagePage): Turn[] {
  const byId = new Map(page.items.map((message) => [message.id, message as AgUiMessage]));
  return page.runs.map((run) => {
    const messages = run.message_ids.flatMap((id) => byId.get(id) ?? []);
    const results = new Map(messages.filter((m) => m.role === "tool").map((m) => [m.toolCallId, textOf(m.content)]));
    let userText: string | null = null;
    const parts: LivePart[] = [];
    for (const message of messages) {
      if (message.role === "user" && userText === null) userText = textOf(message.content);
      else if (message.role === "assistant") {
        const text = textOf(message.content);
        if (text) parts.push({ kind: "text", id: message.id, text });
        for (const call of message.toolCalls ?? []) {
          const result = results.get(call.id);
          parts.push({ kind: "tool", id: call.id, name: call.function.name, args: call.function.arguments, ...(result === undefined ? {} : { result }) });
        }
      }
    }
    return { run, userText, parts };
  });
}

function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content.map((part) => (typeof part === "object" && part !== null && "text" in part ? String(part.text) : "")).join("");
  }
  return "";
}

async function allMessages(conversationId: string): Promise<MessagePage> {
  const items: MessagePage["items"] = [];
  const runs: PathRun[] = [];
  let cursor: string | undefined;
  do {
    const query = cursor === undefined ? { limit: 100 } : { limit: 100, cursor };
    const page = unwrap(
      await api.GET("/conversations/{conversation_id}/messages", { params: { path: { conversation_id: conversationId }, query } }),
    );
    items.push(...page.items);
    for (const run of page.runs) if (runs.at(-1)?.run_id !== run.run_id) runs.push(run);
    else runs[runs.length - 1] = { ...run, message_ids: [...(runs.at(-1)?.message_ids ?? []), ...run.message_ids] };
    cursor = page.next_cursor ?? undefined;
  } while (cursor !== undefined);
  return { items, runs, next_cursor: null };
}

export function ConversationView() {
  const { t } = useTranslation();
  const { conversationId = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queries = useQueryClient();
  const refreshList = useRefreshConversations();
  const conversation = useQuery({
    queryKey: ["conversation", conversationId, "details"],
    queryFn: async () => unwrap(await api.GET("/conversations/{conversation_id}", { params: { path: { conversation_id: conversationId } } })),
  });
  const history = useQuery({ queryKey: ["conversation", conversationId, "messages"], queryFn: () => allMessages(conversationId) });

  // While a new version of an earlier turn streams, that turn and the ones after it are hidden.
  const [hideFrom, setHideFrom] = useState<number | null>(null);
  const refresh = useCallback(async () => {
    await queries.invalidateQueries({ queryKey: ["conversation", conversationId] });
    await refreshList();
  }, [queries, refreshList, conversationId]);
  const runEnded = useCallback(async () => {
    await refresh();
    setHideFrom(null);
  }, [refresh]);

  const { live, start, follow, stop, running } = useLiveRun(runEnded);
  const [rewindTo, setRewindTo] = useState<PathRun | null>(null);

  // The first message of a new chat, handed over by the new-chat screen.
  const firstMessage = (location.state as { firstMessage?: string } | null)?.firstMessage;
  const started = useRef(false);
  useEffect(() => {
    if (firstMessage && !started.current) {
      started.current = true;
      start({ conversationId, text: firstMessage });
      void navigate(location.pathname, { replace: true, state: null });
    }
  }, [firstMessage, conversationId, start, navigate, location.pathname]);

  // A run in progress, started on another device or before a reload: follow it (CNV-015).
  const activeRunId = conversation.data?.active_run_id;
  useEffect(() => {
    if (!activeRunId || running || started.current) return;
    void api.GET("/runs/{run_id}", { params: { path: { run_id: activeRunId } } }).then((result) => {
      if (result.data?.status === "queued" || result.data?.status === "running") follow(activeRunId);
    });
  }, [activeRunId, running, follow]);

  /** A new version of `run`'s turn: editing its message or asking for a new answer (CNV-001). */
  async function newVersion(index: number, run: PathRun, text: string) {
    setHideFrom(index);
    if (run.parent_run_id === null) {
      // The first turn has no parent: rewind to before it, then start again.
      await updateConversation(conversationId, { active_run_id: null });
      start({ conversationId, text });
    } else {
      start({ conversationId, text, parentRunId: run.parent_run_id });
    }
  }

  async function switchTo(runId: string) {
    await updateConversation(conversationId, { active_run_id: runId });
    await refresh();
  }

  if (conversation.error instanceof ApiError && conversation.error.status === 404) {
    return <p className="p-6">{t("errors.notFound")}</p>;
  }

  const turns = history.data ? turnsOf(history.data) : [];
  const shown = live !== null && hideFrom !== null ? turns.slice(0, hideFrom) : turns;

  return (
    <>
      <div className="flex-1 overflow-y-auto" aria-live="polite" aria-busy={running}>
        <ol className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6">
          {shown.map((turn, index) => (
            <TurnView
              key={turn.run.run_id}
              turn={turn}
              busy={running}
              last={index === shown.length - 1}
              onEdit={(text) => void newVersion(index, turn.run, text)}
              onRegenerate={() => turn.userText && void newVersion(index, turn.run, turn.userText)}
              onSwitch={(runId) => void switchTo(runId)}
              onRewind={() => setRewindTo(turn.run)}
            />
          ))}
          {live && (
            <li className="space-y-3">
              {live.userText !== null && <UserBubble text={live.userText} />}
              <Answer parts={live.parts} />
              {live.status === "running" && live.parts.length === 0 && <p className="text-stone-600 dark:text-stone-300">{t("message.thinking")}</p>}
              {live.status === "failed" && (
                <p role="status" className="text-sm text-red-800 dark:text-red-300">
                  {live.errorCode === "run.cancelled" ? t("message.stopped") : t("message.failed", { code: live.errorCode })}
                </p>
              )}
            </li>
          )}
        </ol>
      </div>
      <Composer onSend={(text) => start({ conversationId, text })} onStop={() => void stop()} running={running} />
      <Dialog.Root open={rewindTo !== null} onOpenChange={(open) => !open && setRewindTo(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
          <Dialog.Content className="fixed top-1/2 left-1/2 z-50 w-[min(92vw,28rem)] -translate-x-1/2 -translate-y-1/2 space-y-3 rounded-xl bg-white p-5 shadow-xl dark:bg-stone-800">
            <Dialog.Title className="text-lg font-semibold">{t("rewind.title")}</Dialog.Title>
            <Dialog.Description>{t("rewind.body")}</Dialog.Description>
            {/* Going back never changes the workspace, and the user is told so (UX-010). */}
            <p className="rounded-lg bg-amber-100 p-3 text-sm text-amber-950">{t("rewind.files")}</p>
            <div className="flex justify-end gap-2">
              <Dialog.Close className="rounded-lg px-3 py-2">{t("rewind.cancel")}</Dialog.Close>
              <button
                type="button"
                className="rounded-lg bg-stone-800 px-3 py-2 text-white"
                onClick={() => {
                  if (rewindTo) void switchTo(rewindTo.run_id);
                  setRewindTo(null);
                }}
              >
                {t("rewind.confirm")}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}

function TurnView(props: {
  turn: Turn;
  busy: boolean;
  last: boolean;
  onEdit: (text: string) => void;
  onRegenerate: () => void;
  onSwitch: (runId: string) => void;
  onRewind: () => void;
}) {
  const { t } = useTranslation();
  const { turn, busy } = props;
  const [editing, setEditing] = useState(false);
  const versions = turn.run.versions;
  const current = versions.indexOf(turn.run.run_id);
  const action = "rounded px-2 py-1 text-sm text-stone-700 hover:bg-stone-200 disabled:opacity-50 dark:text-stone-200 dark:hover:bg-stone-700";

  return (
    <li className="space-y-3">
      {turn.userText !== null &&
        (editing ? (
          <form
            className="space-y-2"
            onSubmit={(event) => {
              event.preventDefault();
              const text = String(new FormData(event.currentTarget).get("text") ?? "").trim();
              if (text) props.onEdit(text);
              setEditing(false);
            }}
          >
            <label className="sr-only" htmlFor={`edit-${turn.run.run_id}`}>
              {t("message.editLabel")}
            </label>
            <textarea id={`edit-${turn.run.run_id}`} name="text" defaultValue={turn.userText} rows={3} autoFocus className="w-full rounded-xl border border-stone-400 bg-white p-3 text-stone-900" />
            <div className="flex justify-end gap-2">
              <button type="button" className={action} onClick={() => setEditing(false)}>
                {t("message.cancelEdit")}
              </button>
              <button type="submit" className="rounded-lg bg-stone-800 px-3 py-1 text-white">
                {t("message.saveEdit")}
              </button>
            </div>
          </form>
        ) : (
          <div className="space-y-1">
            <UserBubble text={turn.userText} />
            <div className="flex items-center justify-end gap-1">
              {versions.length > 1 && (
                <span className="flex items-center gap-1 text-sm" aria-label={t("message.version", { current: current + 1, total: versions.length })}>
                  <button type="button" className={action} disabled={busy || current <= 0} aria-label={t("message.previousVersion")} onClick={() => props.onSwitch(turn.run.version_tips[current - 1] ?? "")}>
                    ‹
                  </button>
                  <span aria-hidden="true">
                    {current + 1} / {versions.length}
                  </span>
                  <button type="button" className={action} disabled={busy || current >= versions.length - 1} aria-label={t("message.nextVersion")} onClick={() => props.onSwitch(turn.run.version_tips[current + 1] ?? "")}>
                    ›
                  </button>
                </span>
              )}
              <button type="button" className={action} disabled={busy} onClick={() => setEditing(true)}>
                {t("message.edit")}
              </button>
            </div>
          </div>
        ))}
      <Answer parts={turn.parts} />
      <div className="flex gap-1">
        <button type="button" className={action} disabled={busy} onClick={props.onRegenerate}>
          {t("message.regenerate")}
        </button>
        {!props.last && (
          <button type="button" className={action} disabled={busy} onClick={props.onRewind}>
            {t("message.rewind")}
          </button>
        )}
      </div>
    </li>
  );
}

function UserBubble({ text }: { text: string }) {
  const { t } = useTranslation();
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-2xl bg-stone-200 px-4 py-2 whitespace-pre-wrap dark:bg-stone-700">
        <span className="sr-only">{t("message.you")}: </span>
        {text}
      </div>
    </div>
  );
}

function Answer({ parts }: { parts: LivePart[] }) {
  return (
    <div className="space-y-3">
      {parts.map((part) => (part.kind === "text" ? <Markdown key={part.id} text={part.text} /> : <ToolCall key={part.id} part={part} />))}
    </div>
  );
}

/** Tool activity as a compact summary that expands to its full details (UX-003). */
function ToolCall({ part }: { part: Extract<LivePart, { kind: "tool" }> }) {
  const { t } = useTranslation();
  return (
    <details className="rounded-lg border border-stone-300 text-sm dark:border-stone-600">
      <summary className="cursor-pointer px-3 py-2">{part.result === undefined ? t("message.toolRunning", { name: part.name }) : t("message.tool", { name: part.name })}</summary>
      <div className="space-y-2 border-t border-stone-300 p-3 dark:border-stone-600">
        <p className="font-medium">{t("message.toolArguments")}</p>
        <pre className="overflow-x-auto rounded bg-stone-100 p-2 dark:bg-stone-900">{part.args}</pre>
        {part.result !== undefined && (
          <>
            <p className="font-medium">{t("message.toolResult")}</p>
            <pre className="max-h-80 overflow-auto rounded bg-stone-100 p-2 dark:bg-stone-900">{part.result}</pre>
          </>
        )}
      </div>
    </details>
  );
}
