import { type FormEvent, type KeyboardEvent, useState } from "react";
import { useTranslation } from "react-i18next";

/** The message box: Enter sends, Shift+Enter starts a new line; while a run goes on, Stop. */
export function Composer({ onSend, onStop, running }: { onSend: (text: string) => void; onStop?: () => void; running: boolean }) {
  const { t } = useTranslation();
  const [text, setText] = useState("");

  function send(event?: FormEvent) {
    event?.preventDefault();
    const message = text.trim();
    if (!message || running) return;
    onSend(message);
    setText("");
  }

  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) send(event);
  }

  return (
    <form onSubmit={send} className="mx-auto flex w-full max-w-3xl items-end gap-2 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      <label className="sr-only" htmlFor="composer">
        {t("composer.label")}
      </label>
      <textarea
        id="composer"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={keyDown}
        rows={Math.min(8, Math.max(1, text.split("\n").length))}
        placeholder={t("composer.placeholder")}
        className="min-h-12 flex-1 resize-none rounded-xl border border-stone-400 bg-white px-3 py-3 text-base text-stone-900"
      />
      {running && onStop ? (
        <button type="button" onClick={onStop} className="rounded-xl bg-red-800 px-4 py-3 font-medium text-white">
          {t("composer.stop")}
        </button>
      ) : (
        <button type="submit" disabled={!text.trim()} className="rounded-xl bg-stone-800 px-4 py-3 font-medium text-white disabled:opacity-60">
          {t("composer.send")}
        </button>
      )}
    </form>
  );
}
