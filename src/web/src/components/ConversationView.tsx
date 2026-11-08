import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, ChevronRight, Copy, Download, FilePen, FileText, FolderOpen, GitFork, Pencil, SlidersHorizontal } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useNavigate, useParams } from "react-router";

import { ApiError, api, unwrap, type ModelChoice, type MessagePage, type PathRun } from "../api/client";
import { forkConversation, rewindConversation, updateConversation, useRefreshConversations } from "../conversations";
import { formatMoney, isPaid, USAGE } from "../costs";
import { useNotify } from "../notices";
import { type LivePart, type LiveRun, poseOf, type RunUsage, toolActivity, useLiveRun } from "../run";
import { type AttachedFile, download, downloadUrl, formatSize, listFolder, useAttachments } from "../workspace";
import { ChatSettings } from "./AssistantSettings";
import { Composer } from "./Composer";
import { Markdown } from "./Markdown";
import { Sprite } from "./Sprite";
import { type Reveal, WorkspacePanel } from "./WorkspacePanel";

type AgUiMessage = MessagePage["items"][number] & {
  content?: unknown;
  toolCalls?: { id: string; function: { name: string; arguments: string } }[];
  toolCallId?: string;
  attachments?: AttachedFile[];
};

interface Turn {
  run: PathRun;
  userText: string | null;
  attachments: AttachedFile[];
  parts: LivePart[];
}

/** The runs of the conversation, each with its user message and what answered it. */
function turnsOf(page: MessagePage): Turn[] {
  const byId = new Map(page.items.map((message) => [message.id, message as AgUiMessage]));
  return page.runs.map((run) => {
    const messages = run.message_ids.flatMap((id) => byId.get(id) ?? []);
    const results = new Map(messages.filter((m) => m.role === "tool").map((m) => [m.toolCallId, textOf(m.content)]));
    let userText: string | null = null;
    let attachments: AttachedFile[] = [];
    const parts: LivePart[] = [];
    for (const message of messages) {
      if (message.role === "user" && userText === null) {
        userText = textOf(message.content);
        attachments = message.attachments ?? [];
      }
      else if (message.role === "reasoning") {
        const text = textOf(message.content);
        if (text) parts.push({ kind: "reasoning", id: message.id, text });
      }
      else if (message.role === "assistant") {
        const text = textOf(message.content);
        if (text) parts.push({ kind: "text", id: message.id, text });
        for (const call of message.toolCalls ?? []) {
          const result = results.get(call.id);
          parts.push({ kind: "tool", id: call.id, name: call.function.name, args: call.function.arguments, ...(result === undefined ? {} : { result }) });
        }
      }
    }
    return { run, userText, attachments, parts };
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
  const [panelOpen, setPanelOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [reveal, setReveal] = useState<Reveal | null>(null);
  const [panelFor, setPanelFor] = useState(conversationId);
  if (panelFor !== conversationId) {
    setPanelFor(conversationId);
    setReveal(null);
  }
  const owner = useCallback(() => Promise.resolve(conversationId), [conversationId]);
  const attachments = useAttachments(owner);
  const show = useCallback((path: string) => {
    setReveal({ path, at: Date.now() });
    setPanelOpen(true);
  }, []);

  // The first message of a new chat, handed over by the new-chat screen, with its attachments.
  const handedOver = location.state as { firstMessage?: string; attachments?: AttachedFile[] } | null;
  const firstMessage = handedOver?.firstMessage;
  const firstAttachments = handedOver?.attachments;
  const started = useRef(false);
  useEffect(() => {
    if (firstMessage && !started.current) {
      started.current = true;
      start({ conversationId, text: firstMessage, attachments: firstAttachments ?? [] });
      void navigate(location.pathname, { replace: true, state: null });
    }
  }, [firstMessage, firstAttachments, conversationId, start, navigate, location.pathname]);

  // A run in progress, started on another device or before a reload: follow it (CNV-015).
  const activeRunId = conversation.data?.active_run_id;
  useEffect(() => {
    if (!activeRunId || running || started.current) return;
    void api.GET("/runs/{run_id}", { params: { path: { run_id: activeRunId } } }).then((result) => {
      if (result.data?.status === "queued" || result.data?.status === "running") follow(activeRunId);
    });
  }, [activeRunId, running, follow]);

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
  // A failed run, once in the history, is shown there with its error (UX-014); a reason only the
  // stream gave stays with it until the next run.
  const settled = live?.status === "failed" && shown.some((turn) => turn.run.run_id === live.runId);
  const liveReason = live?.status === "failed" ? { runId: live.runId, reason: live.reason } : null;

  function askToEdit(index: number, turn: Turn, text: string) {
    const deleted = shownAnswer(turn) + turns.slice(index + 1).reduce((sum, later) => sum + (later.userText === null ? 0 : 1) + shownAnswer(later), 0);
    const edit = { index, turn, text, deleted };
    if (deleted === 0) void sendEdit(edit);
    else setPending(edit);
  }

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-w-0 flex-1 flex-col">
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
              last={(live === null || settled) && index === shown.length - 1}
              reason={liveReason?.runId === turn.run.run_id ? liveReason.reason : undefined}
              editing={editing === index}
              onEdit={() => setEditing(index)}
              onCancelEdit={() => setEditing(null)}
              onSendEdit={(text) => askToEdit(index, turn, text)}
              onFork={() => void fork(turn)}
              conversationId={conversationId}
              onShow={show}
            />
          ))}
          {live && !settled && (
            <li className="my-5 flex flex-col gap-1">
              {live.userText !== null && <UserBubble text={live.userText} attachments={live.attachments ?? []} onShow={show} />}
              <Answer parts={live.parts} conversationId={conversationId} onShow={show} />
              {live.status === "failed" && live.errorCode !== "run.cancelled" ? (
                <RunErrorView code={live.errorCode ?? "internal.error"} reason={live.reason ?? null} />
              ) : (
                <Activity run={live} />
              )}
            </li>
          )}
        </ol>
      </div>
      <div className="flex-none px-4 pt-1.5 pb-[max(0.875rem,env(safe-area-inset-bottom))]">
        <div className="mx-auto max-w-[740px]">
          {/* The open conversation's cost and its context stay in view (UX-008). */}
          <div className="mb-1.5 flex min-h-4 flex-wrap items-center justify-end gap-x-4 gap-y-1 text-xs text-muted tabular-nums">
            <button
              type="button"
              onClick={() => setPanelOpen((open) => !open)}
              aria-expanded={panelOpen}
              className="-ml-1.5 mr-auto flex items-center gap-1.5 rounded-lg px-1.5 py-1 font-semibold hover:bg-hover hover:text-fg"
            >
              <FolderOpen className="size-4" aria-hidden="true" />
              {t("files.title")}
            </button>
            {conversation.data && (
              <button
                type="button"
                onClick={() => setSettingsOpen(true)}
                className="-ml-1.5 flex items-center gap-1.5 rounded-lg px-1.5 py-1 font-semibold hover:bg-hover hover:text-fg"
              >
                <SlidersHorizontal className="size-4" aria-hidden="true" />
                {t("assistant.chat")}
              </button>
            )}
            {conversation.data && (
              <span className="flex items-center gap-1.5">
                <span>{t("usage.conversation")}</span>
                <span className="font-semibold text-fg">{formatMoney(conversation.data.cost)}</span>
              </span>
            )}
            {contextUsage && <ContextGauge usage={contextUsage} />}
          </div>
          <Composer
            onSend={(text, files) => start({ conversationId, text, attachments: files })}
            attachments={attachments}
            onStop={() => void stop()}
            running={running}
            model={conversation.data?.model ?? null}
            onModel={(choice) => void chooseModel(choice)}
            placeholder={t("composer.placeholder")}
          />
        </div>
      </div>
      </div>
      <WorkspacePanel conversationId={conversationId} open={panelOpen} onOpenChange={setPanelOpen} reveal={reveal} />
      {conversation.data && <ChatSettings conversation={conversation.data} open={settingsOpen} onOpenChange={setSettingsOpen} />}
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
    </div>
  );
}

function codeKey(error: unknown): string {
  const code = error instanceof ApiError ? error.code : "internal.error";
  return ["model.unavailable", "model.request_failed", "model.refused", "sandbox.unavailable", "run.worker_lost", "run.timeout"].includes(code) ? code.replace(".", "_") : "internal_error";
}

/** Why a run failed, where its answer would be, with what the model said (UX-014, MOD-015). */
function RunErrorView({ code, reason }: { code: string; reason: string | null }) {
  const { t } = useTranslation();
  return (
    <div role="alert" className="mt-1 flex items-start gap-2.5 rounded-2xl border border-danger/45 bg-raised py-2.5 pr-3.5 pl-2">
      <Sprite pose="error" className="h-[53px] w-[46px] flex-none" />
      <div className="min-w-0 flex-1 pt-1 text-sm">
        <strong className="block">{t("errors.title")}</strong>
        <p className="mt-0.5 text-muted">{t(`errors.${codeKey(new ApiError(0, code))}`)}</p>
        {reason && <blockquote className="mt-1.5 border-l-2 border-line-strong pl-2.5 break-words whitespace-pre-wrap">{reason}</blockquote>}
      </div>
    </div>
  );
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
  // What the run's stream said about its failure, when the history keeps no reason.
  reason?: string | undefined;
  editing: boolean;
  onEdit: () => void;
  onCancelEdit: () => void;
  onSendEdit: (text: string) => void;
  onFork: () => void;
  conversationId: string;
  onShow: (path: string) => void;
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
            <UserBubble text={turn.userText} attachments={turn.attachments} onShow={props.onShow} />
            <div className="flex gap-0.5 opacity-0 transition-opacity group-hover/message:opacity-100 group-focus-within/message:opacity-100 [@media(hover:none)]:opacity-100">
              <CopyButton text={turn.userText} />
              <IconButton label={t("message.edit")} disabled={busy} onClick={props.onEdit}>
                <Pencil className="size-4" aria-hidden="true" />
              </IconButton>
            </div>
          </div>
        ))}
      <Answer parts={turn.parts} conversationId={props.conversationId} onShow={props.onShow} />
      {turn.run.error && turn.run.error.code !== "run.cancelled" && (
        <RunErrorView code={turn.run.error.code} reason={turn.run.error.reason ?? props.reason ?? null} />
      )}
      {props.last && !turn.run.error && (
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

/** A message's attachments, as chips that show the file in the workspace panel (CNV-017). */
function UserBubble({ text, attachments, onShow }: { text: string; attachments: AttachedFile[]; onShow: (path: string) => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-end gap-1.5">
      {attachments.length > 0 && (
        <ul aria-label={t("files.attachments")} className="flex max-w-[min(85%,560px)] flex-wrap justify-end gap-1.5">
          {attachments.map((file) => (
            <li key={file.path}>
              <button type="button" onClick={() => onShow(file.path)} className="flex max-w-[260px] items-center gap-2 rounded-xl border border-line bg-surface py-1.5 pr-3 pl-2.5 text-left text-[13px] hover:bg-hover">
                <FileText className="size-4 flex-none text-muted" aria-hidden="true" />
                <span className="flex min-w-0 flex-col">
                  <span className="truncate font-semibold">{file.path.split("/").at(-1)}</span>
                  <span className="text-muted">{formatSize(file.size)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    <div className="flex w-full justify-end">
      <div className="max-w-[min(85%,560px)] rounded-[20px] bg-bubble px-[15px] py-2.5 break-words whitespace-pre-wrap">
        <span className="sr-only">{t("message.you")}: </span>
        {text}
      </div>
    </div>
    </div>
  );
}

function Answer({ parts, conversationId, onShow }: { parts: LivePart[]; conversationId: string; onShow: (path: string) => void }) {
  const offers = parts.flatMap((part) => (part.kind === "tool" ? (offerOf(part) ?? []) : []));
  const tools = parts.flatMap((part) => (part.kind === "tool" && offerOf(part) === null ? [part] : []));
  const texts = parts.filter((part) => part.kind === "text");
  const reasoning = parts.flatMap((part) => (part.kind === "reasoning" ? [part.text] : [])).join("\n\n");
  return (
    <div className="flex min-w-0 flex-col gap-2.5">
      {reasoning && <ReasoningView text={reasoning} />}
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
      {offers.length > 0 && (
        <div className="flex flex-col items-start gap-1.5">
          {offers.map((offer) => (
            <OfferCard key={offer.id} offer={offer} conversationId={conversationId} onShow={onShow} />
          ))}
        </div>
      )}
    </div>
  );
}

/** The model's reasoning, folded above its answer (CNV-013). */
function ReasoningView({ text }: { text: string }) {
  const { t } = useTranslation();
  return (
    <details className="group/reasoning max-w-full">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-lg py-1 pr-2 text-[13.5px] font-semibold text-muted hover:text-fg [&::-webkit-details-marker]:hidden">
        <Brain className="size-4" aria-hidden="true" />
        {t("message.reasoning")}
        <ChevronRight className="size-4 flex-none transition-transform group-open/reasoning:rotate-90" aria-hidden="true" />
      </summary>
      <p className="mt-1.5 mb-1 ml-2 border-l-2 border-line py-1 pl-3.5 text-[13.5px] whitespace-pre-wrap text-muted">{text}</p>
    </details>
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

interface Offer {
  id: string;
  path: string;
  size: number | null;
}

/** A file the assistant offered, once the tool found it (AGT-023). */
function offerOf(part: Extract<LivePart, { kind: "tool" }>): Offer | null {
  if (part.name !== "offer_download" || part.result === undefined || !part.result.startsWith("Offered ")) return null;
  let path = "";
  try {
    path = String((JSON.parse(part.args) as { path?: unknown }).path ?? "");
  } catch {
    return null;
  }
  path = path.trim().replace(/^\/workspace/, "").replace(/^\/+|\/+$/g, "");
  const size = /\((\d+) bytes\)/.exec(part.result)?.[1];
  return path ? { id: part.id, path, size: size === undefined ? null : Number(size) } : null;
}

/** An offered file: it downloads as it is now, when the user taps it, or says it is gone (AGT-023, ADR-0079). */
function OfferCard({ offer, conversationId, onShow }: { offer: Offer; conversationId: string; onShow: (path: string) => void }) {
  const { t } = useTranslation();
  const [gone, setGone] = useState(false);
  const name = offer.path.split("/").at(-1) ?? offer.path;
  const folder = offer.path.includes("/") ? offer.path.slice(0, offer.path.lastIndexOf("/")) : "";

  async function get() {
    try {
      const entries = await listFolder(conversationId, folder);
      if (!entries.some((entry) => entry.path === offer.path && entry.type === "file")) {
        setGone(true);
        return;
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        setGone(true);
        return;
      }
    }
    setGone(false);
    download(downloadUrl(conversationId, offer.path));
  }

  return (
    <div role="group" aria-label={name} className="flex w-[min(100%,360px)] items-center gap-3 rounded-2xl border border-line bg-surface py-2.5 pr-2.5 pl-3 shadow-soft">
      <span className="grid size-10 flex-none place-items-center rounded-xl bg-accent-soft text-accent" aria-hidden="true">
        <FileText className="size-5" />
      </span>
      <button type="button" onClick={() => onShow(offer.path)} className="flex min-w-0 flex-1 flex-col text-left" title={t("files.show")}>
        <span className="truncate font-semibold">{name}</span>
        <span className={`text-[12.5px] ${gone ? "text-danger" : "text-muted"}`}>{gone ? t("files.gone") : offer.size === null ? "" : formatSize(offer.size)}</span>
      </button>
      <button type="button" onClick={() => void get()} className="flex h-9 flex-none items-center gap-1.5 rounded-xl bg-fg px-3 text-sm font-semibold text-bg">
        <Download className="size-4" aria-hidden="true" />
        {t("files.download")}
      </button>
    </div>
  );
}
