import { Check, ChevronDown, Cloud, House } from "lucide-react";
import { type CSSProperties, type RefObject, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import type { EgressPolicy, ModelChoice, ModelOption } from "../api/client";
import { findModel, refusedBy, sameModel, shortPrice, useModels } from "../models";

// The space the panel keeps from the window's edges and from its button.
const MARGIN = 12;
const GAP = 8;
const HEIGHT = 480;

/**
 * A button showing a model, which opens the model picker: in the message box
 * (`compact`) and for the household's default model in the settings (UX-015).
 */
export function ModelSelect(props: {
  value: ModelChoice | null;
  onChange: (choice: ModelChoice) => void;
  compact?: boolean;
  label?: string;
  placeholder?: string;
  // Which models to offer: chat models unless said otherwise (ADR-0088).
  kind?: ModelOption["kind"];
  // Whose data egress policy marks remote models unavailable: the user's, or the household's for its
  // defaults (MOD-003, ADR-0091).
  policy?: "effective" | "household";
}) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const models = useModels();
  const chosen = findModel(models.data?.items, props.value);
  // Without a model, the message box offers to choose one when there is something to choose.
  if (props.compact && !chosen && !props.placeholder) return null;
  const local = chosen?.location === "local";
  const shown = chosen ? (props.compact ? chosen.name : `${chosen.name} · ${chosen.connection_name}`) : props.placeholder;
  return (
    <>
      <button
        ref={button}
        type="button"
        className={
          props.compact
            ? "flex min-w-0 items-center gap-1.5 rounded-[9px] px-2 py-1.5 text-[13.5px] font-medium text-muted hover:bg-hover hover:text-fg aria-expanded:bg-hover aria-expanded:text-fg"
            : "flex h-10 w-full max-w-[420px] items-center gap-2 rounded-[10px] border border-line-strong bg-bg px-3 text-left outline-none hover:bg-hover focus-visible:border-accent aria-expanded:border-accent"
        }
        // The name holds what the button shows, so that it can be spoken as it reads (UX-007).
        aria-label={props.label && `${props.label}: ${shown ?? ""}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {chosen && (local ? <House className="size-4 flex-none" aria-hidden="true" /> : <Cloud className="size-4 flex-none" aria-hidden="true" />)}
        <span className={`truncate ${props.compact ? "" : "flex-1"}`}>
          {shown}
        </span>
        <ChevronDown className="size-4 flex-none" aria-hidden="true" />
      </button>
      {open && models.data && (
        <ModelPicker
          anchor={button}
          options={models.data.items.filter((option) => option.kind === (props.kind ?? "chat"))}
          defaultModel={models.data.default}
          chosen={props.value}
          policy={models.data.egress[props.policy ?? "effective"]}
          onPick={(option) => {
            setOpen(false);
            props.onChange({ connection_id: option.connection_id, model: option.model });
          }}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

/** Where the panel fits: on the side of its button with more room, never past the window. */
function placement(anchor: HTMLElement): CSSProperties {
  const box = anchor.getBoundingClientRect();
  const width = Math.min(400, window.innerWidth - 2 * MARGIN);
  const left = Math.min(Math.max(MARGIN, box.right - width), window.innerWidth - width - MARGIN);
  const above = box.top - GAP - MARGIN;
  const below = window.innerHeight - box.bottom - GAP - MARGIN;
  if (above >= below) return { left, width, bottom: window.innerHeight - box.top + GAP, maxHeight: Math.min(HEIGHT, above) };
  return { left, width, top: box.bottom + GAP, maxHeight: Math.min(HEIGHT, below) };
}

/** Every model of the household's connections, searchable, grouped by connection (UX-015). */
function ModelPicker(props: {
  anchor: RefObject<HTMLElement | null>;
  options: ModelOption[];
  defaultModel: ModelChoice | null;
  chosen: ModelChoice | null;
  policy: EgressPolicy;
  onPick: (option: ModelOption) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [style, setStyle] = useState<CSSProperties | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const { anchor, onClose } = props;
  useLayoutEffect(() => {
    function place() {
      if (anchor.current) setStyle(placement(anchor.current));
    }
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [anchor]);
  useEffect(() => {
    function outside(event: MouseEvent) {
      const target = event.target as Node;
      // The button toggles the panel itself.
      if (panel.current?.contains(target) || anchor.current?.contains(target)) return;
      onClose();
    }
    function escape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [anchor, onClose]);
  const needle = query.trim().toLowerCase();
  const matching = props.options.filter(
    (option) => !needle || option.name.toLowerCase().includes(needle) || option.connection_name.toLowerCase().includes(needle) || option.model.toLowerCase().includes(needle),
  );
  const groups = new Map<string, ModelOption[]>();
  for (const option of matching) groups.set(option.connection_id, [...(groups.get(option.connection_id) ?? []), option]);

  return createPortal(
    <div
      ref={panel}
      role="dialog"
      aria-label={t("picker.title")}
      style={style ?? { visibility: "hidden" }}
      className="slide fixed z-50 flex flex-col overflow-hidden rounded-2xl border border-line bg-raised text-fg shadow-soft"
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
      <div className="min-h-0 overflow-y-auto px-1.5 pt-1 pb-2">
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
              {refusedBy(props.policy, first) && <p className="mx-2.5 mb-1 text-xs text-muted">{t("picker.refused")}</p>}
              {options.map((option) => (
                <button
                  key={option.model}
                  type="button"
                  disabled={refusedBy(props.policy, option)}
                  onClick={() => props.onPick(option)}
                  className="grid w-full grid-cols-[minmax(0,1fr)_auto] gap-x-2.5 rounded-[11px] px-2.5 py-2 text-left hover:bg-hover focus-visible:bg-hover disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent"
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
    </div>,
    document.body,
  );
}
