import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet, useLocation } from "react-router";

import type { User } from "../api/client";
import { useConversations } from "../conversations";
import { useSignOut } from "../session";
import { ConversationMenu } from "./ConversationMenu";

/** The conversation list beside the conversation; on phones the list slides over it. */
export function Shell({ me }: { me: User }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const conversations = useConversations();
  const signOut = useSignOut();
  const location = useLocation();
  const admin = me.instance_admin || me.role === "tenant_admin";
  // Close the list on phones after choosing a conversation.
  const [shownFor, setShownFor] = useState(location.pathname);
  if (shownFor !== location.pathname) {
    setShownFor(location.pathname);
    setOpen(false);
  }

  return (
    <div className="flex h-full">
      {open && <div className="fixed inset-0 z-10 bg-black/30 md:hidden" aria-hidden="true" onClick={() => setOpen(false)} />}
      <nav
        aria-label={t("shell.conversations")}
        className={`${open ? "flex" : "hidden"} fixed inset-y-0 left-0 z-20 w-72 flex-col border-r border-stone-300 bg-stone-100 md:static md:flex dark:border-stone-700 dark:bg-stone-900`}
      >
        <div className="flex items-center gap-2 p-3">
          <Link to="/" className="flex-1 rounded-lg bg-stone-800 px-3 py-2 text-center font-medium text-white dark:bg-stone-200 dark:text-stone-900">
            {t("shell.newChat")}
          </Link>
          <button type="button" onClick={() => setOpen(false)} className="rounded-lg px-2 py-2 md:hidden" aria-label={t("shell.closeMenu")}>
            ✕
          </button>
        </div>
        <h2 className="px-4 pt-2 pb-1 text-xs font-semibold tracking-wide text-stone-600 uppercase dark:text-stone-300">{t("shell.conversations")}</h2>
        <ul className="flex-1 overflow-y-auto px-2">
          {conversations.data?.length === 0 && <li className="px-2 py-2 text-sm text-stone-600 dark:text-stone-300">{t("shell.empty")}</li>}
          {conversations.data?.map((conversation) => (
            <li key={conversation.id} className="group flex items-center rounded-lg hover:bg-stone-200 dark:hover:bg-stone-800">
              <NavLink
                to={`/c/${conversation.id}`}
                className={({ isActive }) => `flex-1 truncate px-2 py-2 text-sm ${isActive ? "font-semibold" : ""}`}
              >
                {conversation.title || t("shell.untitled")}
              </NavLink>
              <ConversationMenu conversation={conversation} />
            </li>
          ))}
        </ul>
        <div className="space-y-1 border-t border-stone-300 p-3 text-sm dark:border-stone-700">
          {admin && (
            <Link to="/settings/models" className="block rounded-lg px-2 py-2 hover:bg-stone-200 dark:hover:bg-stone-800">
              {t("shell.settings")}
            </Link>
          )}
          <button type="button" onClick={() => void signOut()} className="block w-full rounded-lg px-2 py-2 text-left hover:bg-stone-200 dark:hover:bg-stone-800">
            {t("shell.signOut")} <span className="text-stone-600 dark:text-stone-300">({me.display_name})</span>
          </button>
        </div>
      </nav>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-stone-300 p-2 md:hidden dark:border-stone-700">
          <button type="button" onClick={() => setOpen(true)} className="rounded-lg px-3 py-2" aria-label={t("shell.openMenu")} aria-expanded={open}>
            ☰
          </button>
          <span className="font-semibold">{t("app.name")}</span>
        </header>
        <main className="flex min-h-0 flex-1 flex-col">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
