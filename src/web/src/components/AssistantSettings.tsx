// The settings of conversations: the user's defaults and one conversation's own (CNV-013, CNV-014, ADR-0081).
import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, X } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, unwrap, type Conversation, type ModelChoice, type Reasoning, type ToolName, type UserSettings } from "../api/client";
import { updateConversation } from "../conversations";
import { findModel, useModels } from "../models";
import { useNotify } from "../notices";
import { ModelSelect } from "./ModelPicker";

export const SETTINGS = ["me", "settings"] as const;
const REASONING: Reasoning[] = ["off", "on", "deep"];
const TOOLS: ToolName[] = ["web_search", "read_page", "shell", "file_system", "offer_download"];
const BUTTON = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] border border-line-strong bg-surface px-4 text-sm font-semibold hover:bg-hover disabled:opacity-50";
const PRIMARY = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] bg-fg px-4 text-sm font-semibold text-bg disabled:opacity-50";
const TEXTAREA = "min-h-24 w-full rounded-[10px] border border-line-strong bg-bg px-3 py-2 text-sm outline-none focus:border-accent";

export function useSettings() {
  return useQuery({ queryKey: SETTINGS, queryFn: async () => unwrap(await api.GET("/me/settings")) });
}

/** Whether to offer reasoning for a model: not for one known not to reason. */
function useReasons(choice: ModelChoice | null | undefined): boolean {
  const models = useModels();
  return findModel(models.data?.items, choice)?.reasoning !== false;
}

/** An empty text is no text: the default instructions apply. */
function orNull(text: string): string | null {
  return text.trim() === "" ? null : text;
}

function ReasoningField({ value, onChange }: { value: Reasoning; onChange: (value: Reasoning) => void }) {
  const { t } = useTranslation();
  const label = useId();
  const name = useId();
  return (
    <div>
      <h3 id={label} className="mb-1 text-sm font-bold">
        {t("assistant.reasoning")}
      </h3>
      <p className="mb-2.5 max-w-[62ch] text-sm text-muted">{t("assistant.reasoningHint")}</p>
      <div role="radiogroup" aria-labelledby={label} className="inline-flex rounded-[10px] border border-line-strong p-0.5">
        {REASONING.map((level) => (
          <label key={level} className="relative cursor-pointer rounded-lg px-3.5 py-1.5 text-sm font-semibold text-muted has-checked:bg-hover has-checked:text-fg has-focus-visible:outline-2 has-focus-visible:outline-accent">
            <input type="radio" name={name} value={level} checked={value === level} onChange={() => onChange(level)} className="absolute inset-0 cursor-pointer opacity-0" />
            {t(`assistant.levels.${level}`)}
          </label>
        ))}
      </div>
    </div>
  );
}

function ToolSwitches({ disabled, onChange }: { disabled: ToolName[]; onChange: (disabled: ToolName[]) => void }) {
  const { t } = useTranslation();
  return (
    <div>
      <h3 className="mb-1 text-sm font-bold">{t("assistant.tools")}</h3>
      <p className="mb-2.5 max-w-[62ch] text-sm text-muted">{t("assistant.toolsHint")}</p>
      <div className="flex flex-col gap-1">
        {TOOLS.map((tool) => (
          <label key={tool} className="relative flex max-w-[420px] cursor-pointer items-center justify-between gap-3 rounded-[10px] px-1 py-1.5 text-sm">
            {t(`assistant.toolNames.${tool}`)}
            <input
              type="checkbox"
              role="switch"
              checked={!disabled.includes(tool)}
              onChange={(event) => onChange(event.target.checked ? disabled.filter((name) => name !== tool) : [...disabled, tool])}
              className="peer absolute inset-0 size-full cursor-pointer opacity-0"
            />
            <span
              aria-hidden="true"
              className="relative h-6 w-10 flex-none rounded-full bg-line-strong transition-colors peer-checked:bg-accent peer-focus-visible:outline-2 peer-focus-visible:outline-accent after:absolute after:top-0.5 after:left-0.5 after:size-5 after:rounded-full after:bg-bg after:transition-transform peer-checked:after:translate-x-4"
            />
          </label>
        ))}
      </div>
    </div>
  );
}

function InstructionsFields(props: {
  base: string;
  additional: string;
  onBase: (text: string) => void;
  onAdditional: (text: string) => void;
  basePlaceholder: string;
  additionalPlaceholder: string;
}) {
  const { t } = useTranslation();
  const base = useId();
  const additional = useId();
  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="mb-1 flex items-center justify-between gap-2">
          <label htmlFor={base} className="text-sm font-bold">
            {t("assistant.base")}
          </label>
          <button type="button" className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[13px] font-semibold text-muted hover:bg-hover hover:text-fg disabled:opacity-50" disabled={props.base === ""} onClick={() => props.onBase("")}>
            <RotateCcw className="size-3.5" aria-hidden="true" />
            {/* Named in its content, so that the field's label stays the only one that names it. */}
            <span aria-hidden="true">{t("assistant.restoreShort")}</span>
            <span className="sr-only">{t("assistant.restore")}</span>
          </button>
        </div>
        <p className="mb-2 max-w-[62ch] text-sm text-muted">{t("assistant.baseHint")}</p>
        <textarea id={base} className={TEXTAREA} value={props.base} placeholder={props.basePlaceholder} onChange={(event) => props.onBase(event.target.value)} maxLength={20000} />
      </div>
      <div>
        <label htmlFor={additional} className="mb-1 block text-sm font-bold">
          {t("assistant.additional")}
        </label>
        <p className="mb-2 max-w-[62ch] text-sm text-muted">{t("assistant.additionalHint")}</p>
        <textarea id={additional} className={TEXTAREA} value={props.additional} placeholder={props.additionalPlaceholder} onChange={(event) => props.onAdditional(event.target.value)} maxLength={20000} />
      </div>
    </div>
  );
}

/** The user's defaults, in the settings: settings save at once, instructions on request. */
export function AssistantSection() {
  const settings = useSettings();
  if (!settings.data) return null;
  return <AssistantForm settings={settings.data} />;
}

function AssistantForm(props: { settings: UserSettings }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const heading = useId();
  const notify = useNotify();
  // The form's own copy, so that a choice shows at once.
  const [settings, setSettings] = useState(props.settings);
  const reasons = useReasons(settings.model);
  const [base, setBase] = useState(settings.base_instructions ?? "");
  const [additional, setAdditional] = useState(settings.additional_instructions ?? "");
  const [saved, setSaved] = useState(false);

  async function save(changes: Partial<UserSettings>) {
    const body = { ...settings, ...changes };
    setSettings(body);
    try {
      const stored = unwrap(await api.PUT("/me/settings", { body }));
      queries.setQueryData(SETTINGS, stored);
      return true;
    } catch {
      setSettings(settings);
      notify({ kind: "error", title: t("errors.title"), text: t("assistant.notSaved") });
      return false;
    }
  }

  async function saveInstructions() {
    setSaved(await save({ base_instructions: orNull(base), additional_instructions: orNull(additional) }));
  }

  return (
    <section aria-labelledby={heading} className="flex flex-col gap-6">
      <div>
        <h2 id={heading} className="mb-1 text-base font-bold">
          {t("assistant.title")}
        </h2>
        <p className="max-w-[62ch] text-sm text-muted">{t("assistant.hint")}</p>
      </div>
      <div>
        <h3 className="mb-1 text-sm font-bold">{t("assistant.model")}</h3>
        <p className="mb-2.5 max-w-[62ch] text-sm text-muted">{t("assistant.modelHint")}</p>
        <ModelSelect value={settings.model} onChange={(model) => void save({ model })} label={t("assistant.model")} placeholder={t("assistant.householdModel")} />
      </div>
      {reasons && <ReasoningField value={settings.reasoning ?? "on"} onChange={(reasoning) => void save({ reasoning })} />}
      <ToolSwitches disabled={settings.disabled_tools} onChange={(disabled_tools) => void save({ disabled_tools })} />
      <InstructionsFields
        base={base}
        additional={additional}
        onBase={(text) => {
          setBase(text);
          setSaved(false);
        }}
        onAdditional={(text) => {
          setAdditional(text);
          setSaved(false);
        }}
        basePlaceholder={t("assistant.builtIn")}
        additionalPlaceholder={t("assistant.none")}
      />
      <div className="flex items-center gap-3">
        <button type="button" className={PRIMARY} onClick={() => void saveInstructions()}>
          {t("assistant.saveInstructions")}
        </button>
        <span role="status" className="text-sm text-muted">
          {saved ? t("settings.saved") : ""}
        </span>
      </div>
    </section>
  );
}

/** One conversation's settings and instructions, in a dialog; they apply from its next answer. */
export function ChatSettings({ conversation, open, onOpenChange }: { conversation: Conversation; open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        {open && <ChatSettingsForm conversation={conversation} onDone={() => onOpenChange(false)} />}
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ChatSettingsForm({ conversation, onDone }: { conversation: Conversation; onDone: () => void }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const reasons = useReasons(conversation.model);
  const [reasoning, setReasoning] = useState(conversation.reasoning);
  const [disabled, setDisabled] = useState(conversation.disabled_tools);
  const [base, setBase] = useState(conversation.base_instructions ?? "");
  const [additional, setAdditional] = useState(conversation.additional_instructions ?? "");

  async function save() {
    try {
      const updated = await updateConversation(conversation.id, {
        reasoning,
        disabled_tools: disabled,
        base_instructions: orNull(base),
        additional_instructions: orNull(additional),
      });
      queries.setQueryData(["conversation", conversation.id, "details"], updated);
      onDone();
    } catch {
      notify({ kind: "error", title: t("errors.title"), text: t("assistant.notSaved") });
    }
  }

  return (
    <Dialog.Content className="rise fixed top-1/2 left-1/2 z-50 flex max-h-[min(92dvh,46rem)] w-[min(92vw,34rem)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-[20px] bg-raised text-fg shadow-soft">
      <div className="flex items-start justify-between gap-3 px-[22px] pt-[22px]">
        <div>
          <Dialog.Title className="text-lg font-bold tracking-tight">{t("assistant.chat")}</Dialog.Title>
          <Dialog.Description className="text-sm text-muted">{t("assistant.chatHint")}</Dialog.Description>
        </div>
        <Dialog.Close className="grid size-9 flex-none place-items-center rounded-[10px] text-muted hover:bg-hover hover:text-fg" aria-label={t("files.close")}>
          <X className="size-5" aria-hidden="true" />
        </Dialog.Close>
      </div>
      <div className="flex min-h-0 flex-col gap-6 overflow-y-auto px-[22px] py-4">
        {reasons && <ReasoningField value={reasoning} onChange={setReasoning} />}
        <ToolSwitches disabled={disabled} onChange={setDisabled} />
        <InstructionsFields
          base={base}
          additional={additional}
          onBase={setBase}
          onAdditional={setAdditional}
          basePlaceholder={t("assistant.myBase")}
          additionalPlaceholder={t("assistant.myAdditional")}
        />
      </div>
      <div className="flex justify-end gap-2 border-t border-line px-[22px] py-3.5">
        <Dialog.Close className={BUTTON}>{t("conversationMenu.cancel")}</Dialog.Close>
        <button type="button" className={PRIMARY} onClick={() => void save()}>
          {t("conversationMenu.save")}
        </button>
      </div>
    </Dialog.Content>
  );
}
