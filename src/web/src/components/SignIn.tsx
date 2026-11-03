import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { ME } from "../session";

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
    <main className="flex min-h-full items-center justify-center p-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4" aria-describedby={error ? "sign-in-error" : undefined}>
        <h1 className="text-2xl font-semibold">{t("signIn.title")}</h1>
        <label className="block">
          <span className="mb-1 block text-sm font-medium">{t("signIn.username")}</span>
          <input name="username" autoComplete="username" required autoCapitalize="none" className="w-full rounded-lg border border-stone-400 bg-white px-3 py-2 text-base text-stone-900" />
        </label>
        <label className="block">
          <span className="mb-1 block text-sm font-medium">{t("signIn.password")}</span>
          <input name="password" type="password" autoComplete="current-password" required className="w-full rounded-lg border border-stone-400 bg-white px-3 py-2 text-base text-stone-900" />
        </label>
        {error && (
          <p id="sign-in-error" role="alert" className="text-sm text-red-800">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy} className="w-full rounded-lg bg-stone-800 px-4 py-2 font-medium text-white disabled:opacity-60">
          {busy ? t("signIn.submitting") : t("signIn.submit")}
        </button>
      </form>
    </main>
  );
}
