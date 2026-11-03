import { LogOut, Menu as MenuIcon, Plus, SlidersHorizontal, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet, useLocation } from "react-router";

import type { Conversation, User } from "../api/client";
import { useConversations } from "../conversations";
import { useSignOut } from "../session";
import { ConversationMenu } from "./ConversationMenu";
import { Sprite } from "./Sprite";

const DAY = 24 * 60 * 60 * 1000;

/** Conversations by how recently they changed: today, yesterday, the past week, older. */
function grouped(conversations: Conversation[]): [string, Conversation[]][] {
  const midnight = new Date();
  midnight.setHours(0, 0, 0, 0);
  const groups = new Map<string, Conversation[]>();
  for (const conversation of conversations) {
    const updated = new Date(conversation.updated_at).getTime();
    const key =
      updated >= midnight.getTime()
        ? "today"
        : updated >= midnight.getTime() - DAY
          ? "yesterday"
          : updated >= midnight.getTime() - 7 * DAY
            ? "week"
            : "older";
    groups.set(key, [...(groups.get(key) ?? []), conversation]);
  }
  return [...groups.entries()];
}

/** The conversation list beside the conversation; on phones the list slides over it. */
export function Shell({ me }: { me: User }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const conversations = useConversations();
  const signOut = useSignOut();
  const location = useLocation();
  // Close the list on phones after choosing a conversation.
  const [shownFor, setShownFor] = useState(location.pathname);
  if (shownFor !== location.pathname) {
    setShownFor(location.pathname);
    setOpen(false);
  }
  const groupName = (key: string) =>
    key === "today" ? t("shell.today") : key === "yesterday" ? t("shell.yesterday") : key === "week" ? t("shell.week") : t("shell.older");

  return (
    <div className="flex h-full bg-bg text-fg">
      {open && <div className="fixed inset-0 z-30 bg-scrim md:hidden" aria-hidden="true" onClick={() => setOpen(false)} />}
      <nav
        aria-label={t("shell.conversations")}
        className={`${open ? "flex" : "hidden"} fixed inset-y-0 left-0 z-40 w-[min(19rem,86vw)] flex-col gap-1.5 border-r border-line bg-panel px-2.5 pt-[calc(0.75rem+env(safe-area-inset-top))] pb-[calc(0.625rem+env(safe-area-inset-bottom))] shadow-soft md:static md:flex md:w-[268px] md:shadow-none`}
      >
        <div className="flex items-center gap-1.5 px-1 pb-2">
          <Link to="/" className="flex flex-1 items-center gap-2 rounded-lg p-1 text-base font-bold tracking-tight">
            <Sprite pose="waiting" head className="size-7" />
            {t("app.name")}
          </Link>
          <button type="button" onClick={() => setOpen(false)} className="grid size-9 place-items-center rounded-lg text-muted hover:bg-hover md:hidden" aria-label={t("shell.closeMenu")}>
            <X className="size-5" aria-hidden="true" />
          </button>
        </div>
        <Link to="/" className="flex items-center gap-2.5 rounded-xl px-2.5 py-2 font-semibold hover:bg-hover">
          <span className="grid size-[26px] place-items-center rounded-full bg-accent text-on-accent" aria-hidden="true">
            <Plus className="size-4" strokeWidth={2.6} />
          </span>
          {t("shell.newChat")}
        </Link>
        <div className="mt-1.5 min-h-0 flex-1 overflow-y-auto">
          {conversations.data?.length === 0 && <p className="px-2.5 py-2 text-sm text-muted">{t("shell.empty")}</p>}
          {grouped(conversations.data ?? []).map(([key, items]) => (
            <section key={key}>
              <h2 className="mx-2.5 mt-3.5 mb-1 text-xs font-semibold text-faint">{groupName(key)}</h2>
              <ul>
                {items.map((conversation) => (
                  <li key={conversation.id} className="group flex items-center rounded-[9px] hover:bg-hover">
                    <NavLink
                      to={`/c/${conversation.id}`}
                      className={({ isActive }) => `min-w-0 flex-1 truncate rounded-[9px] px-2.5 py-[7px] text-sm ${isActive ? "bg-hover font-semibold" : ""}`}
                    >
                      {conversation.title || t("shell.untitled")}
                    </NavLink>
                    <ConversationMenu conversation={conversation} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
        <div className="flex flex-col gap-0.5 border-t border-line pt-2">
          <Link to="/settings" className="flex items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-sm hover:bg-hover">
            <SlidersHorizontal className="size-[18px]" aria-hidden="true" />
            {t("shell.settings")}
          </Link>
          <div className="flex items-center gap-2.5 py-1.5 pr-1 pl-2.5">
            <span className="grid size-[30px] flex-none place-items-center rounded-full bg-accent-soft text-[13px] font-bold text-accent" aria-hidden="true">
              {me.display_name.slice(0, 1).toUpperCase()}
            </span>
            <span className="min-w-0 flex-1 truncate text-sm font-semibold">{me.display_name}</span>
            <button type="button" onClick={() => void signOut()} className="grid size-9 place-items-center rounded-lg text-muted hover:bg-hover hover:text-fg" aria-label={t("shell.signOut")} title={t("shell.signOut")}>
              <LogOut className="size-[18px]" aria-hidden="true" />
            </button>
          </div>
        </div>
      </nav>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-[52px] flex-none items-center gap-1.5 pr-4 pl-[max(0.5rem,env(safe-area-inset-left))] md:hidden">
          <button type="button" onClick={() => setOpen(true)} className="grid size-9 place-items-center rounded-lg text-muted hover:bg-hover" aria-label={t("shell.openMenu")} aria-expanded={open}>
            <MenuIcon className="size-5" aria-hidden="true" />
          </button>
          <span className="flex-1 font-semibold">{t("app.name")}</span>
        </header>
        <main className="flex min-h-0 flex-1 flex-col">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
