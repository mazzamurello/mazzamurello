// Approval requests, in place of the message box until the user answers them (UX-022, AGT-007, ADR-0090).
import { ShieldAlert } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ApprovalScope, Interrupt } from "../api/client";
import type { ResumeEntry } from "../api/stream";
import { toolLabel } from "../tools";

const BUTTON = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] border border-line-strong bg-surface px-4 text-sm font-semibold hover:bg-hover disabled:opacity-50";
const SCOPE_ORDER: ApprovalScope[] = ["once", "turn", "conversation"];

/** The time left before a request is denied, in words. */
function useTimeLeft(expiresAt: string | undefined): string | null {
  const { t } = useTranslation();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  if (!expiresAt) return null;
  const minutes = Math.max(0, Math.round((Date.parse(expiresAt) - now) / 60_000));
  return minutes >= 60 ? t("approvals.deniedInHours", { count: Math.round(minutes / 60) }) : t("approvals.deniedInMinutes", { count: minutes });
}

/** One approval request: what the call does, with what and where, and why it asks. */
function Request({ interrupt }: { interrupt: Interrupt }) {
  const { t } = useTranslation();
  const request = interrupt.metadata?.approval;
  const timeLeft = useTimeLeft(interrupt.expiresAt);
  if (!request) return null;
  return (
    <div className="flex flex-col gap-2 text-sm">
      <p className="text-[15px] font-semibold text-pretty">
        {toolLabel(t, request.tool)} <code className="font-mono text-[13px] font-normal text-muted">{request.tool}</code>
      </p>
      <p className="text-pretty">{request.action}</p>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
        <dt className="font-semibold text-muted">{t("approvals.data")}</dt>
        <dd className="font-mono text-[13px] break-words whitespace-pre-wrap">{request.data}</dd>
        <dt className="font-semibold text-muted">{t("approvals.destination")}</dt>
        <dd className="break-words">{request.destination}</dd>
      </dl>
      <p className="rounded-[10px] bg-hover px-3 py-2 text-pretty">{t(`approvals.reasons.${request.reason}`)}</p>
      {/* The arguments in full, as the model gave them (UX-003, AGT-007). */}
      <p className="text-[13px] font-semibold text-muted">{t("approvals.arguments")}</p>
      <pre className="max-h-40 overflow-auto rounded-lg bg-hover p-2 font-mono text-[12.5px] whitespace-pre-wrap">{JSON.stringify(request.arguments, null, 2)}</pre>
      {timeLeft && <p className="text-[13px] text-muted">{timeLeft}</p>}
    </div>
  );
}

/** The pending approval requests, one at a time: Deny first, never chosen for the user (UX-022). */
export function ApprovalCard({ interrupts, onDecided }: { interrupts: Interrupt[]; onDecided: (resume: ResumeEntry[]) => void }) {
  const { t } = useTranslation();
  const heading = useId();
  const [decisions, setDecisions] = useState<ResumeEntry[]>([]);
  const current = interrupts[decisions.length];
  if (!current) return null;
  const scopes = SCOPE_ORDER.filter((scope) => current.metadata?.approval?.scopes.includes(scope));

  function decide(entry: ResumeEntry) {
    const all = [...decisions, entry];
    if (all.length >= interrupts.length) onDecided(all);
    else setDecisions(all);
  }

  return (
    <section aria-labelledby={heading} className="flex max-h-[min(70dvh,38rem)] flex-col rounded-[20px] border border-line-strong bg-surface shadow-soft">
      <div className="flex flex-none items-center gap-2 px-4 pt-3.5 pb-2">
        <h2 id={heading} className="flex flex-1 items-center gap-2 text-sm font-bold text-muted">
          <ShieldAlert className="size-4" aria-hidden="true" />
          {t("approvals.title")}
        </h2>
        {interrupts.length > 1 && (
          <span className="text-[13px] text-muted tabular-nums" aria-live="polite">
            {t("questions.counter", { number: decisions.length + 1, total: interrupts.length })}
          </span>
        )}
      </div>
      <div className="min-h-0 overflow-y-auto px-4 pb-2">
        <Request key={current.id} interrupt={current} />
      </div>
      <div className="flex flex-none flex-wrap justify-end gap-2 border-t border-line px-4 py-3">
        <button type="button" className={BUTTON} onClick={() => decide({ interruptId: current.id, status: "resolved", payload: { approved: false } })}>
          {t("approvals.deny")}
        </button>
        {scopes.map((scope) => (
          <button key={scope} type="button" className={BUTTON} onClick={() => decide({ interruptId: current.id, status: "resolved", payload: { approved: true, scope } })}>
            {t(`approvals.allow.${scope}`)}
          </button>
        ))}
      </div>
    </section>
  );
}
