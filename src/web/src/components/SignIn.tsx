import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { hasKeyboard } from "../focus";
import { ME } from "../session";
import { Sprite } from "./Sprite";

const INPUT = "h-[42px] w-full rounded-[10px] border border-line-strong bg-surface px-3 text-base outline-none focus:border-accent";

/** Sign in with a cookie session: the token never reaches the page's scripts (AUTH-005). */
export function SignIn() {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    const result = await api.POST("/auth/login", {
      body: {
        username: String(form.get("username") ?? ""),
        password: String(form.get("password") ?? ""),
        device_name: navigator.userAgent.slice(0, 100) || "browser",
        session_delivery: "cookie",
      },
    });
    setBusy(false);
    if (result.data !== undefined) {
      queries.setQueryData(ME, result.data.user);
      return;
    }
    const status = result.response.status;
    setError(t(status === 401 ? "signIn.invalid" : status === 429 ? "signIn.rateLimited" : "signIn.failed"));
  }

  return (
    <main className="flex min-h-full overflow-y-auto bg-bg px-4 py-6 text-fg">
      <div className="m-auto flex w-full max-w-[360px] flex-col items-center gap-1">
        <Sprite pose="waiting" className="h-[106px] w-[92px]" />
        <h1 className="mt-1.5 text-center text-2xl font-bold tracking-tight">{t("signIn.title")}</h1>
        <p className="mb-[18px] text-center text-muted">{t("signIn.subtitle")}</p>
        <form onSubmit={submit} className="flex w-full flex-col gap-3.5" aria-describedby={error ? "sign-in-error" : undefined}>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13.5px] font-semibold">{t("signIn.username")}</span>
            <input name="username" autoComplete="username" required autoCapitalize="none" autoFocus={hasKeyboard()} className={INPUT} />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13.5px] font-semibold">{t("signIn.password")}</span>
            <input name="password" type="password" autoComplete="current-password" required className={INPUT} />
          </label>
          {error && (
            <p id="sign-in-error" role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
          <button type="submit" disabled={busy} className="h-[42px] w-full rounded-[10px] bg-fg font-semibold text-bg disabled:opacity-60">
            {busy ? t("signIn.submitting") : t("signIn.submit")}
          </button>
        </form>
      </div>
    </main>
  );
}
