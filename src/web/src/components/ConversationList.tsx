import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Folder as FolderIcon, FolderPlus, Search } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router";

import { api, unwrap, type Conversation, type Folder, type ListEntry } from "../api/client";
import { CONVERSATIONS, createFolder, updateFolder, useConversationList } from "../conversations";
import { ConversationMenu } from "./ConversationMenu";

/** Folders and conversations, pinned first, then newest; a search over them all (CNV-007 to CNV-009). */
export function ConversationList() {
  const { t } = useTranslation();
  const list = useConversationList();
  const [query, setQuery] = useState("");
  const [naming, setNaming] = useState(false);
  const entries = list.data ?? [];
  const folders = entries.flatMap((entry) => (entry.kind === "folder" ? [entry.folder] : []));
  const isPinned = (entry: ListEntry) => (entry.kind === "folder" ? entry.folder.pinned : entry.conversation.pinned);
  const pinned = entries.filter(isPinned);
  const others = entries.filter((entry) => !isPinned(entry));

  return (
    <>
      <div className="mt-1 flex items-center gap-1 px-1">
        <label className="flex min-w-0 flex-1 items-center gap-2 rounded-[10px] bg-hover px-2.5 py-1.5 focus-within:ring-2 focus-within:ring-accent">
          <Search className="size-4 flex-none text-muted" aria-hidden="true" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label={t("shell.search")}
            placeholder={t("shell.searchPlaceholder")}
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-faint"
          />
        </label>
        <button type="button" onClick={() => setNaming(true)} className="grid size-9 flex-none place-items-center rounded-lg text-muted hover:bg-hover hover:text-fg" aria-label={t("shell.newFolder")} title={t("shell.newFolder")}>
          <FolderPlus className="size-[18px]" aria-hidden="true" />
        </button>
      </div>
      <div className="mt-1 min-h-0 flex-1 overflow-y-auto">
        {query.trim() ? (
          <SearchResults query={query.trim()} />
        ) : (
          <>
            {entries.length === 0 && list.isSuccess && <p className="px-2.5 py-2 text-sm text-muted">{t("shell.empty")}</p>}
            {pinned.length > 0 && <Group title={t("shell.pinned")} entries={pinned} folders={folders} />}
            {others.length > 0 && <Group title={pinned.length > 0 ? t("shell.recent") : null} entries={others} folders={folders} />}
          </>
        )}
      </div>
      <NewFolder open={naming} onClose={() => setNaming(false)} />
    </>
  );
}

function Group({ title, entries, folders }: { title: string | null; entries: ListEntry[]; folders: Folder[] }) {
  return (
    <section>
      {title && <h2 className="mx-2.5 mt-3.5 mb-1 text-xs font-semibold text-faint">{title}</h2>}
      <ul className={title ? "" : "mt-2"}>
        {entries.map((entry) =>
          entry.kind === "folder" ? (
            <FolderItem key={entry.folder.id} folder={entry.folder} conversations={entry.conversations} folders={folders} />
          ) : (
            <ConversationItem key={entry.conversation.id} conversation={entry.conversation} folders={folders} />
          ),
        )}
      </ul>
    </section>
  );
}

function ConversationItem({ conversation, folders, nested = false }: { conversation: Conversation; folders: Folder[]; nested?: boolean }) {
  const { t } = useTranslation();
  return (
    <li className="group flex items-center rounded-[9px] hover:bg-hover">
      <NavLink
        to={`/c/${conversation.id}`}
        className={({ isActive }) => `min-w-0 flex-1 truncate rounded-[9px] py-[7px] pr-2.5 text-sm ${nested ? "pl-8" : "pl-2.5"} ${isActive ? "bg-hover font-semibold" : ""}`}
      >
        {conversation.title || t("shell.untitled")}
      </NavLink>
      <ConversationMenu conversation={conversation} folders={folders} />
    </li>
  );
}

/** A folder: it collapses and expands, and remembers which on every device (CNV-008). */
function FolderItem({ folder, conversations, folders }: { folder: Folder; conversations: Conversation[]; folders: Folder[] }) {
  const queries = useQueryClient();
  const expanded = !folder.collapsed;
  async function toggle() {
    await updateFolder(folder.id, { collapsed: expanded });
    await queries.invalidateQueries({ queryKey: CONVERSATIONS });
  }
  return (
    <li>
      <button type="button" onClick={() => void toggle()} aria-expanded={expanded} className="flex w-full items-center gap-2 rounded-[9px] px-2.5 py-[7px] text-left text-sm font-medium hover:bg-hover">
        <ChevronRight className={`size-4 flex-none text-muted transition-transform ${expanded ? "rotate-90" : ""}`} aria-hidden="true" />
        <FolderIcon className="size-4 flex-none text-muted" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate">{folder.name}</span>
      </button>
      {expanded && (
        <ul>
          {conversations.map((conversation) => (
            <ConversationItem key={conversation.id} conversation={conversation} folders={folders} nested />
          ))}
        </ul>
      )}
    </li>
  );
}

function SearchResults({ query }: { query: string }) {
  const { t } = useTranslation();
  const results = useQuery({
    queryKey: ["search", query],
    queryFn: async () => unwrap(await api.GET("/search", { params: { query: { q: query } } })).items,
  });
  if (results.data?.length === 0) return <p className="px-2.5 py-2 text-sm text-muted">{t("shell.noResults")}</p>;
  return (
    <ul aria-label={t("shell.results")} className="mt-1 flex flex-col gap-0.5">
      {results.data?.map((result) => (
        <li key={result.conversation_id}>
          <NavLink to={`/c/${result.conversation_id}`} className="block rounded-[9px] px-2.5 py-2 hover:bg-hover">
            <span className="block truncate text-sm font-semibold">{result.title || t("shell.untitled")}</span>
            <span className="line-clamp-2 text-[12.5px] text-muted">{result.snippet}</span>
          </NavLink>
        </li>
      ))}
    </ul>
  );
}

function NewFolder({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("name") ?? "").trim();
    if (!name) return;
    await createFolder(name);
    await queries.invalidateQueries({ queryKey: CONVERSATIONS });
    onClose();
  }
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content className="rise fixed top-1/2 left-1/2 z-50 w-[min(92vw,26rem)] -translate-x-1/2 -translate-y-1/2 rounded-[20px] bg-raised p-[22px] text-fg shadow-soft">
          <form onSubmit={(event) => void submit(event)} className="flex flex-col gap-4">
            <Dialog.Title className="text-lg font-bold">{t("shell.newFolder")}</Dialog.Title>
            <Dialog.Description className="sr-only">{t("shell.folderName")}</Dialog.Description>
            <label className="flex flex-col gap-1.5">
              <span className="text-[13.5px] font-semibold">{t("shell.folderName")}</span>
              <input name="name" required maxLength={100} autoFocus className="h-10 w-full rounded-[10px] border border-line-strong bg-bg px-3 outline-none focus:border-accent" />
            </label>
            <div className="flex justify-end gap-2">
              <Dialog.Close className="h-[38px] rounded-[10px] border border-line-strong px-4 text-sm font-semibold hover:bg-hover">{t("conversationMenu.cancel")}</Dialog.Close>
              <button type="submit" className="h-[38px] rounded-[10px] bg-fg px-4 text-sm font-semibold text-bg">
                {t("shell.createFolder")}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
