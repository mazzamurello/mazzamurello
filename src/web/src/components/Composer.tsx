import { ArrowUp, Check, ChevronDown, Cloud, House, Square } from "lucide-react";
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ModelChoice, ModelOption } from "../api/client";
import { findModel, sameModel, shortPrice, useModels } from "../models";

/** The message box: Enter sends, Shift+Enter starts a new line; while a run goes on, Stop. */
export function Composer(props: {
  onSend: (text: string) => void;
  onStop?: () => void;
  running: boolean;
  model: ModelChoice | null;
  onModel: (choice: ModelChoice) => void;
  placeholder: string;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [picking, setPicking] = useState(false);
  const models = useModels();
  const chosen = findModel(models.data?.items, props.model);
  const area = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const element = area.current;
    if (element === null) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 220)}px`;
  }, [text]);

  function send(event?: FormEvent) {
    event?.preventDefault();
    const message = text.trim();
    if (!message || props.running) return;
    props.onSend(message);
    setText("");
  }

  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) send(event);
  }

  const local = chosen?.location === "local";
  return (
    <div className="w-full">
      <form
        onSubmit={send}
        className="relative flex flex-col gap-2 rounded-3xl border border-line-strong bg-surface pt-3.5 pr-3 pb-2.5 pl-[18px] shadow-soft focus-within:border-accent/45"
      >
        <label className="sr-only" htmlFor="composer">
          {t("composer.label")}
        </label>
        <textarea
          id="composer"
          ref={area}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={keyDown}
          rows={1}
          placeholder={props.placeholder}
          className="max-h-[220px] min-h-[26px] resize-none bg-transparent text-base leading-normal outline-none placeholder:text-faint"
        />
        <div className="flex items-center gap-1.5">
          <span className="flex-1" />
          {chosen && (
            <button
              type="button"
              className="flex min-w-0 items-center gap-1.5 rounded-[9px] px-2 py-1.5 text-[13.5px] font-medium text-muted hover:bg-hover hover:text-fg aria-expanded:bg-hover aria-expanded:text-fg"
              aria-haspopup="dialog"
              aria-expanded={picking}
              onClick={() => setPicking(!picking)}
            >
              {local ? <House className="size-4 flex-none" aria-hidden="true" /> : <Cloud className="size-4 flex-none" aria-hidden="true" />}
              <span className="truncate">{chosen.name}</span>
              <ChevronDown className="size-4 flex-none" aria-hidden="true" />
            </button>
          )}
          {props.running && props.onStop ? (
            <button type="button" onClick={props.onStop} className="grid size-9 flex-none place-items-center rounded-xl bg-fg text-bg" aria-label={t("composer.stop")}>
              <Square className="size-3.5" fill="currentColor" aria-hidden="true" />
            </button>
          ) : (
            <button type="submit" disabled={!text.trim()} className="grid size-9 flex-none place-items-center rounded-xl bg-accent text-on-accent transition-opacity disabled:opacity-35" aria-label={t("composer.send")}>
              <ArrowUp className="size-[18px]" strokeWidth={2.4} aria-hidden="true" />
            </button>
          )}
        </div>
        {picking && models.data && (
          <ModelPicker
            options={models.data.items}
            defaultModel={models.data.default}
            chosen={props.model}
            onPick={(option) => {
              setPicking(false);
              props.onModel({ connection_id: option.connection_id, model: option.model });
            }}
            onClose={() => setPicking(false)}
          />
        )}
      </form>
      {/* Where the conversation's data goes (MOD-010), and whether the model can use tools (MOD-014). */}
      <p className="mt-2 flex items-center justify-center gap-1.5 text-center text-[12.5px] text-faint">
        {models.data && models.data.items.length === 0
          ? t("composer.noModel")
          : chosen?.tools === false
            ? t("composer.chatOnly")
            : chosen
              ? local
                ? t("composer.local")
                : t("composer.remote", { connection: chosen.connection_name })
              : null}
      </p>
    </div>
  );
}

/** Every model of the household's connections, searchable, grouped by connection (UX-015). */
function ModelPicker(props: {
  options: ModelOption[];
  defaultModel: ModelChoice | null;
  chosen: ModelChoice | null;
  onPick: (option: ModelOption) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function outside(event: MouseEvent) {
      if (panel.current && !panel.current.contains(event.target as Node)) props.onClose();
    }
    function escape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") props.onClose();
    }
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [props]);
  const needle = query.trim().toLowerCase();
  const matching = props.options.filter(
    (option) => !needle || option.name.toLowerCase().includes(needle) || option.connection_name.toLowerCase().includes(needle) || option.model.toLowerCase().includes(needle),
  );
  const groups = new Map<string, ModelOption[]>();
  for (const option of matching) groups.set(option.connection_id, [...(groups.get(option.connection_id) ?? []), option]);

  return (
    <div
      ref={panel}
      role="dialog"
      aria-label={t("picker.title")}
      className="rise absolute right-1.5 bottom-[calc(100%+8px)] z-30 flex max-h-[min(480px,68vh)] w-[min(400px,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-line bg-raised shadow-soft"
    >
      <div className="border-b border-line p-2.5">
        <input
          type="search"
          autoFocus
          aria-label={t("picker.search")}
          placeholder={t("picker.searchPlaceholder", { count: props.options.length })}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="h-[38px] w-full rounded-[10px] border border-line-strong bg-bg px-3 text-sm outline-none focus:border-accent"
        />
      </div>
      <div className="overflow-y-auto px-1.5 pt-1 pb-2">
        {matching.length === 0 && <p className="px-2.5 py-4 text-sm text-muted">{t("picker.none", { query })}</p>}
        {[...groups.values()].map((options) => {
          const first = options[0];
          if (first === undefined) return null;
          return (
            <section key={first.connection_id}>
              <h3 className="mx-2.5 mt-3 mb-1 flex items-center gap-1.5 text-xs font-semibold text-muted">
                {first.location === "local" ? <House className="size-3.5" aria-hidden="true" /> : <Cloud className="size-3.5" aria-hidden="true" />}
                {first.connection_name}
                <span className="ml-auto font-normal">{first.location === "local" ? t("picker.local") : t("picker.remote")}</span>
              </h3>
              {options.map((option) => (
                <button
                  key={option.model}
                  type="button"
                  onClick={() => props.onPick(option)}
                  className="grid w-full grid-cols-[minmax(0,1fr)_auto] gap-x-2.5 rounded-[11px] px-2.5 py-2 text-left hover:bg-hover focus-visible:bg-hover"
                >
                  <span className="flex min-w-0 items-center gap-1.5 text-sm font-semibold">
                    <span className="truncate">{option.name}</span>
                    {sameModel(option, props.defaultModel) && <span className="rounded-full bg-accent-soft px-[7px] py-px text-[11px] font-bold text-accent">{t("picker.default")}</span>}
                    {option.tools === false && <span className="rounded-full border border-line-strong px-[7px] py-px text-[11px] font-semibold text-muted">{t("picker.chatOnly")}</span>}
                  </span>
                  <span className="row-span-2 self-center text-accent">{sameModel(option, props.chosen) && <Check className="size-[18px]" aria-hidden="true" />}</span>
                  <span className="text-[12.5px] text-muted tabular-nums">
                    {option.connection_name} ·{" "}
                    {option.location === "local"
                      ? t("picker.free")
                      : option.prices
                        ? t("picker.price", { input: shortPrice(option.prices.input), output: shortPrice(option.prices.output) })
                        : t("picker.unknownPrice")}
                  </span>
                </button>
              ))}
            </section>
          );
        })}
      </div>
      <p className="border-t border-line px-3.5 py-2 text-xs text-faint">{t("picker.footer")}</p>
    </div>
  );
}
