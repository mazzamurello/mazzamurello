// The settings of conversations: the user's defaults and one conversation's own (CNV-013, CNV-014, ADR-0081).
import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, X } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, unwrap, type Allowances, type Conversation, type ModelChoice, type Reasoning, type ToolName, type UserSettings, type UserSettingsView } from "../api/client";
import { updateConversation } from "../conversations";
import { findModel, useModels } from "../models";
import { useNotify } from "../notices";
import { toolLabel, useLockedTools } from "../tools";
import { OwnEgressSwitch } from "./EgressSettings";
import { ModelSelect } from "./ModelPicker";

export const SETTINGS = ["me", "settings"] as const;
const REASONING: Reasoning[] = ["off", "on", "deep"];
// Every tool of the assistant, by group (CNV-013, ADR-0087); the groups are the client's own.
const TOOL_GROUPS: { id: string; tools: ToolName[] }[] = [
  { id: "web", tools: ["web_search", "read_page"] },
  { id: "commands", tools: ["run_command", "start_command", "check_command", "stop_command"] },
  { id: "files", tools: ["read_file", "write_file", "edit_file", "create_directory", "list_directory", "find_files", "search_files", "file_info"] },
  { id: "showing", tools: ["offer_download"] },
  { id: "questions", tools: ["ask_user_question"] },
  { id: "tasks", tools: ["write_plan", "read_plan", "add_task", "update_task_status", "update_task_statuses", "remove_task"] },
];
const SWITCH =
  "relative h-6 w-10 flex-none rounded-full bg-line-strong transition-colors peer-checked:bg-accent peer-focus-visible:outline-2 peer-focus-visible:outline-accent after:absolute after:top-0.5 after:left-0.5 after:size-5 after:rounded-full after:bg-bg after:transition-transform peer-checked:after:translate-x-4";
const BUTTON = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] border border-line-strong bg-surface px-4 text-sm font-semibold hover:bg-hover disabled:opacity-50";
const PRIMARY = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] bg-fg px-4 text-sm font-semibold text-bg disabled:opacity-50";
const TEXTAREA = "min-h-24 w-full rounded-[10px] border border-line-strong bg-bg px-3 py-2 text-sm outline-none focus:border-accent";

export function useSettings() {
  return useQuery({ queryKey: SETTINGS, queryFn: async () => unwrap(await api.GET("/me/settings")) });
}

/** Whether a model may reason: not one known not to. */
function useReasons(choice: ModelChoice | null | undefined): boolean {
  const models = useModels();
  return findModel(models.data?.items, choice)?.reasoning !== false;
}

/** A text left as the one it inherits is no text of its own, so it keeps following its default (ADR-0081). */
function own(text: string, inherited: string): string | null {
  return text === inherited ? null : text;
}

function ReasoningField({ value, onChange, reasons }: { value: Reasoning; onChange: (value: Reasoning) => void; reasons: boolean }) {
  const { t } = useTranslation();
  const label = useId();
  const name = useId();
  const note = useId();
  return (
    <div>
      <h3 id={label} className="mb-1 text-sm font-bold">
        {t("assistant.reasoning")}
      </h3>
      <p className="mb-2.5 max-w-[62ch] text-sm text-muted">{t("assistant.reasoningHint")}</p>
      <div
        role="radiogroup"
        aria-labelledby={label}
        aria-describedby={reasons ? undefined : note}
        aria-disabled={!reasons || undefined}
        className="inline-flex rounded-[10px] border border-line-strong p-0.5 aria-disabled:opacity-50"
      >
        {REASONING.map((level) => (
          <label key={level} className="relative cursor-pointer rounded-lg px-3.5 py-1.5 text-sm font-semibold text-muted has-checked:bg-hover has-checked:text-fg has-disabled:cursor-not-allowed has-focus-visible:outline-2 has-focus-visible:outline-accent">
            <input
              type="radio"
              name={name}
              value={level}
              checked={reasons ? value === level : level === "off"}
              disabled={!reasons}
              onChange={() => onChange(level)}
              className="absolute inset-0 cursor-pointer opacity-0 disabled:cursor-not-allowed"
            />
            {t(`assistant.levels.${level}`)}
          </label>
        ))}
      </div>
      {!reasons && (
        <p id={note} className="mt-2 text-sm text-muted">
          {t("assistant.cannotReason")}
        </p>
      )}
    </div>
  );
}

/** A switch: the label names it, the description says more (UX-007). */
export function Switch({
  label,
  description,
  checked,
  onChange,
  strong = false,
  locked = false,
}: {
  label: string;
  description?: React.ReactNode;
  checked: boolean;
  onChange: (on: boolean) => void;
  strong?: boolean;
  locked?: boolean;
}) {
  const name = useId();
  const more = useId();
  return (
    <div className="relative flex max-w-[460px] items-center justify-between gap-3 rounded-[10px] px-1 py-1.5 text-sm">
      <span className="flex min-w-0 flex-col">
        <label htmlFor={name} className={`cursor-pointer ${strong ? "font-bold" : ""}`}>
          {label}
        </label>
        {description && (
          <span id={more} className="text-[12.5px] text-muted">
            {description}
          </span>
        )}
      </span>
      <input
        id={name}
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={locked}
        aria-describedby={description ? more : undefined}
        onChange={(event) => onChange(event.target.checked)}
        className="peer absolute inset-0 size-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
      />
      <span aria-hidden="true" className={`${SWITCH} peer-disabled:opacity-50`} />
    </div>
  );
}

/**
 * Every tool, by group with its name, each with a switch, and a switch for each group (CNV-013, ADR-0087).
 * A tool the household's admin denied is off and locked, and says why (ADR-0090).
 */
function ToolSwitches({ disabled, onChange }: { disabled: ToolName[]; onChange: (disabled: ToolName[]) => void }) {
  const { t } = useTranslation();
  const heading = useId();
  const locked = useLockedTools();
  const isOn = (tool: ToolName) => !disabled.includes(tool) && !locked.has(tool);
  const set = (tools: ToolName[], on: boolean) => onChange(on ? disabled.filter((name) => !tools.includes(name)) : [...disabled.filter((name) => !tools.includes(name)), ...tools]);
  return (
    <div role="group" aria-labelledby={heading}>
      <h3 id={heading} className="mb-1 text-sm font-bold">
        {t("assistant.tools")}
      </h3>
      <p className="mb-2.5 max-w-[62ch] text-sm text-muted">{t("assistant.toolsHint")}</p>
      <div className="flex flex-col gap-3">
        {TOOL_GROUPS.map((group) => {
          const on = group.tools.filter(isOn).length;
          const free = group.tools.filter((tool) => !locked.has(tool));
          return (
            <div key={group.id} className="max-w-[460px] rounded-[14px] border border-line px-2.5 py-1.5">
              <Switch
                label={t(`assistant.toolGroups.${group.id}`)}
                description={t("assistant.toolsOn", { on, total: group.tools.length })}
                checked={free.length > 0 && free.every(isOn)}
                onChange={(checked) => set(free, checked)}
                strong
                locked={free.length === 0}
              />
              <div className="mt-0.5 flex flex-col border-t border-line pt-0.5 pl-2">
                {group.tools.map((tool) => (
                  <Switch
                    key={tool}
                    label={t(`assistant.toolNames.${tool}`)}
                    description={
                      <>
                        <code className="font-mono">{tool}</code>
                        {locked.has(tool) && <span className="block">{t("permissions.lockedByAdmin")}</span>}
                      </>
                    }
                    checked={isOn(tool)}
                    locked={locked.has(tool)}
                    onChange={(checked) => set([tool], checked)}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function AdditionalPrompt({ value, onChange, placeholder }: { value: string; onChange: (text: string) => void; placeholder: string }) {
  const { t } = useTranslation();
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-bold">
        {t("assistant.additional")}
      </label>
      <p className="mb-2 max-w-[62ch] text-sm text-muted">{t("assistant.additionalHint")}</p>
      <textarea id={id} className={TEXTAREA} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} maxLength={20000} />
    </div>
  );
}

/** The system prompt, set apart: replacing it changes who the assistant is (CNV-014). */
function DangerZone({ value, inherited, onChange }: { value: string; inherited: string; onChange: (text: string) => void }) {
  const { t } = useTranslation();
  const heading = useId();
  const id = useId();
  return (
    <section aria-labelledby={heading} className="rounded-2xl border border-danger/45 p-4">
      <h3 id={heading} className="mb-1 text-sm font-bold text-danger">
        {t("assistant.dangerZone")}
      </h3>
      <p className="mb-3 max-w-[62ch] text-sm text-muted">{t("assistant.dangerHint")}</p>
      <div className="mb-1 flex items-center justify-between gap-2">
        <label htmlFor={id} className="text-sm font-bold">
          {t("assistant.base")}
        </label>
        <button type="button" className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[13px] font-semibold text-muted hover:bg-hover hover:text-fg disabled:opacity-50" disabled={value === inherited} onClick={() => onChange(inherited)}>
          <RotateCcw className="size-3.5" aria-hidden="true" />
          {/* Named in its content, so that the field's label stays the only one that names it. */}
          <span aria-hidden="true">{t("assistant.restoreShort")}</span>
          <span className="sr-only">{t("assistant.restore")}</span>
        </button>
      </div>
      <p className="mb-2 max-w-[62ch] text-sm text-muted">{t("assistant.baseHint")}</p>
      <textarea id={id} className={`${TEXTAREA} min-h-40`} value={value} onChange={(event) => onChange(event.target.value)} maxLength={20000} />
    </section>
  );
}

/** The user's defaults, in the settings: settings save at once, prompts on request. */
export function AssistantSection() {
  const settings = useSettings();
  if (!settings.data) return null;
  return <AssistantForm view={settings.data} />;
}

function AssistantForm({ view }: { view: UserSettingsView }) {
  const { t } = useTranslation();
  const models = useModels();
  const householdModel = findModel(models.data?.items, models.data?.default);
  const queries = useQueryClient();
  const heading = useId();
  const notify = useNotify();
  const { built_in_base_instructions: builtIn, ...stored } = view;
  // The form's own copy, so that a choice shows at once.
  const [settings, setSettings] = useState<UserSettings>(stored);
  const reasons = useReasons(settings.model);
  const [base, setBase] = useState(settings.base_instructions ?? builtIn);
  const [additional, setAdditional] = useState(settings.additional_instructions ?? "");
  const [saved, setSaved] = useState(false);

  async function save(changes: Partial<UserSettings>) {
    const body = { ...settings, ...changes };
    setSettings(body);
    try {
      const updated = unwrap(await api.PUT("/me/settings", { body }));
      queries.setQueryData(SETTINGS, updated);
      return true;
    } catch {
      setSettings(settings);
      notify({ kind: "error", title: t("errors.title"), text: t("assistant.notSaved") });
      return false;
    }
  }

  async function savePrompts() {
    setSaved(await save({ base_instructions: own(base, builtIn), additional_instructions: own(additional, "") }));
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
        <ModelSelect
          value={settings.model}
          onChange={(model) => void save({ model })}
          label={t("assistant.model")}
          placeholder={householdModel ? t("assistant.householdModel", { name: householdModel.name }) : t("assistant.noHouseholdModel")}
        />
      </div>
      <OwnEgressSwitch />
      <ReasoningField value={settings.reasoning ?? "on"} onChange={(reasoning) => void save({ reasoning })} reasons={reasons} />
      <ToolSwitches disabled={settings.disabled_tools} onChange={(disabled_tools) => void save({ disabled_tools })} />
      <AdditionalPrompt
        value={additional}
        onChange={(text) => {
          setAdditional(text);
          setSaved(false);
        }}
        placeholder={t("assistant.none")}
      />
      <DangerZone
        value={base}
        inherited={builtIn}
        onChange={(text) => {
          setBase(text);
          setSaved(false);
        }}
      />
      <div className="flex items-center gap-3">
        <button type="button" className={PRIMARY} onClick={() => void savePrompts()}>
          {t("assistant.savePrompts")}
        </button>
        <span role="status" className="text-sm text-muted">
          {saved ? t("settings.saved") : ""}
        </span>
      </div>
    </section>
  );
}

/** One conversation's settings and prompts, in a dialog; they apply from its next answer. */
export function ChatSettings({ conversation, open, onOpenChange }: { conversation: Conversation; open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        {open && <ChatSettingsLoader conversation={conversation} onDone={() => onOpenChange(false)} />}
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** The dialog's fields start from the user's defaults, so it waits for them. */
function ChatSettingsLoader(props: { conversation: Conversation; onDone: () => void }) {
  const settings = useSettings();
  if (!settings.data) return null;
  return <ChatSettingsForm {...props} defaults={settings.data} />;
}

function ChatSettingsForm({ conversation, defaults, onDone }: { conversation: Conversation; defaults: UserSettingsView; onDone: () => void }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const notify = useNotify();
  const reasons = useReasons(conversation.model);
  const inheritedBase = defaults.base_instructions ?? defaults.built_in_base_instructions;
  const inheritedAdditional = defaults.additional_instructions ?? "";
  const [reasoning, setReasoning] = useState(conversation.reasoning);
  const [disabled, setDisabled] = useState(conversation.disabled_tools);
  const [base, setBase] = useState(conversation.base_instructions ?? inheritedBase);
  const [additional, setAdditional] = useState(conversation.additional_instructions ?? inheritedAdditional);
  const [allowances, setAllowances] = useState<Allowances>(conversation.allowances);
  const withdrawn = allowances.web_and_commands !== conversation.allowances.web_and_commands || allowances.tools.length !== conversation.allowances.tools.length;

  async function save() {
    try {
      const updated = await updateConversation(conversation.id, {
        reasoning,
        disabled_tools: disabled,
        ...(withdrawn ? { allowances } : {}),
        base_instructions: own(base, inheritedBase),
        additional_instructions: own(additional, inheritedAdditional),
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
        <ReasoningField value={reasoning} onChange={setReasoning} reasons={reasons} />
        <ToolSwitches disabled={disabled} onChange={setDisabled} />
        <AllowedInChat allowances={allowances} onChange={setAllowances} />
        <AdditionalPrompt value={additional} onChange={setAdditional} placeholder={t("assistant.none")} />
        <DangerZone value={base} inherited={inheritedBase} onChange={setBase} />
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

/** What the user allowed in this conversation by answering approval requests, each one withdrawable (AGT-006, UX-023). */
function AllowedInChat({ allowances, onChange }: { allowances: Allowances; onChange: (allowances: Allowances) => void }) {
  const { t } = useTranslation();
  const heading = useId();
  const items: { key: string; label: string; withdraw: () => void }[] = [
    ...(allowances.web_and_commands ? [{ key: "web_and_commands", label: t("approvals.webAndCommands"), withdraw: () => onChange({ ...allowances, web_and_commands: false }) }] : []),
    ...allowances.tools.map((tool) => ({ key: tool, label: toolLabel(t, tool), withdraw: () => onChange({ ...allowances, tools: allowances.tools.filter((name) => name !== tool) }) })),
  ];
  return (
    <section aria-labelledby={heading}>
      <h3 id={heading} className="mb-1 text-sm font-bold">
        {t("approvals.allowedInChat")}
      </h3>
      <p className="mb-2.5 max-w-[62ch] text-sm text-muted">{t("approvals.allowedHint")}</p>
      {items.length === 0 ? (
        <p className="text-sm text-muted">{t("approvals.nothingAllowed")}</p>
      ) : (
        <ul className="flex max-w-[460px] flex-col gap-1.5">
          {items.map((item) => (
            <li key={item.key} className="flex items-center justify-between gap-3 rounded-[10px] border border-line px-3 py-1.5 text-sm">
              <span>{item.label}</span>
              <button type="button" className="rounded-lg px-2 py-1 text-[13px] font-semibold text-danger hover:bg-hover" onClick={item.withdraw}>
                {t("approvals.withdraw")}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
