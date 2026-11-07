import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Download, File, Folder, FolderPlus, Link2, Pencil, RotateCcw, Trash2, Upload, X } from "lucide-react";
import { type FormEvent, type KeyboardEvent, type ReactNode, useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { useNotify } from "../notices";
import {
  archiveUrl,
  createFolder,
  deleteEntry,
  download,
  downloadUrl,
  formatSize,
  listFolder,
  moveEntry,
  previewKind,
  previewUrl,
  resetWorkspace,
  upload,
  type WorkspaceEntry,
  workspaceSummary,
} from "../workspace";
import { errorKey } from "./Composer";
import { Markdown } from "./Markdown";

const WIDE = "(min-width: 768px)";
// The API shows at most this much of a text (UX-020).
const TEXT_PREVIEW_BYTES = 1024 * 1024;
const CSV_ROWS = 200;

/** Whether the screen is wide enough for the panel beside the conversation. */
export function useWide(): boolean {
  return useSyncExternalStore(
    (changed) => {
      const query = window.matchMedia(WIDE);
      query.addEventListener("change", changed);
      return () => query.removeEventListener("change", changed);
    },
    () => window.matchMedia(WIDE).matches,
  );
}

export function workspaceKey(conversationId: string): unknown[] {
  return ["conversation", conversationId, "workspace"];
}

function parentOf(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash === -1 ? "" : path.slice(0, slash);
}

function useFolder(conversationId: string, path: string, enabled = true) {
  return useQuery({
    queryKey: [...workspaceKey(conversationId), "folder", path],
    queryFn: () => listFolder(conversationId, path),
    enabled,
  });
}

/** A file to show in the panel, as a chip or a card asks (UX-019). */
export interface Reveal {
  path: string;
  at: number;
}

/**
 * The conversation's workspace: a tree with previews and the actions on its files, beside the
 * conversation on a computer and a full-screen sheet on a phone (UX-019, ADR-0079).
 */
export function WorkspacePanel(props: { conversationId: string; open: boolean; onOpenChange: (open: boolean) => void; reveal: Reveal | null }) {
  const { t } = useTranslation();
  const wide = useWide();
  const title = useId();
  if (wide) {
    if (!props.open) return null;
    return (
      <section aria-labelledby={title} className="flex w-[min(400px,40vw)] flex-none flex-col border-l border-line bg-panel">
        <header className="flex h-[52px] flex-none items-center gap-2 px-4">
          <h2 id={title} className="flex-1 font-semibold">
            {t("files.title")}
          </h2>
          <button type="button" onClick={() => props.onOpenChange(false)} className="grid size-9 place-items-center rounded-lg text-muted hover:bg-hover hover:text-fg" aria-label={t("files.close")} title={t("files.close")}>
            <X className="size-5" aria-hidden="true" />
          </button>
        </header>
        <PanelBody conversationId={props.conversationId} reveal={props.reveal} />
      </section>
    );
  }
  return (
    <Dialog.Root open={props.open} onOpenChange={props.onOpenChange}>
      <Dialog.Portal>
        <Dialog.Content aria-describedby={undefined} className="fixed inset-0 z-50 flex flex-col bg-panel pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] text-fg">
          <header className="flex h-[52px] flex-none items-center gap-2 px-4">
            <Dialog.Title className="flex-1 font-semibold">{t("files.title")}</Dialog.Title>
            <Dialog.Close className="grid size-9 place-items-center rounded-lg text-muted hover:bg-hover hover:text-fg" aria-label={t("files.close")}>
              <X className="size-5" aria-hidden="true" />
            </Dialog.Close>
          </header>
          <PanelBody conversationId={props.conversationId} reveal={props.reveal} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

type Asking = { kind: "delete" | "rename"; entry: WorkspaceEntry } | { kind: "folder"; in: string } | { kind: "reset" };

interface Transfer {
  key: string;
  name: string;
  progress: number;
}

function PanelBody({ conversationId, reveal }: { conversationId: string; reveal: Reveal | null }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const [hidden, setHidden] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [asking, setAsking] = useState<Asking | null>(null);
  const [transfers, setTransfers] = useState<Transfer[]>([]);
  const picker = useRef<HTMLInputElement>(null);
  const summary = useQuery({ queryKey: [...workspaceKey(conversationId), "summary"], queryFn: () => workspaceSummary(conversationId) });

  // A chip or a card opened the panel on one of its files: show it.
  const [revealed, setRevealed] = useState<Reveal | null>(null);
  if (reveal !== null && reveal !== revealed) {
    setRevealed(reveal);
    const folders = new Set(expanded);
    let folder = parentOf(reveal.path);
    while (folder) {
      folders.add(folder);
      folder = parentOf(folder);
    }
    setExpanded(folders);
    setSelected(reveal.path);
  }

  const siblings = useFolder(conversationId, selected === null ? "" : parentOf(selected), selected !== null);
  const entry = selected === null ? null : (siblings.data?.find((candidate) => candidate.path === selected) ?? null);
  // Uploads and new folders go into the chosen folder, or the chosen file's folder.
  const target = entry === null ? "" : entry.type === "folder" ? entry.path : parentOf(entry.path);

  async function changed() {
    await queries.invalidateQueries({ queryKey: workspaceKey(conversationId) });
  }

  function failed(error: unknown) {
    const code = error instanceof ApiError ? error.code : "internal.error";
    notify({ kind: "error", title: t("errors.title"), text: t(`files.errors.${errorKey(code)}`) });
  }

  function toggle(path: string) {
    setExpanded((all) => {
      const next = new Set(all);
      if (!next.delete(path)) next.add(path);
      return next;
    });
  }

  function uploadHere(files: File[]) {
    for (const file of files) {
      const key = crypto.randomUUID();
      setTransfers((all) => [...all, { key, name: file.name, progress: 0 }]);
      const path = target ? `${target}/${file.name}` : file.name;
      const transfer = upload(conversationId, file, (progress) => setTransfers((all) => all.map((item) => (item.key === key ? { ...item, progress } : item))), path);
      transfer.done
        .then(async () => {
          if (target) setExpanded((all) => new Set(all).add(target));
          await changed();
        }, failed)
        .finally(() => setTransfers((all) => all.filter((item) => item.key !== key)));
    }
  }

  async function run(action: () => Promise<unknown>, after?: () => void) {
    setAsking(null);
    try {
      await action();
      after?.();
    } catch (error) {
      failed(error);
    }
    await changed();
  }

  const quota = summary.data;
  const percent = quota ? Math.min(100, Math.round((quota.size / Math.max(1, quota.quota)) * 100)) : 0;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-none flex-wrap items-center gap-1 border-b border-line px-3 pb-2">
        <ToolButton label={t("files.upload")} onClick={() => picker.current?.click()}>
          <Upload className="size-4" aria-hidden="true" />
        </ToolButton>
        <input
          ref={picker}
          type="file"
          multiple
          hidden
          aria-label={t("files.upload")}
          onChange={(event) => {
            if (event.target.files) uploadHere([...event.target.files]);
            event.target.value = "";
          }}
        />
        <ToolButton label={t("files.newFolder")} onClick={() => setAsking({ kind: "folder", in: target })}>
          <FolderPlus className="size-4" aria-hidden="true" />
        </ToolButton>
        <ToolButton label={t("files.reset")} onClick={() => setAsking({ kind: "reset" })}>
          <RotateCcw className="size-4" aria-hidden="true" />
        </ToolButton>
        <span className="flex-1" />
        <label className="flex items-center gap-1.5 text-[13px] text-muted">
          <input type="checkbox" checked={hidden} onChange={(event) => setHidden(event.target.checked)} className="accent-accent" />
          {t("files.showHidden")}
        </label>
      </div>
      {transfers.length > 0 && (
        <ul aria-label={t("files.uploads")} className="flex-none border-b border-line px-4 py-1.5 text-[13px] text-muted">
          {transfers.map((item) => (
            <li key={item.key} className="truncate">
              {t("files.uploadingName", { name: item.name, percent: Math.round(item.progress * 100) })}
            </li>
          ))}
        </ul>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <Tree conversationId={conversationId} hidden={hidden} expanded={expanded} selected={selected} onToggle={toggle} onSelect={setSelected} />
        {entry !== null && (
          <section aria-label={t("files.preview")} className="border-t border-line px-4 py-3">
            <div className="mb-2 flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold">{entry.name}</p>
                <p className="text-[12.5px] text-muted">
                  {entry.type === "file" ? `${formatSize(entry.size)} · ` : ""}
                  {new Date(entry.modified).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
                </p>
              </div>
              {entry.type !== "link" && (
                <ToolButton label={t("files.download")} onClick={() => download(entry.type === "folder" ? archiveUrl(conversationId, entry.path) : downloadUrl(conversationId, entry.path))}>
                  <Download className="size-4" aria-hidden="true" />
                </ToolButton>
              )}
              <ToolButton label={t("files.rename")} onClick={() => setAsking({ kind: "rename", entry })}>
                <Pencil className="size-4" aria-hidden="true" />
              </ToolButton>
              <ToolButton label={t("files.delete")} onClick={() => setAsking({ kind: "delete", entry })}>
                <Trash2 className="size-4" aria-hidden="true" />
              </ToolButton>
            </div>
            {entry.type === "file" && <FilePreview conversationId={conversationId} entry={entry} />}
            {entry.type === "link" && <p className="text-sm text-muted">{t("files.linkPreview")}</p>}
          </section>
        )}
      </div>
      {quota && (
        <div className="flex flex-none items-center gap-2 border-t border-line px-4 py-2.5 text-xs text-muted tabular-nums">
          <span className="flex-1">{t("files.quota", { used: formatSize(quota.size), quota: formatSize(quota.quota) })}</span>
          <span
            role="meter"
            aria-label={t("files.quotaLabel")}
            aria-valuemin={0}
            aria-valuemax={quota.quota}
            aria-valuenow={quota.size}
            aria-valuetext={t("files.quota", { used: formatSize(quota.size), quota: formatSize(quota.quota) })}
            className="h-1.5 w-20 overflow-hidden rounded-full bg-hover"
          >
            <span className={`block h-full rounded-full ${percent >= 90 ? "bg-danger" : "bg-accent"}`} style={{ width: `${Math.max(3, percent)}%` }} />
          </span>
        </div>
      )}
      <Dialog.Root open={asking !== null} onOpenChange={(open) => !open && setAsking(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-[60] bg-scrim" />
          {asking?.kind === "delete" || asking?.kind === "reset" ? (
            <Dialog.Content role="alertdialog" className="rise fixed top-1/2 left-1/2 z-[70] w-[min(92vw,26rem)] -translate-x-1/2 -translate-y-1/2 rounded-[20px] bg-raised p-[22px] text-fg shadow-soft">
              <Dialog.Title className="mb-2 text-lg font-bold tracking-tight">{asking.kind === "reset" ? t("files.resetTitle") : t("files.deleteTitle", { name: asking.entry.name })}</Dialog.Title>
              <Dialog.Description className="text-muted">
                {asking.kind === "reset" ? t("files.resetBody") : asking.entry.type === "folder" ? t("files.deleteFolderBody", { name: asking.entry.name }) : t("files.deleteBody", { name: asking.entry.name })}
              </Dialog.Description>
              <div className="mt-[18px] flex flex-wrap justify-end gap-2">
                <Dialog.Close className="h-[38px] rounded-[10px] border border-line-strong bg-surface px-4 text-sm font-semibold hover:bg-hover">{t("files.cancel")}</Dialog.Close>
                <button
                  type="button"
                  className="h-[38px] rounded-[10px] bg-danger px-4 text-sm font-semibold text-on-danger"
                  onClick={() =>
                    asking.kind === "reset"
                      ? void run(() => resetWorkspace(conversationId), () => setSelected(null))
                      : void run(() => deleteEntry(conversationId, asking.entry.path), () => setSelected(null))
                  }
                >
                  {asking.kind === "reset" ? t("files.resetConfirm") : t("files.delete")}
                </button>
              </div>
            </Dialog.Content>
          ) : asking !== null ? (
            <Dialog.Content aria-describedby={undefined} className="rise fixed top-1/2 left-1/2 z-[70] w-[min(92vw,26rem)] -translate-x-1/2 -translate-y-1/2 rounded-[20px] bg-raised p-[22px] text-fg shadow-soft">
              <PathForm
                title={asking.kind === "rename" ? t("files.renameTitle") : t("files.newFolder")}
                label={t("files.pathLabel")}
                initial={asking.kind === "rename" ? asking.entry.path : asking.kind === "folder" && asking.in ? `${asking.in}/` : ""}
                confirm={asking.kind === "rename" ? t("files.renameConfirm") : t("files.create")}
                onSubmit={(path) =>
                  asking.kind === "rename"
                    ? void run(() => moveEntry(conversationId, asking.entry.path, path), () => setSelected(path))
                    : void run(() => createFolder(conversationId, path), () => setExpanded((all) => new Set(all).add(parentOf(path))))
                }
              />
            </Dialog.Content>
          ) : null}
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}

function PathForm(props: { title: string; label: string; initial: string; confirm: string; onSubmit: (path: string) => void }) {
  const { t } = useTranslation();
  const field = useId();
  return (
    <form
      onSubmit={(event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const path = String(new FormData(event.currentTarget).get("path") ?? "")
          .trim()
          .replace(/^\/+|\/+$/g, "");
        if (path) props.onSubmit(path);
      }}
    >
      <Dialog.Title className="mb-3 text-lg font-bold tracking-tight">{props.title}</Dialog.Title>
      <label htmlFor={field} className="mb-1 block text-sm text-muted">
        {props.label}
      </label>
      <input id={field} name="path" defaultValue={props.initial} autoFocus className="h-10 w-full rounded-[10px] border border-line-strong bg-surface px-3 font-mono text-sm outline-none focus:border-accent" />
      <div className="mt-[18px] flex flex-wrap justify-end gap-2">
        <Dialog.Close type="button" className="h-[38px] rounded-[10px] border border-line-strong bg-surface px-4 text-sm font-semibold hover:bg-hover">
          {t("files.cancel")}
        </Dialog.Close>
        <button type="submit" className="h-[38px] rounded-[10px] bg-fg px-4 text-sm font-semibold text-bg">
          {props.confirm}
        </button>
      </div>
    </form>
  );
}

function ToolButton(props: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" onClick={props.onClick} className="grid size-8 flex-none place-items-center rounded-lg text-muted hover:bg-hover hover:text-fg" aria-label={props.label} title={props.label}>
      {props.children}
    </button>
  );
}

interface TreeProps {
  conversationId: string;
  hidden: boolean;
  expanded: Set<string>;
  selected: string | null;
  onToggle: (path: string) => void;
  onSelect: (path: string) => void;
}

/** The workspace as a tree: folders load their entries when opened; arrows move between entries. */
function Tree(props: TreeProps) {
  const { t } = useTranslation();
  const root = useFolder(props.conversationId, "");
  const tree = useRef<HTMLUListElement>(null);
  const entries = (root.data ?? []).filter((entry) => props.hidden || !entry.name.startsWith("."));
  // The entry reached with Tab: the chosen one, or else the first.
  const focusable = props.selected ?? entries[0]?.path ?? null;

  function keyDown(event: KeyboardEvent<HTMLUListElement>) {
    const items = [...(tree.current?.querySelectorAll<HTMLElement>('[role="treeitem"]') ?? [])];
    const current = (event.target as HTMLElement).closest<HTMLElement>('[role="treeitem"]');
    const index = current === null ? -1 : items.indexOf(current);
    if (current === null || index === -1) return;
    const path = current.dataset.path ?? "";
    const isFolder = current.getAttribute("aria-expanded") !== null;
    const open = current.getAttribute("aria-expanded") === "true";
    const move = (to: HTMLElement | undefined) => {
      if (to === undefined) return;
      event.preventDefault();
      to.focus();
    };
    switch (event.key) {
      case "ArrowDown":
        move(items[index + 1]);
        break;
      case "ArrowUp":
        move(items[index - 1]);
        break;
      case "Home":
        move(items[0]);
        break;
      case "End":
        move(items.at(-1));
        break;
      case "ArrowRight":
        event.preventDefault();
        if (isFolder && !open) props.onToggle(path);
        else if (open) move(items[index + 1]);
        break;
      case "ArrowLeft":
        event.preventDefault();
        if (open) props.onToggle(path);
        else move(current.parentElement?.parentElement?.closest("li")?.querySelector<HTMLElement>(':scope > [role="treeitem"]') ?? undefined);
        break;
      case "Enter":
      case " ":
        event.preventDefault();
        props.onSelect(path);
        if (isFolder) props.onToggle(path);
        break;
    }
  }

  return (
    <>
      <ul ref={tree} role="tree" aria-label={t("files.workspace")} onKeyDown={keyDown} className="min-h-16 px-2 py-2">
        {entries.map((entry) => (
          <TreeItem key={entry.path} {...props} entry={entry} level={1} focusable={focusable} />
        ))}
      </ul>
      {root.isSuccess && entries.length === 0 && <p className="-mt-12 px-4 pb-6 text-sm text-muted">{t("files.empty")}</p>}
      {root.isError && <p className="-mt-12 px-4 pb-6 text-sm text-danger">{t("files.errors.sandbox_unavailable")}</p>}
    </>
  );
}

function TreeItem(props: TreeProps & { entry: WorkspaceEntry; level: number; focusable: string | null }) {
  const { entry, level } = props;
  const folder = entry.type === "folder";
  const open = folder && props.expanded.has(entry.path);
  const children = useFolder(props.conversationId, entry.path, open);
  const shown = (children.data ?? []).filter((child) => props.hidden || !child.name.startsWith("."));
  const chosen = props.selected === entry.path;
  const Icon = folder ? Folder : entry.type === "link" ? Link2 : File;
  // The row is the treeitem, named by its own content; the folder's group sits beside it.
  return (
    <li role="none">
      <div
        role="treeitem"
        aria-level={level}
        aria-selected={chosen}
        aria-expanded={folder ? open : undefined}
        data-path={entry.path}
        tabIndex={props.focusable === entry.path ? 0 : -1}
        onClick={() => {
          props.onSelect(entry.path);
          if (folder) props.onToggle(entry.path);
        }}
        className={`flex cursor-pointer items-center gap-1.5 rounded-lg py-1.5 pr-2 text-sm outline-none focus-visible:outline-2 focus-visible:outline-accent ${chosen ? "bg-accent-soft" : "hover:bg-hover"}`}
        style={{ paddingLeft: `${(level - 1) * 16 + 6}px` }}
      >
        <ChevronRight className={`size-3.5 flex-none text-muted transition-transform ${folder ? "" : "invisible"} ${open ? "rotate-90" : ""}`} aria-hidden="true" />
        <Icon className="size-4 flex-none text-muted" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate">{entry.name}</span>
        {entry.type === "file" && <span className="flex-none text-xs text-muted tabular-nums">{formatSize(entry.size)}</span>}
      </div>
      {open && (
        <ul role="group">
          {shown.map((child) => (
            <TreeItem key={child.path} {...props} entry={child} level={level + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

/** A file shown as what it is, never run in the app: text as text, media in the browser's own players (UX-020). */
function FilePreview({ conversationId, entry }: { conversationId: string; entry: WorkspaceEntry }) {
  const { t } = useTranslation();
  const kind = previewKind(entry.name);
  const textual = kind === "text" || kind === "markdown" || kind === "csv";
  const content = useQuery({
    queryKey: [...workspaceKey(conversationId), "preview", entry.path, entry.modified],
    queryFn: async () => {
      const response = await fetch(previewUrl(conversationId, entry.path), { credentials: "same-origin" });
      if (!response.ok) throw new ApiError(response.status, "file.not_previewable");
      return response.text();
    },
    enabled: textual,
  });
  const source = previewUrl(conversationId, entry.path);
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [entry.path, entry.modified]);

  if (kind === "none" || broken || content.isError) return <p className="text-sm text-muted">{t("files.noPreview")}</p>;
  if (kind === "image") return <img src={source} alt={entry.name} onError={() => setBroken(true)} className="max-h-[60vh] max-w-full rounded-lg border border-line bg-surface object-contain" />;
  if (kind === "pdf") return <iframe src={source} title={entry.name} className="h-[60vh] w-full rounded-lg border border-line bg-surface" />;
  if (kind === "audio") return <audio src={source} controls className="w-full" aria-label={entry.name} onError={() => setBroken(true)} />;
  if (kind === "video") return <video src={source} controls className="max-h-[60vh] w-full rounded-lg" aria-label={entry.name} onError={() => setBroken(true)} />;
  if (content.data === undefined) return <p className="text-sm text-muted">{t("files.loading")}</p>;
  const cut = entry.size > TEXT_PREVIEW_BYTES && <p className="mt-2 text-xs text-muted">{t("files.cut")}</p>;
  if (kind === "markdown") {
    return (
      <div className="text-[14.5px]">
        <Markdown text={content.data} />
        {cut}
      </div>
    );
  }
  if (kind === "csv") {
    const rows = parseCsv(content.data, CSV_ROWS);
    const [head, ...body] = rows;
    return (
      <div className="overflow-x-auto">
        <table className="text-[12.5px]">
          {head && (
            <thead>
              <tr>
                {head.map((cell, index) => (
                  <th key={index} className="border border-line bg-hover px-2 py-1 text-left font-semibold whitespace-nowrap">
                    {cell}
                  </th>
                ))}
              </tr>
            </thead>
          )}
          <tbody>
            {body.map((row, index) => (
              <tr key={index}>
                {row.map((cell, column) => (
                  <td key={column} className="border border-line px-2 py-1 whitespace-nowrap">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {cut}
      </div>
    );
  }
  return (
    <>
      <pre tabIndex={0} className="max-h-[60vh] overflow-auto rounded-lg bg-hover p-2.5 font-mono text-[12.5px] whitespace-pre-wrap break-words">
        {content.data}
      </pre>
      {cut}
    </>
  );
}

/** The first rows of a CSV text, with quoted fields. */
export function parseCsv(text: string, limit: number): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length && rows.length < limit; index++) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') {
        field += '"';
        index++;
      } else if (char === '"') quoted = false;
      else field += char;
    } else if (char === '"') quoted = true;
    else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[index + 1] === "\n") index++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else field += char;
  }
  if ((field || row.length > 0) && rows.length < limit) rows.push([...row, field]);
  return rows;
}
