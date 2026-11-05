import { ArrowUp, Square } from "lucide-react";
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ModelChoice } from "../api/client";
import { hasKeyboard } from "../focus";
import { findModel, useModels } from "../models";
import { ModelSelect } from "./ModelPicker";

/** The message box: Enter sends, Shift+Enter starts a new line; while a run goes on, Stop. */
export function Composer(props: {
  onSend: (text: string) => void;
  onStop?: () => void;
  running: boolean;
  model: ModelChoice | null;
  onModel: (choice: ModelChoice) => void;
  placeholder: string;
  // Take the focus when shown, on devices with a keyboard (UX-018).
  autoFocus?: boolean;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
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
          autoFocus={props.autoFocus === true && hasKeyboard()}
          placeholder={props.placeholder}
          className="max-h-[220px] min-h-[26px] resize-none bg-transparent text-base leading-normal outline-none placeholder:text-faint"
        />
        <div className="flex items-center gap-1.5">
          <span className="flex-1" />
          <ModelSelect compact value={props.model} onChange={props.onModel} />
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
