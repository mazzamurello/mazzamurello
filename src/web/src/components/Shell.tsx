import { LogOut, Menu as MenuIcon, Plus, SlidersHorizontal, X } from "lucide-react";
import { type CSSProperties, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Outlet, useLocation } from "react-router";

import type { User } from "../api/client";
import { formatMoney, useUsage } from "../costs";
import { useSignOut } from "../session";
import { useLeavingTemporary } from "../temporary";
import { ConversationList } from "./ConversationList";
import { ResizeHandle, usePanelWidth } from "./ResizeHandle";
import { HandsFreeOverlay, VoiceProvider } from "../voice";
import { Sprite } from "./Sprite";

/** The conversation list beside the conversation; on phones the list slides over it. */
export function Shell({ me }: { me: User }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const list = usePanelWidth("sibillo.listWidth", 268, 220, 440);
  const signOut = useSignOut();
  const location = useLocation();
  useLeavingTemporary();
  // Close the list on phones after choosing a conversation.
  const [shownFor, setShownFor] = useState(location.pathname);
  if (shownFor !== location.pathname) {
    setShownFor(location.pathname);
    setOpen(false);
  }

  return (
    <VoiceProvider>
      <div className="flex h-full overflow-hidden bg-bg text-fg">
        {open && <div className="fixed inset-0 z-30 bg-scrim md:hidden" aria-hidden="true" onClick={() => setOpen(false)} />}
        <nav
          aria-label={t("shell.conversations")}
          style={{ "--list-width": `${list.width}px` } as CSSProperties}
          className={`${open ? "flex" : "hidden"} fixed inset-y-0 left-0 z-40 w-[min(19rem,86vw)] flex-col gap-1.5 border-r border-line bg-panel px-2.5 pt-[calc(0.75rem+env(safe-area-inset-top))] pb-[calc(0.625rem+env(safe-area-inset-bottom))] shadow-soft md:relative md:flex md:w-(--list-width) md:shadow-none`}
        >
          <ResizeHandle label={t("shell.resizeList")} side="right" panel={list} className="hidden md:block" />
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
          <ConversationList />
          <UsageSummary />
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
          <main className="relative flex min-h-0 flex-1 flex-col">
            <Outlet />
            <HandsFreeOverlay />
          </main>
        </div>
      </div>
    </VoiceProvider>
  );
}

/** The user's spend over the last 24 hours and 30 days (UX-008). */
function UsageSummary() {
  const { t } = useTranslation();
  const usage = useUsage();
  if (!usage.data) return null;
  const rows: [string, string][] = [
    [t("usage.day"), formatMoney(usage.data.last_24_hours)],
    [t("usage.month"), formatMoney(usage.data.last_30_days)],
  ];
  return (
    <dl className="mx-1 mb-1 grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 rounded-xl bg-hover px-3 py-2 text-[12.5px] tabular-nums">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted">{label}</dt>
          <dd className="text-right font-semibold">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
