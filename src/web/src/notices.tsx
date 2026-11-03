// Notices: errors say what went wrong and what to do, with the sprite holding a sign (UX-014, ADR-0070).
import { X } from "lucide-react";
import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Sprite } from "./components/Sprite";

export interface Notice {
  kind: "error" | "info";
  title: string;
  text?: string;
  action?: { label: string; run: () => void };
}

interface Shown extends Notice {
  id: number;
}

const Notices = createContext<(notice: Notice) => void>(() => undefined);

export function useNotify(): (notice: Notice) => void {
  return useContext(Notices);
}

const INFO_SECONDS = 2.6;

export function NoticeProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [shown, setShown] = useState<Shown[]>([]);
  const dismiss = useCallback((id: number) => setShown((all) => all.filter((notice) => notice.id !== id)), []);
  const notify = useCallback(
    (notice: Notice) => {
      const id = Date.now() + Math.random();
      setShown((all) => [...all.filter((other) => other.kind !== notice.kind || other.title !== notice.title), { ...notice, id }]);
      if (notice.kind === "info") window.setTimeout(() => dismiss(id), INFO_SECONDS * 1000);
    },
    [dismiss],
  );
  const value = useMemo(() => notify, [notify]);
  return (
    <Notices.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed top-[calc(4rem+env(safe-area-inset-top))] left-1/2 z-[60] flex w-[min(34rem,calc(100vw-2rem))] -translate-x-1/2 flex-col gap-2">
        {shown.map((notice) => (
          <div
            key={notice.id}
            role={notice.kind === "error" ? "alert" : "status"}
            className={`rise pointer-events-auto flex items-center gap-3 rounded-2xl border bg-raised py-2.5 pr-2.5 shadow-soft ${
              notice.kind === "error" ? "border-danger/45 pl-2" : "border-line pl-4"
            }`}
          >
            {notice.kind === "error" && <Sprite pose="error" className="h-[67px] w-[58px] flex-none" />}
            <div className="min-w-0 flex-1 text-sm">
              <strong className="block">{notice.title}</strong>
              {notice.text && <p className="mt-0.5 text-muted">{notice.text}</p>}
              {notice.action && (
                <button
                  type="button"
                  className="mt-2 rounded-lg border border-line-strong px-3 py-1 text-[13px] font-semibold hover:bg-hover"
                  onClick={() => {
                    notice.action?.run();
                    dismiss(notice.id);
                  }}
                >
                  {notice.action.label}
                </button>
              )}
            </div>
            <button type="button" className="grid size-8 flex-none place-items-center rounded-lg text-muted hover:bg-hover" aria-label={t("errors.dismiss")} onClick={() => dismiss(notice.id)}>
              <X className="size-4" aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </Notices.Provider>
  );
}
