import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Bot, Check, Cloud, House, Palette, Plug, Plus, ShieldCheck, Users, X } from "lucide-react";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, api, unwrap, type Connection, type ConnectionTest, type ModelChoice, type Schemas, type User } from "../api/client";
import { findModel, MODELS, useModels } from "../models";
import { useNotify } from "../notices";
import { type Theme, useTheme } from "../theme";
import { AssistantSection } from "./AssistantSettings";
import { ModelSelect } from "./ModelPicker";
import { HouseholdEgressSection } from "./EgressSettings";
import { ActivitySection, ToolPermissionsSection } from "./ToolSettings";

type SpeechSettings = Schemas["SpeechSettings"];

const CONNECTIONS = ["connections"] as const;
const BUTTON = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] border border-line-strong bg-surface px-4 text-sm font-semibold hover:bg-hover disabled:opacity-50";
const PRIMARY = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] bg-fg px-4 text-sm font-semibold text-bg disabled:opacity-50";
const INPUT = "h-10 w-full rounded-[10px] border border-line-strong bg-bg px-3 outline-none focus:border-accent";

type Tab = "models" | "permissions" | "assistant" | "activity" | "appearance";

interface TabItem {
  id: Tab;
  label: string;
  icon: React.ReactNode;
}

/**
 * The settings: for everyone their assistant (CNV-013, CNV-014) and the theme (UX-011), and, set
 * apart for its admins, the household's models (UX-015, UX-016).
 */
export function Settings({ me }: { me: User }) {
  const { t } = useTranslation();
  const admin = me.role === "tenant_admin";
  const [tab, setTab] = useState<Tab>(admin ? "models" : "assistant");
  const yours: TabItem[] = [
    { id: "assistant", label: t("assistant.title"), icon: <Bot className="size-[18px]" aria-hidden="true" /> },
    { id: "activity", label: t("activity.page.title"), icon: <Activity className="size-[18px]" aria-hidden="true" /> },
    { id: "appearance", label: t("settings.appearance"), icon: <Palette className="size-[18px]" aria-hidden="true" /> },
  ];
  const household: TabItem[] = admin
    ? [
        { id: "models", label: t("settings.models"), icon: <Plug className="size-[18px]" aria-hidden="true" /> },
        { id: "permissions", label: t("permissions.title"), icon: <ShieldCheck className="size-[18px]" aria-hidden="true" /> },
      ]
    : [];
  return (
    <div className="relative min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto grid max-w-[900px] grid-cols-1 gap-[18px] px-4 pt-6 pb-14 md:grid-cols-[190px_minmax(0,1fr)] md:gap-9">
        <h1 className="text-[26px] font-bold tracking-tight md:col-span-2">{t("settings.title")}</h1>
        <nav aria-label={t("settings.sections")} className="flex gap-3 overflow-x-auto md:flex-col md:gap-4">
          <TabGroup title={t("settings.yours")} items={yours} tab={tab} onChoose={setTab} />
          {household.length > 0 && <TabGroup title={t("settings.household")} items={household} tab={tab} onChoose={setTab} />}
        </nav>
        <div className="flex min-w-0 flex-col gap-[34px]">
          {tab === "models" && admin ? (
            <ModelsSection />
          ) : tab === "permissions" && admin ? (
            <ToolPermissionsSection />
          ) : tab === "assistant" ? (
            <AssistantSection />
          ) : tab === "activity" ? (
            <ActivitySection />
          ) : (
            <AppearanceSection />
          )}
        </div>
      </div>
    </div>
  );
}

/** The sections of one kind of settings: the user's own, or the household's (UX-015). */
function TabGroup({ title, items, tab, onChoose }: { title: string; items: TabItem[]; tab: Tab; onChoose: (tab: Tab) => void }) {
  const heading = useId();
  return (
    <div role="group" aria-labelledby={heading} className="flex flex-none gap-0.5 md:flex-col">
      <h2 id={heading} className="hidden px-3 pb-1 text-xs font-semibold text-faint md:block">
        {title}
      </h2>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          aria-current={tab === item.id ? "page" : undefined}
          onClick={() => onChoose(item.id)}
          className="flex items-center gap-2.5 rounded-[9px] px-3 py-2 text-left font-medium whitespace-nowrap text-muted hover:bg-hover hover:text-fg aria-[current=page]:bg-hover aria-[current=page]:font-semibold aria-[current=page]:text-fg"
        >
          {item.icon}
          {item.label}
        </button>
      ))}
    </div>
  );
}

function AppearanceSection() {
  const { t } = useTranslation();
  const [theme, setTheme] = useTheme();
  const themes: { id: Theme; label: string; swatch: string }[] = [
    { id: "system", label: t("settings.system"), swatch: "bg-[linear-gradient(135deg,#f7f7f5_50%,#171719_50%)]" },
    { id: "light", label: t("settings.light"), swatch: "bg-[linear-gradient(90deg,#efefec_30%,#f7f7f5_30%)]" },
    { id: "dark", label: t("settings.dark"), swatch: "bg-[linear-gradient(90deg,#1e1e21_30%,#171719_30%)]" },
  ];
  return (
    <section>
      <h2 className="mb-1 text-base font-bold">{t("settings.theme")}</h2>
      <p className="mb-3.5 text-sm text-muted">{t("settings.themeHint")}</p>
      <div className="grid max-w-[480px] grid-cols-3 gap-2.5">
        {themes.map((item) => (
          <button
            key={item.id}
            type="button"
            aria-pressed={theme === item.id}
            onClick={() => setTheme(item.id)}
            className="flex flex-col gap-2 rounded-[14px] border border-line-strong bg-surface p-3 text-left text-sm font-semibold aria-pressed:border-accent aria-pressed:shadow-[0_0_0_1px_var(--accent)]"
          >
            <span className={`h-11 rounded-lg border border-line ${item.swatch}`} aria-hidden="true" />
            {item.label}
          </button>
        ))}
      </div>
    </section>
  );
}

function ModelsSection() {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const models = useModels();
  const connections = useQuery({ queryKey: CONNECTIONS, queryFn: async () => unwrap(await api.GET("/tenant/connections")).items });
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<Connection | null>(null);
  const [results, setResults] = useState<Record<string, ConnectionTest>>({});

  async function refresh() {
    await queries.invalidateQueries({ queryKey: CONNECTIONS });
    await queries.invalidateQueries({ queryKey: MODELS });
  }

  async function chooseDefault(choice: ModelChoice) {
    unwrap(await api.PUT("/tenant/default-model", { body: choice }));
    await refresh();
    notify({ kind: "info", title: t("settings.saved") });
  }

  async function test(connection: Connection) {
    const result = unwrap(await api.POST("/tenant/connections/{connection_id}/test", { params: { path: { connection_id: connection.id } } }));
    setResults({ ...results, [connection.id]: result });
    await refresh();
  }

  async function remove(connection: Connection) {
    await api.DELETE("/tenant/connections/{connection_id}", { params: { path: { connection_id: connection.id } } });
    setRemoving(null);
    await refresh();
  }

  const current = models.data?.default;
  return (
    <>
      <p role="note" className="flex max-w-[62ch] items-start gap-2.5 rounded-[14px] border border-line bg-surface px-3.5 py-3 text-sm">
        <Users className="mt-0.5 size-[18px] flex-none text-muted" aria-hidden="true" />
        {t("settings.householdNote")}
      </p>
      <section>
        <h2 className="mb-1 text-base font-bold">{t("settings.defaultModel")}</h2>
        <p className="mb-3.5 max-w-[62ch] text-sm text-muted">{t("settings.defaultHint")}</p>
        <ModelSelect value={current ?? null} onChange={(choice) => void chooseDefault(choice)} label={t("settings.defaultModel")} placeholder={t("settings.noDefault")} policy="household" />
      </section>
      <HouseholdEgressSection />
      <SpeechSection />
      <section>
        <h2 className="mb-1 text-base font-bold">{t("settings.connections")}</h2>
        <p className="mb-3.5 max-w-[62ch] text-sm text-muted">{t("settings.connectionsHint")}</p>
        <div className="flex flex-col gap-2.5">
          {connections.data?.length === 0 && <p className="text-sm text-muted">{t("settings.noConnections")}</p>}
          {connections.data?.map((connection) => (
            <div key={connection.id} className="rounded-2xl border border-line bg-surface px-4 py-3.5">
              <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3.5 gap-y-0.5">
                <span className="row-span-2 grid size-[42px] place-items-center rounded-xl bg-accent-soft text-accent" aria-hidden="true">
                  {connection.location === "local" ? <House className="size-5" /> : <Cloud className="size-5" />}
                </span>
                <span className="flex flex-wrap items-center gap-2 font-bold">
                  {connection.name}
                  <span className="inline-flex items-center gap-1 rounded-full border border-line-strong px-2 text-[11.5px] font-semibold text-muted">
                    {connection.location === "local" ? t("settings.local") : t("settings.remote")}
                  </span>
                </span>
                <span className="row-span-2 inline-flex items-center gap-1.5 rounded-full bg-ok/15 px-2.5 py-[3px] text-xs font-semibold whitespace-nowrap text-ok">
                  <Check className="size-3.5" aria-hidden="true" />
                  {connection.model_count === 1 ? t("settings.modelCountOne", { count: 1 }) : t("settings.modelCountMany", { count: connection.model_count })}
                </span>
                <span className="col-start-2 text-[13px] break-all text-muted">{connection.base_url}</span>
              </div>
              <div className="mt-2.5 flex gap-2">
                <button type="button" className={`${BUTTON} h-8 px-3 text-[13px]`} onClick={() => void test(connection)}>
                  {t("settings.test")}
                </button>
                <button type="button" className={`${BUTTON} h-8 px-3 text-[13px]`} onClick={() => setRemoving(connection)}>
                  {t("settings.remove")}
                </button>
              </div>
              {connection.id in results && <TestResult test={results[connection.id] as ConnectionTest} />}
            </div>
          ))}
        </div>
        <div className="mt-3">
          <button type="button" className={BUTTON} onClick={() => setAdding(true)}>
            <Plus className="size-[18px]" aria-hidden="true" />
            {t("settings.add")}
          </button>
        </div>
      </section>
      {adding && <AddConnection onClose={() => setAdding(false)} onAdded={refresh} existing={connections.data ?? []} />}
      <Dialog.Root open={removing !== null} onOpenChange={(open) => !open && setRemoving(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
          <Dialog.Content role="alertdialog" className="rise fixed top-1/2 left-1/2 z-50 w-[min(92vw,28rem)] -translate-x-1/2 -translate-y-1/2 rounded-[20px] bg-raised p-[22px] shadow-soft">
            <Dialog.Title className="mb-2 text-lg font-bold">{t("settings.removeTitle", { name: removing?.name ?? "" })}</Dialog.Title>
            <Dialog.Description className="text-muted">{t("settings.removeBody")}</Dialog.Description>
            <div className="mt-[18px] flex justify-end gap-2">
              <Dialog.Close className={BUTTON}>{t("connection.cancel")}</Dialog.Close>
              <button type="button" className="h-[38px] rounded-[10px] bg-danger px-4 text-sm font-semibold text-on-danger" onClick={() => removing && void remove(removing)}>
                {t("settings.remove")}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}

/** The household's speech models: one that transcribes spoken turns, one that reads aloud with a voice (API-006, ADR-0088). */
function SpeechSection() {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const models = useModels();
  const current = models.data?.speech ?? { transcription: null, speech: null };
  const speechModel = findModel(models.data?.items, current.speech);
  const [pending, setPending] = useState<{ choice: ModelChoice; voice: string } | null>(null);
  const shown = pending ?? (current.speech ? { choice: current.speech, voice: current.speech.voice } : null);
  const shownModel = findModel(models.data?.items, shown?.choice) ?? speechModel;
  const voiceField = useId();

  async function save(settings: SpeechSettings) {
    try {
      unwrap(await api.PUT("/tenant/speech", { body: settings }));
      await queries.invalidateQueries({ queryKey: MODELS });
      setPending(null);
      notify({ kind: "info", title: t("settings.saved") });
    } catch {
      notify({ kind: "error", title: t("errors.title"), text: t("errors.internal_error") });
    }
  }

  function chooseSpeech(choice: ModelChoice) {
    const voices = findModel(models.data?.items, choice)?.voices ?? [];
    const voice = voices[0];
    if (voice) void save({ ...current, speech: { ...choice, voice } });
    else setPending({ choice, voice: "" });
  }

  return (
    <section>
      <h2 className="mb-1 text-base font-bold">{t("settings.voice")}</h2>
      <p className="mb-3.5 max-w-[62ch] text-sm text-muted">{t("settings.voiceHint")}</p>
      <div className="flex max-w-[420px] flex-col gap-3">
        <div className="flex items-center gap-2">
          <ModelSelect kind="transcription" value={current.transcription} onChange={(choice) => void save({ ...current, transcription: choice })} label={t("settings.transcriptionModel")} placeholder={t("settings.noTranscription")} />
          {current.transcription && (
            <button type="button" className={`${BUTTON} h-10 flex-none px-3 text-[13px]`} onClick={() => void save({ ...current, transcription: null })}>
              {t("settings.remove")}
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <ModelSelect kind="speech" value={shown?.choice ?? null} onChange={chooseSpeech} label={t("settings.speechModel")} placeholder={t("settings.noSpeech")} />
          {current.speech && (
            <button type="button" className={`${BUTTON} h-10 flex-none px-3 text-[13px]`} onClick={() => void save({ ...current, speech: null })}>
              {t("settings.remove")}
            </button>
          )}
        </div>
        {shown && (
          <form
            className="flex items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              const voice = String(new FormData(event.currentTarget).get("voice") ?? "").trim();
              if (voice) void save({ ...current, speech: { ...shown.choice, voice } });
            }}
          >
            <div className="flex flex-1 flex-col gap-1.5">
              <label htmlFor={voiceField} className="text-[13.5px] font-semibold">
                {t("settings.voiceName")}
              </label>
              {shownModel?.voices?.length ? (
                <select
                  id={voiceField}
                  name="voice"
                  defaultValue={shown.voice}
                  key={`${shown.choice.model}-${shown.voice}`}
                  onChange={(event) => void save({ ...current, speech: { ...shown.choice, voice: event.target.value } })}
                  className={INPUT}
                >
                  {shownModel.voices.map((voice) => (
                    <option key={voice}>{voice}</option>
                  ))}
                </select>
              ) : (
                <input id={voiceField} name="voice" defaultValue={shown.voice} key={`${shown.choice.model}-${shown.voice}`} required maxLength={200} className={INPUT} placeholder={t("settings.voicePlaceholder")} />
              )}
            </div>
            {!shownModel?.voices?.length && (
              <button type="submit" className={`${BUTTON} h-10`}>
                {t("settings.saveVoice")}
              </button>
            )}
          </form>
        )}
      </div>
    </section>
  );
}

/** A connection test, step by step, with the reason for a failure and how to fix it (UX-016). */
function TestResult({ test }: { test: ConnectionTest }) {
  const { t } = useTranslation();
  const reason = test.reason;
  return (
    <div role={test.passed ? "status" : "alert"} className={`mt-3 flex flex-col gap-2.5 rounded-[14px] border px-3.5 py-3 text-[13.5px] ${test.passed ? "border-ok/50" : "border-danger/50"}`}>
      <div className="flex items-center gap-2 text-[14.5px] font-bold">
        {test.passed ? <Check className="size-[18px] text-ok" aria-hidden="true" /> : <X className="size-[18px] text-danger" aria-hidden="true" />}
        {test.passed ? t("connection.passed") : t(`connection.reasons.${reason ?? "http_error"}`)}
      </div>
      <p className="text-muted">
        {test.passed
          ? test.model_count === 1
            ? t("connection.passedBodyOne", { count: 1 })
            : t("connection.passedBodyMany", { count: test.model_count ?? 0 })
          : t(`connection.fixes.${reason ?? "http_error"}`)}
      </p>
      <ol className="flex flex-col gap-1.5">
        {test.steps.map((step) => (
          <li key={step.step} className={`grid grid-cols-[18px_minmax(0,1fr)_auto] items-center gap-x-2 ${step.outcome === "skipped" ? "text-faint" : ""}`}>
            <span className={`grid place-items-center ${step.outcome === "passed" ? "text-ok" : step.outcome === "failed" ? "text-danger" : ""}`} aria-hidden="true">
              {step.outcome === "passed" ? <Check className="size-[15px]" strokeWidth={2.4} /> : step.outcome === "failed" ? <X className="size-[15px]" strokeWidth={2.4} /> : "–"}
            </span>
            <span className={step.outcome === "skipped" ? "font-medium" : "font-semibold"}>{t(`connection.steps.${step.step}`)}</span>
            <span className="text-xs text-faint tabular-nums">{step.duration_ms === null ? "" : step.duration_ms >= 1000 ? `${Math.round(step.duration_ms / 1000)} s` : `${step.duration_ms} ms`}</span>
            <span className={`col-span-2 col-start-2 font-mono text-xs break-all ${step.outcome === "failed" ? "text-danger" : "text-muted"}`}>{step.detail}</span>
          </li>
        ))}
      </ol>
      {test.technical_detail && (
        <details>
          <summary className="cursor-pointer text-[13px] font-semibold text-muted">{t("connection.technical")}</summary>
          <pre className="mt-1.5 rounded-lg bg-hover px-2.5 py-2 font-mono text-xs break-all whitespace-pre-wrap">{test.technical_detail}</pre>
        </details>
      )}
    </div>
  );
}

function AddConnection(props: { onClose: () => void; onAdded: () => Promise<void>; existing: Connection[] }) {
  const { t } = useTranslation();
  const notify = useNotify();
  const [kind, setKind] = useState<"openrouter" | "openai">("openrouter");
  const [result, setResult] = useState<ConnectionTest | null>(null);
  const [busy, setBusy] = useState(false);

  /** OpenRouter needs only its key; its name is OpenRouter, numbered when the household has one already. */
  function request(form: HTMLFormElement) {
    const data = new FormData(form);
    const field = (name: string) => String(data.get(name) ?? "").trim();
    if (kind === "openrouter") {
      const taken = new Set(props.existing.map((connection) => connection.name));
      let name = t("connection.openrouter");
      for (let number = 2; taken.has(name); number += 1) name = `${t("connection.openrouter")} ${number}`;
      return { name, kind, api_key: field("api_key") };
    }
    const key = field("api_key");
    return {
      name: field("name"),
      kind,
      base_url: field("base_url"),
      location: field("location") === "remote" ? ("remote" as const) : ("local" as const),
      ...(key ? { api_key: key } : {}),
    };
  }

  async function runTest(form: HTMLFormElement | null) {
    if (form === null || !form.reportValidity()) return;
    setBusy(true);
    setResult(null);
    try {
      setResult(unwrap(await api.POST("/tenant/connection-tests", { body: request(form) })));
    } finally {
      setBusy(false);
    }
  }

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setResult(null);
    const body = request(event.currentTarget);
    try {
      const connection = unwrap(await api.POST("/tenant/connections", { body }));
      await props.onAdded();
      props.onClose();
      notify({
        kind: "info",
        title: t("connection.connected", { name: connection.name }),
        text: connection.model_count === 1 ? t("connection.connectedBodyOne", { count: 1 }) : t("connection.connectedBodyMany", { count: connection.model_count }),
      });
    } catch (error) {
      // A connection that fails its test is not saved; its test says why (MOD-013).
      const test = error instanceof ApiError ? (error.problem.test as ConnectionTest | undefined) : undefined;
      if (test) setResult(test);
      else notify({ kind: "error", title: t("errors.title"), text: t("errors.internal_error") });
    } finally {
      setBusy(false);
    }
  }

  const choice = "rounded-[9px] px-3 py-1.5 text-[13.5px] font-medium text-muted aria-pressed:bg-surface aria-pressed:text-fg aria-pressed:shadow-sm";
  return (
    <Dialog.Root open onOpenChange={(open) => !open && props.onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content className="rise fixed top-1/2 left-1/2 z-50 max-h-[calc(100%-2rem)] w-[min(92vw,30rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[20px] bg-raised p-[22px] shadow-soft">
          <Dialog.Title className="mb-3 text-lg font-bold">{t("connection.title")}</Dialog.Title>
          <Dialog.Description className="sr-only">{t("connection.kind")}</Dialog.Description>
          <div role="group" aria-label={t("connection.kind")} className="inline-flex flex-wrap gap-0.5 rounded-xl bg-hover p-[3px]">
            <button type="button" className={choice} aria-pressed={kind === "openrouter"} onClick={() => (setKind("openrouter"), setResult(null))}>
              {t("connection.openrouter")}
            </button>
            <button type="button" className={choice} aria-pressed={kind === "openai"} onClick={() => (setKind("openai"), setResult(null))}>
              {t("connection.server")}
            </button>
          </div>
          <form key={kind} onSubmit={(event) => void connect(event)} className="mt-3.5 flex flex-col gap-3.5">
            {kind === "openrouter" ? (
              <Field id="api-key" label={t("connection.apiKey")} hint={t("connection.apiKeyHint")}>
                <input id="api-key" name="api_key" type="password" autoComplete="off" required className={INPUT} />
              </Field>
            ) : (
              <>
                <Field id="server-name" label={t("connection.name")}>
                  <input id="server-name" name="name" required maxLength={100} className={INPUT} />
                </Field>
                <Field id="server-address" label={t("connection.address")} hint={t("connection.addressHint")}>
                  <input id="server-address" name="base_url" type="url" required className={INPUT} />
                </Field>
                <fieldset className="flex flex-col gap-1.5">
                  <legend className="mb-1.5 text-[13.5px] font-semibold">{t("connection.where")}</legend>
                  <label className="flex items-center gap-2 text-sm">
                    <input type="radio" name="location" value="local" defaultChecked />
                    {t("connection.atHome")}
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input type="radio" name="location" value="remote" />
                    {t("connection.elsewhere")}
                  </label>
                </fieldset>
                <Field id="server-key" label={t("connection.apiKeyOptional")}>
                  <input id="server-key" name="api_key" type="password" autoComplete="off" className={INPUT} />
                </Field>
              </>
            )}
            {busy && (
              <p role="status" className="live-text text-sm">
                {t("connection.testing")}
              </p>
            )}
            {result && <TestResult test={result} />}
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <button type="button" className={BUTTON} disabled={busy} onClick={(event) => void runTest(event.currentTarget.form)}>
                {t("connection.test")}
              </button>
              <span className="flex-1" />
              <Dialog.Close className={BUTTON}>{t("connection.cancel")}</Dialog.Close>
              <button type="submit" className={PRIMARY} disabled={busy}>
                {t("connection.connect")}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Field(props: { id: string; label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={props.id} className="text-[13.5px] font-semibold">
        {props.label}
      </label>
      {props.children}
      {props.hint && <small className="text-[12.5px] text-muted">{props.hint}</small>}
    </div>
  );
}
