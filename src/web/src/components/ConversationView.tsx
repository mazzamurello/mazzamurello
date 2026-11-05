import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Copy, FilePen, GitFork, Pencil } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useNavigate, useParams } from "react-router";

import { ApiError, api, unwrap, type ModelChoice, type MessagePage, type PathRun } from "../api/client";
import { forkConversation, rewindConversation, updateConversation, useRefreshConversations } from "../conversations";
import { formatMoney, isPaid, USAGE } from "../costs";
import { useNotify } from "../notices";
import { type LivePart, type LiveRun, poseOf, type RunUsage, toolActivity, useLiveRun } from "../run";
import { Composer } from "./Composer";
import { Markdown } from "./Markdown";
import { Sprite } from "./Sprite";

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

/** The runs of the conversation, each with its user message and what answered it. */
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

/** The messages a person sees in a turn's answer: its texts, or one for an answer of tools only. */
function shownAnswer(turn: Turn): number {
  const texts = turn.parts.filter((part) => part.kind === "text").length;
  return texts > 0 ? texts : turn.parts.length > 0 ? 1 : 0;
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

interface PendingEdit {
  index: number;
  turn: Turn;
  text: string;
  deleted: number;
}

export function ConversationView() {
  const { t } = useTranslation();
  const { conversationId = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queries = useQueryClient();
  const refreshList = useRefreshConversations();
  const notify = useNotify();
  const conversation = useQuery({
    queryKey: ["conversation", conversationId, "details"],
    queryFn: async () => unwrap(await api.GET("/conversations/{conversation_id}", { params: { path: { conversation_id: conversationId } } })),
  });
  const history = useQuery({ queryKey: ["conversation", conversationId, "messages"], queryFn: () => allMessages(conversationId) });

  // While an edited message streams, the turn it replaces and the ones after it are gone.
  const [hideFrom, setHideFrom] = useState<number | null>(null);
  const refresh = useCallback(async () => {
    await queries.invalidateQueries({ queryKey: ["conversation", conversationId] });
    await queries.invalidateQueries({ queryKey: USAGE });
    await refreshList();
  }, [queries, refreshList, conversationId]);
  const runEnded = useCallback(async () => {
    await refresh();
    setHideFrom(null);
  }, [refresh]);

  const { live, start, follow, stop, running } = useLiveRun(runEnded);
  // The latest context reading stays in view after the run, until another conversation opens.
  const [contextUsage, setContextUsage] = useState<RunUsage | null>(null);
  const [usageFor, setUsageFor] = useState(conversationId);
  if (usageFor !== conversationId) {
    setUsageFor(conversationId);
    setContextUsage(null);
  }
  if (live?.usage && live.usage !== contextUsage) setContextUsage(live.usage);
  const [pending, setPending] = useState<PendingEdit | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const thread = useRef<HTMLDivElement>(null);

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

  // An error says what went wrong and what to do (UX-014).
  const reported = useRef<string | null>(null);
  useEffect(() => {
    if (live?.status !== "failed" || live.errorCode === "run.cancelled" || reported.current === live.runId) return;
    reported.current = live.runId;
    notify({ kind: "error", title: t("errors.title"), text: explain(t, live) });
  }, [live, notify, t]);

  // The thread follows the answer as it streams.
  useEffect(() => {
    const element = thread.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [live, history.data]);

  /** A new conversation from a copy of this one up to the turn (CNV-005). */
  async function fork(turn: Turn) {
    try {
      const copy = await forkConversation(conversationId, turn.run.run_id);
      await refreshList();
      await navigate(`/c/${copy.id}`);
    } catch (error) {
      notify({ kind: "error", title: t("errors.title"), text: t(`errors.${codeKey(error)}`) });
    }
  }

  async function chooseModel(choice: ModelChoice) {
    await updateConversation(conversationId, { model: choice });
    await refresh();
  }

  /** Editing a message rewinds to the turn before it, then sends the edited text (CNV-016, ADR-0068). */
  async function sendEdit(edit: PendingEdit) {
    setPending(null);
    setEditing(null);
    setHideFrom(edit.index);
    try {
      await rewindConversation(conversationId, edit.turn.run.parent_run_id);
      await refresh();
    } catch (error) {
      setHideFrom(null);
      notify({ kind: "error", title: t("errors.title"), text: t(`errors.${codeKey(error)}`) });
      return;
    }
    start({ conversationId, text: edit.text });
  }

  if (conversation.error instanceof ApiError && conversation.error.status === 404) {
    return <p className="p-6">{t("errors.notFound")}</p>;
  }

  const turns = history.data ? turnsOf(history.data) : [];
  const shown = live !== null && hideFrom !== null ? turns.slice(0, hideFrom) : turns;

  function askToEdit(index: number, turn: Turn, text: string) {
    const deleted = shownAnswer(turn) + turns.slice(index + 1).reduce((sum, later) => sum + (later.userText === null ? 0 : 1) + shownAnswer(later), 0);
    const edit = { index, turn, text, deleted };
    if (deleted === 0) void sendEdit(edit);
    else setPending(edit);
  }

  return (
    <>
      <div ref={thread} className="relative min-h-0 flex-1 overflow-y-auto" aria-busy={running}>
        <ol className="mx-auto w-full max-w-[740px] px-4 pt-2 pb-6">
          {conversation.data?.forked_from && (
            <li className="mt-3 flex items-center gap-2 text-[13px] text-muted">
              <GitFork className="size-4" aria-hidden="true" />
              {conversation.data.forked_from.conversation_id ? (
                <Link to={`/c/${conversation.data.forked_from.conversation_id}`} className="underline underline-offset-2 hover:text-fg">
                  {t("message.forkedFrom")}
                </Link>
              ) : (
                t("message.forkedFrom")
              )}
            </li>
          )}
          {shown.map((turn, index) => (
            <TurnView
              key={turn.run.run_id}
              turn={turn}
              busy={running}
              last={live === null && index === shown.length - 1}
              editing={editing === index}
              onEdit={() => setEditing(index)}
              onCancelEdit={() => setEditing(null)}
              onSendEdit={(text) => askToEdit(index, turn, text)}
              onFork={() => void fork(turn)}
            />
          ))}
          {live && (
            <li className="my-5 flex flex-col gap-1">
              {live.userText !== null && <UserBubble text={live.userText} />}
              <Answer parts={live.parts} />
              <Activity run={live} />
            </li>
          )}
        </ol>
      </div>
      <div className="flex-none px-4 pt-1.5 pb-[max(0.875rem,env(safe-area-inset-bottom))]">
        <div className="mx-auto max-w-[740px]">
          {/* The open conversation's cost and its context stay in view (UX-008). */}
          <div className="mb-1.5 flex min-h-4 flex-wrap items-center justify-end gap-x-4 gap-y-1 text-xs text-muted tabular-nums">
            {conversation.data && (
              <span className="flex items-center gap-1.5">
                <span>{t("usage.conversation")}</span>
                <span className="font-semibold text-fg">{formatMoney(conversation.data.cost)}</span>
              </span>
            )}
            {contextUsage && <ContextGauge usage={contextUsage} />}
          </div>
          <Composer
            onSend={(text) => start({ conversationId, text })}
            onStop={() => void stop()}
            running={running}
            model={conversation.data?.model ?? null}
            onModel={(choice) => void chooseModel(choice)}
            placeholder={t("composer.placeholder")}
          />
        </div>
      </div>
      <Dialog.Root open={pending !== null} onOpenChange={(open) => !open && setPending(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
          <Dialog.Content role="alertdialog" className="rise fixed top-1/2 left-1/2 z-50 w-[min(92vw,28rem)] -translate-x-1/2 -translate-y-1/2 rounded-[20px] bg-raised p-[22px] shadow-soft">
            <Dialog.Title className="mb-2 text-lg font-bold tracking-tight">{t("rewind.title")}</Dialog.Title>
            <Dialog.Description className="mb-2.5 text-muted">
              {pending?.deleted === 1 ? t("rewind.bodyOne", { count: 1 }) : t("rewind.bodyMany", { count: pending?.deleted ?? 0 })}
            </Dialog.Description>
            {/* Rewinding never changes the workspace, and the user is told so (UX-010). */}
            <p className="flex items-center gap-2 rounded-[10px] bg-hover px-3 py-2.5 text-sm">
              <FilePen className="size-[18px] flex-none" aria-hidden="true" />
              {t("rewind.files")}
            </p>
            <div className="mt-[18px] flex flex-wrap justify-end gap-2">
              <Dialog.Close className="h-[38px] rounded-[10px] border border-line-strong bg-surface px-4 text-sm font-semibold hover:bg-hover">{t("rewind.cancel")}</Dialog.Close>
              <button
                type="button"
                className="h-[38px] rounded-[10px] bg-danger px-4 text-sm font-semibold text-on-danger"
                onClick={() => pending && void sendEdit(pending)}
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

function codeKey(error: unknown): string {
  const code = error instanceof ApiError ? error.code : "internal.error";
  return ["model.unavailable", "model.request_failed", "model.refused", "sandbox.unavailable", "run.worker_lost", "run.timeout"].includes(code) ? code.replace(".", "_") : "internal_error";
}

function explain(t: (key: string) => string, run: LiveRun): string {
  const text = t(`errors.${codeKey(new ApiError(0, run.errorCode ?? "internal.error"))}`);
  return run.reason ? `${text} ${run.reason}` : text;
}

/** The sprite acting out what the assistant does, and the same in words (UX-013). */
function Activity({ run }: { run: LiveRun }) {
  const { t } = useTranslation();
  const pose = poseOf(run);
  const working = run.status === "running";
  const words =
    run.status === "failed"
      ? run.errorCode === "run.cancelled"
        ? t("message.stopped")
        : t("errors.title")
      : working
        ? t(`activity.${pose}`)
        : "";
  const usage = run.usage;
  const cost = usage?.cost && isPaid([usage.cost]) ? formatMoney([usage.cost]) : null;
  return (
    <div className="mt-0.5 flex min-h-[58px] items-center gap-2.5">
      <Sprite pose={pose} className="h-[53px] w-[46px] flex-none" />
      <span role="status" className="flex items-center gap-2 text-sm text-muted">
        <span className={working ? "live-text" : ""}>{words}</span>
        {working && cost && <span className="tabular-nums">· {cost}</span>}
      </span>
    </div>
  );
}

function compact(tokens: number): string {
  return tokens >= 1000 ? `${Number((tokens / 1000).toFixed(tokens >= 100_000 ? 0 : 1))}k` : String(tokens);
}

/** How much of the model's context window the conversation uses: tokens, window, share and a gauge (UX-008). */
function ContextGauge({ usage }: { usage: RunUsage }) {
  const { t } = useTranslation();
  const percent = Math.round(Math.min(1, usage.context_tokens / Math.max(1, usage.context_window)) * 100);
  const text = t("usage.contextValue", { used: compact(usage.context_tokens), size: compact(usage.context_window), percent });
  return (
    <span className="flex items-center gap-2">
      <span>{text}</span>
      <span
        role="meter"
        aria-label={t("usage.context")}
        aria-valuemin={0}
        aria-valuemax={usage.context_window}
        aria-valuenow={usage.context_tokens}
        aria-valuetext={text}
        className="h-1.5 w-20 overflow-hidden rounded-full bg-hover"
      >
        <span className={`block h-full rounded-full ${percent >= 80 ? "bg-danger" : "bg-accent"}`} style={{ width: `${Math.max(3, percent)}%` }} />
      </span>
    </span>
  );
}

function TurnView(props: {
  turn: Turn;
  busy: boolean;
  last: boolean;
  editing: boolean;
  onEdit: () => void;
  onCancelEdit: () => void;
  onSendEdit: (text: string) => void;
  onFork: () => void;
}) {
  const { t } = useTranslation();
  const { turn, busy } = props;
  const answerText = turn.parts.flatMap((part) => (part.kind === "text" ? [part.text] : [])).join("\n\n");
  return (
    <li className="group/turn my-5 flex flex-col gap-1">
      {turn.userText !== null &&
        (props.editing ? (
          <form
            className="flex w-full max-w-[600px] flex-col gap-2.5 self-end rounded-[18px] border border-line-strong bg-surface px-3.5 py-3"
            onSubmit={(event) => {
              event.preventDefault();
              const text = String(new FormData(event.currentTarget).get("text") ?? "").trim();
              if (text) props.onSendEdit(text);
            }}
          >
            <label className="sr-only" htmlFor={`edit-${turn.run.run_id}`}>
              {t("message.editLabel")}
            </label>
            <textarea id={`edit-${turn.run.run_id}`} name="text" defaultValue={turn.userText} rows={3} autoFocus className="min-h-[60px] resize-none bg-transparent outline-none" />
            <div className="flex items-center justify-end gap-2">
              <small className="flex-1 text-[12.5px] text-muted">{t("message.editHint")}</small>
              <button type="button" className="h-8 rounded-[10px] border border-line-strong px-3 text-[13px] font-semibold hover:bg-hover" onClick={props.onCancelEdit}>
                {t("message.cancelEdit")}
              </button>
              <button type="submit" className="h-8 rounded-[10px] bg-fg px-3 text-[13px] font-semibold text-bg">
                {t("message.saveEdit")}
              </button>
            </div>
          </form>
        ) : (
          <div className="group/message flex flex-col items-end gap-1">
            <UserBubble text={turn.userText} />
            <div className="flex gap-0.5 opacity-0 transition-opacity group-hover/message:opacity-100 group-focus-within/message:opacity-100 [@media(hover:none)]:opacity-100">
              <CopyButton text={turn.userText} />
              <IconButton label={t("message.edit")} disabled={busy} onClick={props.onEdit}>
                <Pencil className="size-4" aria-hidden="true" />
              </IconButton>
            </div>
          </div>
        ))}
      <Answer parts={turn.parts} />
      {props.last && (
        <div className="mt-0.5 flex min-h-[58px] items-center gap-2.5">
          <Sprite pose="waiting" className="h-[53px] w-[46px] flex-none" />
        </div>
      )}
      {answerText && (
        <div className="flex items-center gap-0.5">
          <div className={`flex gap-0.5 transition-opacity group-hover/turn:opacity-100 group-focus-within/turn:opacity-100 [@media(hover:none)]:opacity-100 ${props.last ? "opacity-100" : "opacity-0"}`}>
            <CopyButton text={answerText} />
            <IconButton label={t("message.fork")} disabled={busy} onClick={props.onFork}>
              <GitFork className="size-4" aria-hidden="true" />
            </IconButton>
          </div>
          {/* Each answer's cost, beside its actions and always in view; a local model's is nothing to show (UX-008). */}
          {isPaid(turn.run.cost) && <span className="pl-1.5 text-xs text-muted tabular-nums">{formatMoney(turn.run.cost)}</span>}
        </div>
      )}
    </li>
  );
}

function IconButton(props: { label: string; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      className="grid size-[30px] place-items-center rounded-lg text-muted hover:bg-hover hover:text-fg disabled:opacity-40"
      aria-label={props.label}
      title={props.label}
      disabled={props.disabled}
      onClick={props.onClick}
    >
      {props.children}
    </button>
  );
}

function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation();
  const notify = useNotify();
  return (
    <IconButton
      label={t("message.copyMessage")}
      onClick={() => {
        void navigator.clipboard.writeText(text).then(() => notify({ kind: "info", title: t("message.copied") }));
      }}
    >
      <Copy className="size-4" aria-hidden="true" />
    </IconButton>
  );
}

function UserBubble({ text }: { text: string }) {
  const { t } = useTranslation();
  return (
    <div className="flex justify-end">
      <div className="max-w-[min(85%,560px)] rounded-[20px] bg-bubble px-[15px] py-2.5 break-words whitespace-pre-wrap">
        <span className="sr-only">{t("message.you")}: </span>
        {text}
      </div>
    </div>
  );
}

function Answer({ parts }: { parts: LivePart[] }) {
  const tools = parts.filter((part) => part.kind === "tool");
  const texts = parts.filter((part) => part.kind === "text");
  return (
    <div className="flex min-w-0 flex-col gap-2.5">
      {tools.length > 0 && (
        <div className="flex flex-col items-start gap-1.5">
          {tools.map((part) => (
            <ToolCall key={part.id} part={part} />
          ))}
        </div>
      )}
      {texts.map((part) => (
        <Markdown key={part.id} text={part.text} />
      ))}
    </div>
  );
}

function argumentPreview(args: string): string {
  try {
    const parsed = JSON.parse(args) as Record<string, unknown>;
    const first = Object.values(parsed).find((value) => typeof value === "string");
    return typeof first === "string" ? first : "";
  } catch {
    return "";
  }
}

/** Tool activity as a compact summary that expands to its full details (UX-003). */
function ToolCall({ part }: { part: Extract<LivePart, { kind: "tool" }> }) {
  const { t } = useTranslation();
  const activity = toolActivity(part.name);
  const label =
    activity === "running" ? t("activity.ran") : activity === "writing" ? t("activity.wrote") : activity === "reading" ? t("activity.read") : activity === "searching" ? t("activity.searched") : t("activity.used", { name: part.name });
  const preview = argumentPreview(part.args);
  return (
    <details className="group/tool max-w-full">
      <summary className="inline-flex max-w-full cursor-pointer list-none items-center gap-2 rounded-full border border-line py-[5px] pr-2.5 pl-[9px] text-[13.5px] text-muted hover:bg-hover hover:text-fg [&::-webkit-details-marker]:hidden">
        <b className="font-semibold whitespace-nowrap text-fg">{label}</b>
        {preview && <span className="min-w-0 truncate font-mono text-[12.5px]">{preview}</span>}
        <ChevronRight className="size-4 flex-none transition-transform group-open/tool:rotate-90" aria-hidden="true" />
      </summary>
      <div className="mt-2 mb-1 ml-3.5 flex flex-col gap-2 border-l-2 border-line py-1 pl-3.5 text-[13.5px] text-muted">
        <p className="font-semibold">{t("message.toolArguments")}</p>
        <pre className="overflow-x-auto rounded-lg bg-hover p-2 font-mono text-[12.5px] text-fg">{part.args}</pre>
        {part.result !== undefined && (
          <>
            <p className="font-semibold">{t("message.toolResult")}</p>
            <pre className="max-h-80 overflow-auto rounded-lg bg-hover p-2 font-mono text-[12.5px] whitespace-pre-wrap text-fg">{part.result}</pre>
          </>
        )}
      </div>
    </details>
  );
}
