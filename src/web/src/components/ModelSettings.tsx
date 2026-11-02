import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, api, unwrap, type ModelConfiguration, type User } from "../api/client";

type Scope = "instance" | "tenant";

/** Models configured by administrators, instead of with curl (MOD-008, ADR-0051). */
export function ModelSettings({ me }: { me: User }) {
  const { t } = useTranslation();
  const scopes: Scope[] = [];
  if (me.instance_admin) scopes.push("instance");
  if (me.role === "tenant_admin") scopes.push("tenant");
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl space-y-8 px-4 py-6">
        <h1 className="text-2xl font-semibold">{t("settings.title")}</h1>
        {scopes.length === 0 && <p>{t("settings.notAllowed")}</p>}
        {scopes.map((scope) => (
          <ScopeModels key={scope} scope={scope} />
        ))}
      </div>
    </div>
  );
}

async function listModels(scope: Scope): Promise<ModelConfiguration[]> {
  const result = scope === "instance" ? await api.GET("/instance/models") : await api.GET("/tenant/models");
  return unwrap(result).items;
}

function ScopeModels({ scope }: { scope: Scope }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const key = ["models", scope] as const;
  const models = useQuery({ queryKey: key, queryFn: () => listModels(scope) });
  const [editing, setEditing] = useState<ModelConfiguration | "new" | null>(null);
  const refresh = () => queries.invalidateQueries({ queryKey: key });
  const button = "rounded px-2 py-1 text-sm hover:bg-stone-200 dark:hover:bg-stone-700";

  async function change(id: string, body: { is_default?: boolean }) {
    const path = { params: { path: { model_id: id } }, body };
    unwrap(scope === "instance" ? await api.PATCH("/instance/models/{model_id}", path) : await api.PATCH("/tenant/models/{model_id}", path));
    await refresh();
  }

  async function remove(id: string) {
    const path = { params: { path: { model_id: id } } };
    const result = scope === "instance" ? await api.DELETE("/instance/models/{model_id}", path) : await api.DELETE("/tenant/models/{model_id}", path);
    if (!result.response.ok) unwrap(result);
    await refresh();
  }

  return (
    <section aria-labelledby={`models-${scope}`} className="space-y-3">
      <h2 id={`models-${scope}`} className="text-lg font-semibold">
        {t(scope === "instance" ? "settings.instance" : "settings.household")}
      </h2>
      {models.data?.length === 0 && <p className="text-stone-700 dark:text-stone-300">{t("settings.none")}</p>}
      <ul className="divide-y divide-stone-300 rounded-lg border border-stone-300 dark:divide-stone-600 dark:border-stone-600">
        {models.data?.map((model) => (
          <li key={model.id} className="flex flex-wrap items-center gap-2 p-3">
            <div className="min-w-0 flex-1">
              <p className="font-medium">
                {model.name} {model.is_default && <span className="ml-1 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-950">{t("settings.default")}</span>}
              </p>
              <p className="truncate text-sm text-stone-700 dark:text-stone-300">
                {model.model} · {model.base_url}
              </p>
            </div>
            {!model.is_default && (
              <button type="button" className={button} onClick={() => void change(model.id, { is_default: true })}>
                {t("settings.makeDefault")}
              </button>
            )}
            <button type="button" className={button} onClick={() => setEditing(model)}>
              {t("settings.edit")}
            </button>
            <button type="button" className={`${button} text-red-800 dark:text-red-300`} onClick={() => void remove(model.id)}>
              {t("settings.delete")}
            </button>
          </li>
        ))}
      </ul>
      {editing === null ? (
        <button type="button" className="rounded-lg bg-stone-800 px-3 py-2 text-white" onClick={() => setEditing("new")}>
          {t("settings.add")}
        </button>
      ) : (
        <ModelForm
          scope={scope}
          model={editing === "new" ? null : editing}
          onDone={async () => {
            setEditing(null);
            await refresh();
          }}
        />
      )}
    </section>
  );
}

function ModelForm({ scope, model, onDone }: { scope: Scope; model: ModelConfiguration | null; onDone: () => Promise<void> }) {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);
  const field = "w-full rounded-lg border border-stone-400 bg-white px-3 py-2 text-stone-900";
  const id = (name: string) => `${scope}-${model?.id ?? "new"}-${name}`;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const apiKey = String(form.get("api_key") ?? "");
    const values = {
      name: String(form.get("name") ?? ""),
      api: String(form.get("api") ?? "openai") as "openai" | "openrouter",
      base_url: String(form.get("base_url") ?? ""),
      model: String(form.get("model") ?? ""),
      paid: form.get("paid") === "on",
      ...(apiKey ? { api_key: apiKey } : {}),
    };
    try {
      if (model === null) {
        const body = { ...values, is_default: false };
        unwrap(scope === "instance" ? await api.POST("/instance/models", { body }) : await api.POST("/tenant/models", { body }));
      } else {
        const path = { params: { path: { model_id: model.id } }, body: values };
        unwrap(scope === "instance" ? await api.PATCH("/instance/models/{model_id}", path) : await api.PATCH("/tenant/models/{model_id}", path));
      }
      await onDone();
    } catch (failure) {
      setError(t("settings.failed", { code: failure instanceof ApiError ? failure.code : "internal.error" }));
    }
  }

  return (
    <form onSubmit={submit} className="grid gap-3 rounded-lg border border-stone-300 p-4 sm:grid-cols-2 dark:border-stone-600">
      <label htmlFor={id("name")} className="text-sm font-medium sm:col-span-2">
        {t("settings.name")}
        <input id={id("name")} name="name" required maxLength={100} defaultValue={model?.name} className={field} />
      </label>
      <label htmlFor={id("api")} className="text-sm font-medium">
        {t("settings.api")}
        <select id={id("api")} name="api" defaultValue={model?.api ?? "openai"} className={field}>
          <option value="openai">{t("settings.apiOpenai")}</option>
          <option value="openrouter">{t("settings.apiOpenrouter")}</option>
        </select>
      </label>
      <label htmlFor={id("model")} className="text-sm font-medium">
        {t("settings.model")}
        <input id={id("model")} name="model" required maxLength={200} defaultValue={model?.model} className={field} />
      </label>
      <label htmlFor={id("base_url")} className="text-sm font-medium sm:col-span-2">
        {t("settings.baseUrl")}
        <input id={id("base_url")} name="base_url" type="url" required defaultValue={model?.base_url} className={field} />
      </label>
      <label htmlFor={id("api_key")} className="text-sm font-medium sm:col-span-2">
        {t("settings.apiKey")}
        {/* The key is write-only: the API never returns it (MOD-002). */}
        <input id={id("api_key")} name="api_key" type="password" autoComplete="off" className={field} />
        {model?.has_api_key && <span className="mt-1 block text-xs font-normal">{t("settings.apiKeySet")}</span>}
      </label>
      <label className="flex items-center gap-2 text-sm font-medium sm:col-span-2">
        <input name="paid" type="checkbox" defaultChecked={model?.paid ?? false} />
        {t("settings.paid")}
      </label>
      {error && (
        <p role="alert" className="text-sm text-red-800 sm:col-span-2 dark:text-red-300">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2 sm:col-span-2">
        <button type="button" className="rounded-lg px-3 py-2" onClick={() => void onDone()}>
          {t("settings.cancel")}
        </button>
        <button type="submit" className="rounded-lg bg-stone-800 px-3 py-2 text-white">
          {t("settings.save")}
        </button>
      </div>
    </form>
  );
}
