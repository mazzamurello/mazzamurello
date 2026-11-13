import { ArrowUp, FileText, Headphones, LoaderCircle, Mic, Paperclip, Square, X } from "lucide-react";
import { type DragEvent, type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ModelChoice } from "../api/client";
import { hasKeyboard } from "../focus";
import { findModel, refusedBy, useModels } from "../models";
import { type AttachedFile, formatSize, type useAttachments } from "../workspace";
import { ModelSelect } from "./ModelPicker";
import { Recorder, transcribe } from "../speech";
import { VoiceLevel } from "./VoiceLevel";
import { useVoice, type VoiceMode } from "../voice";
import { useNotify } from "../notices";

/** The message box: Enter sends, Shift+Enter starts a new line; while a run goes on, Stop. Files attach by picking or dropping (CNV-017). */
export function Composer(props: {
  // `voice`: how the message came, when it was not typed (ADR-0088).
  onSend: (text: string, attachments: AttachedFile[], voice?: VoiceMode) => void;
  attachments: ReturnType<typeof useAttachments>;
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
  const picker = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const files = props.attachments;
  const voice = useVoice();
  const notify = useNotify();
  const recorder = useRef(new Recorder());
  const [dictation, setDictation] = useState<"off" | "recording" | "preparing">("off");
  // A hands-free turn is sent by the message box in view (UX-005).
  const onSend = useRef(props.onSend);
  onSend.current = props.onSend;
  useEffect(() => voice?.register((said, mode) => onSend.current(said, [], mode)), [voice?.register]);
  // Whether the box holds dictated words, which the assistant is told about (ADR-0088).
  const [dictated, setDictated] = useState(false);

  /** Dictation: the spoken turn becomes the text of the box, to review before sending (UX-005). */
  async function dictate() {
    if (dictation === "preparing") return;
    if (dictation === "off") {
      try {
        await recorder.current.start();
        setDictation("recording");
      } catch {
        notify({ kind: "error", title: t("voice.noMicrophone") });
      }
      return;
    }
    setDictation("preparing");
    try {
      const said = (await transcribe(await recorder.current.stop())).trim();
      if (said) {
        setText((now) => (now.trim() ? `${now.trimEnd()} ${said}` : said));
        setDictated(true);
      }
    } catch {
      notify({ kind: "error", title: t("voice.notHeard") });
    } finally {
      setDictation("off");
      requestAnimationFrame(() => area.current?.focus());
    }
  }

  useEffect(() => {
    const element = area.current;
    if (element === null) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 220)}px`;
  }, [text]);

  function send(event?: FormEvent) {
    event?.preventDefault();
    const message = text.trim();
    if (!message || props.running || files.uploading) return;
    props.onSend(message, files.ready, dictated ? "dictated" : undefined);
    setText("");
    setDictated(false);
    files.clear();
  }

  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) send(event);
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length > 0) files.add([...event.dataTransfer.files]);
  }

  const local = chosen?.location === "local";
  // A model the user's data egress policy refuses, said before anything is sent (UX-024).
  const refused = refusedBy(models.data?.egress.effective, chosen);
  return (
    <div className="w-full">
      <form
        onSubmit={send}
        onDragOver={(event) => {
          if (event.dataTransfer.types.includes("Files")) {
            event.preventDefault();
            setDragging(true);
          }
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={drop}
        className={`relative flex flex-col gap-2 rounded-3xl border bg-surface pt-3.5 pr-3 pb-2.5 pl-[18px] shadow-soft focus-within:border-accent/45 ${dragging ? "border-accent" : "border-line-strong"}`}
      >
        {files.items.length > 0 && (
          <ul aria-label={t("files.attachments")} className="-ml-1.5 flex flex-wrap gap-1.5">
            {files.items.map((item) => (
              <li key={item.key} className="flex max-w-full items-center gap-2 rounded-xl border border-line bg-hover py-1.5 pr-1 pl-2.5 text-[13px]">
                <FileText className="size-4 flex-none text-muted" aria-hidden="true" />
                <span className="flex min-w-0 flex-col">
                  <span className="truncate font-semibold">{item.name}</span>
                  <span className={item.error ? "text-danger" : "text-muted"}>
                    {item.error
                      ? t(`files.errors.${errorKey(item.error)}`)
                      : item.path === undefined
                        ? item.progress >= 1
                          ? t("files.saving")
                          : t("files.uploading", { percent: Math.round(item.progress * 100) })
                        : formatSize(item.size)}
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => files.remove(item.key)}
                  className="grid size-7 flex-none place-items-center rounded-lg text-muted hover:bg-surface hover:text-fg"
                  aria-label={t("files.remove", { name: item.name })}
                  title={t("files.remove", { name: item.name })}
                >
                  <X className="size-4" aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <label className="sr-only" htmlFor="composer">
          {t("composer.label")}
        </label>
        <textarea
          id="composer"
          ref={area}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            // Cleared, the box holds no dictated words anymore.
            if (!event.target.value.trim()) setDictated(false);
          }}
          onKeyDown={keyDown}
          rows={1}
          autoFocus={props.autoFocus === true && hasKeyboard()}
          placeholder={props.placeholder}
          className={`max-h-[220px] min-h-[26px] resize-none bg-transparent text-base leading-normal outline-none placeholder:text-faint ${dictation === "off" ? "" : "hidden"}`}
        />
        {/* Dictation in the box itself: the voice as it is captured, and how to end it; then the wait (UX-005). */}
        {dictation === "recording" && recorder.current.stream && (
          <div className="flex items-center gap-3">
            <VoiceLevel stream={recorder.current.stream} label={t("voice.capturing")} className="min-w-0 flex-1 text-danger" />
            <button
              type="button"
              onClick={() => void dictate()}
              aria-label={t("voice.stopDictating")}
              className="flex h-11 flex-none items-center gap-2 rounded-full bg-danger px-4 text-sm font-semibold text-on-danger"
            >
              <Square className="size-3.5" fill="currentColor" aria-hidden="true" />
              {t("voice.stop")}
            </button>
          </div>
        )}
        {dictation === "preparing" && (
          <p role="status" className="flex h-14 items-center gap-2.5 text-base text-muted">
            <LoaderCircle className="size-5 animate-spin" aria-hidden="true" />
            <span className="live-text">{t("voice.preparing")}</span>
          </p>
        )}
        <div className="flex items-center gap-1.5">
          <input
            ref={picker}
            type="file"
            multiple
            hidden
            aria-label={t("files.attach")}
            onChange={(event) => {
              if (event.target.files) files.add([...event.target.files]);
              event.target.value = "";
            }}
          />
          <button
            type="button"
            onClick={() => picker.current?.click()}
            title={t("files.attachOne")}
            aria-label={t("files.attachOne")}
            className="-ml-2 grid size-9 place-items-center rounded-xl text-muted hover:bg-hover hover:text-fg"
          >
            <Paperclip className="size-[18px]" aria-hidden="true" />
          </button>
          {voice?.transcription && dictation === "off" && (
            <button
              type="button"
              onClick={() => void dictate()}
              disabled={voice.transcriptionRefused}
              // Unavailable, saying why, when only local models are allowed (UX-024).
              title={voice.transcriptionRefused ? t("voice.refused") : t("voice.dictate")}
              aria-label={t("voice.dictate")}
              className="grid size-9 place-items-center rounded-xl text-muted hover:bg-hover hover:text-fg disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
            >
              <Mic className="size-[18px]" aria-hidden="true" />
            </button>
          )}
          {voice?.transcription && voice.speech && (
            <button
              type="button"
              onClick={voice.open}
              disabled={voice.transcriptionRefused || voice.speechRefused}
              title={voice.transcriptionRefused || voice.speechRefused ? t("voice.refused") : t("voice.handsFree")}
              aria-label={t("voice.handsFree")}
              className="grid size-9 place-items-center rounded-xl text-muted hover:bg-hover hover:text-fg disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
            >
              <Headphones className="size-[18px]" aria-hidden="true" />
            </button>
          )}
          <span className="flex-1" />
          <ModelSelect compact value={props.model} onChange={props.onModel} />
          {props.running && props.onStop ? (
            <button type="button" onClick={props.onStop} className="grid size-9 flex-none place-items-center rounded-xl bg-fg text-bg" aria-label={t("composer.stop")}>
              <Square className="size-3.5" fill="currentColor" aria-hidden="true" />
            </button>
          ) : (
            <button type="submit" disabled={!text.trim() || files.uploading} className="grid size-9 flex-none place-items-center rounded-xl bg-accent text-on-accent transition-opacity disabled:opacity-35" aria-label={t("composer.send")}>
              <ArrowUp className="size-[18px]" strokeWidth={2.4} aria-hidden="true" />
            </button>
          )}
        </div>
      </form>
      {/* Where the conversation's data goes (MOD-010), and whether the model can use tools (MOD-014). */}
      <p className="mt-2 flex items-center justify-center gap-1.5 text-center text-[12.5px] text-faint">
        {models.data && models.data.items.length === 0
          ? t("composer.noModel")
          : refused
            ? t("composer.refused")
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

/** The translation key of an upload's error. */
export function errorKey(code: string): string {
  return ["file.too_large", "workspace.quota_exceeded", "resource.conflict", "sandbox.unavailable", "network"].includes(code) ? code.replace(".", "_") : "internal_error";
}
