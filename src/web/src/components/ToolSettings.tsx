// The user's tool activity, and each user's tool permissions for the household's admins (UX-023, AGT-002, AGT-008, ADR-0090).
import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { api, unwrap, type AuditEvent, type CapabilityClass, type PermissionSetting, type ToolInfo, type ToolName, type ToolPermissions } from "../api/client";
import { useNotify } from "../notices";
import { outcomeLabel, toolLabel, useTools } from "../tools";
import { UserEgressSwitch } from "./EgressSettings";

const PRIMARY = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] bg-fg px-4 text-sm font-semibold text-bg disabled:opacity-50";
const SELECT = "h-9 rounded-[10px] border border-line-strong bg-bg px-2 text-sm outline-none focus:border-accent";
const CLASSES: CapabilityClass[] = ["reads_private_data", "ingests_untrusted", "external_communication", "irreversible", "physical"];
const SETTINGS: PermissionSetting[] = ["allow", "ask", "deny"];
const STRICTNESS: Record<PermissionSetting, number> = { allow: 0, ask: 1, deny: 2 };

/** Every tool call the user's assistant made, newest first, without its content (UX-023, AGT-008). */
export function ActivitySection() {
  const { t, i18n } = useTranslation();
  const heading = useId();
  const toolField = useId();
  const tools = useTools();
  const [tool, setTool] = useState("");
  const activity = useQuery({
    queryKey: ["me", "activity", tool],
    queryFn: async () => unwrap(await api.GET("/me/activity", { params: { query: tool ? { tool, limit: 100 } : { limit: 100 } } })).items,
  });
  const time = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" });
  return (
    <section aria-labelledby={heading} className="flex flex-col gap-4">
      <div>
        <h2 id={heading} className="mb-1 text-base font-bold">
          {t("activity.page.title")}
        </h2>
        <p className="max-w-[62ch] text-sm text-muted">{t("activity.page.hint")}</p>
      </div>
      <div className="flex max-w-[460px] flex-col gap-1">
        <label htmlFor={toolField} className="text-sm font-bold">
          {t("activity.page.tool")}
        </label>
        <select id={toolField} className={SELECT} value={tool} onChange={(event) => setTool(event.target.value)}>
          <option value="">{t("activity.page.allTools")}</option>
          {(tools.data ?? []).map((item) => (
            <option key={item.name} value={item.name}>
              {toolLabel(t, item.name)}
            </option>
          ))}
        </select>
      </div>
      {activity.data && activity.data.length === 0 && <p className="text-sm text-muted">{t("activity.page.none")}</p>}
      <ul aria-label={t("activity.page.calls")} className="flex flex-col gap-1.5">
        {(activity.data ?? []).map((event) => (
          <ActivityItem key={event.id} event={event} when={time.format(new Date(event.created_at))} />
        ))}
      </ul>
    </section>
  );
}

function ActivityItem({ event, when }: { event: AuditEvent; when: string }) {
  const { t } = useTranslation();
  const failed = event.outcome === "denied" || event.outcome === "expired" || event.outcome === "refused";
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[12px] border border-line px-3 py-2 text-sm">
      <span className="font-semibold">{toolLabel(t, event.tool)}</span>
      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${failed ? "bg-danger/15 text-danger" : "bg-hover"}`}>{outcomeLabel(t, event.outcome, event.scope)}</span>
      {event.repeated && <span className="text-xs font-semibold text-danger">{t("activity.page.repeated")}</span>}
      <span className="ml-auto text-xs text-muted tabular-nums">{when}</span>
      <span className="basis-full text-[13px] text-muted">
        {event.conversation_title === null ? (
          t("activity.page.deletedChat")
        ) : (
          <Link to={`/c/${event.conversation_id}`} className="underline underline-offset-2 hover:text-fg">
            {event.conversation_title || t("activity.page.untitled")}
          </Link>
        )}
      </span>
    </li>
  );
}

/** What applies to a tool with these settings: its own, else the strictest of its classes', else its default (AGT-002). */
function applied(tool: ToolInfo, permissions: ToolPermissions): { setting: PermissionSetting; from: string | null } {
  const own = permissions.tools[tool.name];
  if (own) return { setting: own, from: tool.name };
  let found: { setting: PermissionSetting; from: string | null } | null = null;
  for (const name of tool.classes) {
    const setting = permissions.classes[name];
    if (setting && (found === null || STRICTNESS[setting] > STRICTNESS[found.setting])) found = { setting, from: name };
  }
  return found ?? { setting: tool.approval_default, from: null };
}

/** Each user's tool permissions, per tool and per capability class, for the household's admins (UX-023, AGT-002). */
export function ToolPermissionsSection() {
  const { t } = useTranslation();
  const heading = useId();
  const userField = useId();
  const users = useQuery({ queryKey: ["tenant", "users"], queryFn: async () => unwrap(await api.GET("/tenant/users", { params: { query: { limit: 100 } } })).items });
  const [userId, setUserId] = useState("");
  return (
    <section aria-labelledby={heading} className="flex flex-col gap-4">
      <div>
        <h2 id={heading} className="mb-1 text-base font-bold">
          {t("permissions.title")}
        </h2>
        <p className="max-w-[62ch] text-sm text-muted">{t("permissions.hint")}</p>
      </div>
      <div className="flex max-w-[460px] flex-col gap-1">
        <label htmlFor={userField} className="text-sm font-bold">
          {t("permissions.user")}
        </label>
        <select id={userField} className={SELECT} value={userId} onChange={(event) => setUserId(event.target.value)}>
          <option value="">{t("permissions.chooseUser")}</option>
          {(users.data ?? []).map((user) => (
            <option key={user.id} value={user.id}>
              {user.username}
            </option>
          ))}
        </select>
      </div>
      {userId && <UserEgressSwitch key={`egress-${userId}`} userId={userId} />}
      {userId && <PermissionsLoader key={userId} userId={userId} />}
    </section>
  );
}

function PermissionsLoader({ userId }: { userId: string }) {
  const stored = useQuery({
    queryKey: ["tenant", "users", userId, "tool-permissions"],
    queryFn: async () => unwrap(await api.GET("/tenant/users/{user_id}/tool-permissions", { params: { path: { user_id: userId } } })),
  });
  const tools = useTools();
  if (!stored.data || !tools.data) return null;
  return <PermissionsForm userId={userId} stored={stored.data} tools={tools.data} />;
}

function SettingSelect({ label, value, onChange }: { label: string; value: PermissionSetting | undefined; onChange: (value: PermissionSetting | undefined) => void }) {
  const { t } = useTranslation();
  return (
    <select aria-label={label} className={SELECT} value={value ?? "default"} onChange={(event) => onChange(event.target.value === "default" ? undefined : (event.target.value as PermissionSetting))}>
      <option value="default">{t("permissions.settings.default")}</option>
      {SETTINGS.map((setting) => (
        <option key={setting} value={setting}>
          {t(`permissions.settings.${setting}`)}
        </option>
      ))}
    </select>
  );
}

function PermissionsForm({ userId, stored, tools }: { userId: string; stored: ToolPermissions; tools: ToolInfo[] }) {
  const { t } = useTranslation();
  const notify = useNotify();
  const [permissions, setPermissions] = useState<ToolPermissions>(stored);
  const [saved, setSaved] = useState(false);

  function setTool(name: ToolName, value: PermissionSetting | undefined) {
    const next = { ...permissions.tools };
    if (value) next[name] = value;
    else delete next[name];
    setPermissions({ ...permissions, tools: next });
    setSaved(false);
  }

  function setClass(name: CapabilityClass, value: PermissionSetting | undefined) {
    const next = { ...permissions.classes };
    if (value) next[name] = value;
    else delete next[name];
    setPermissions({ ...permissions, classes: next });
    setSaved(false);
  }

  async function save() {
    try {
      unwrap(await api.PUT("/tenant/users/{user_id}/tool-permissions", { params: { path: { user_id: userId } }, body: permissions }));
      setSaved(true);
    } catch {
      notify({ kind: "error", title: t("errors.title"), text: t("assistant.notSaved") });
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h3 className="mb-1 text-sm font-bold">{t("permissions.byClass")}</h3>
        <p className="mb-2.5 max-w-[62ch] text-sm text-muted">{t("permissions.byClassHint")}</p>
        <div className="flex max-w-[460px] flex-col gap-1.5">
          {CLASSES.map((name) => (
            <div key={name} className="flex items-center justify-between gap-3 text-sm">
              <span>{t(`permissions.classes.${name}`)}</span>
              <SettingSelect label={t(`permissions.classes.${name}`)} value={permissions.classes[name]} onChange={(value) => setClass(name, value)} />
            </div>
          ))}
        </div>
      </div>
      <div>
        <h3 className="mb-1 text-sm font-bold">{t("permissions.byTool")}</h3>
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-muted">
            <tr>
              <th scope="col" className="py-1.5 font-semibold">{t("permissions.tool")}</th>
              <th scope="col" className="py-1.5 font-semibold">{t("permissions.setting")}</th>
              <th scope="col" className="py-1.5 font-semibold">{t("permissions.applies")}</th>
            </tr>
          </thead>
          <tbody>
            {tools.map((tool) => {
              const label = toolLabel(t, tool.name);
              const result = applied(tool, permissions);
              return (
                <tr key={tool.name} className="border-t border-line">
                  <th scope="row" className="py-1.5 pr-3 font-normal">
                    {label} <code className="block font-mono text-xs text-muted">{tool.name}</code>
                  </th>
                  <td className="py-1.5 pr-3">
                    <SettingSelect label={label} value={permissions.tools[tool.name]} onChange={(value) => setTool(tool.name, value)} />
                  </td>
                  <td className="py-1.5">
                    {t(`permissions.settings.${result.setting}`)}
                    <span className="block text-xs text-muted">
                      {result.from === null ? t("permissions.fromDefault") : result.from === tool.name ? t("permissions.fromTool") : t("permissions.fromClass", { name: t(`permissions.classes.${result.from}`) })}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-3">
        <button type="button" className={PRIMARY} onClick={() => void save()}>
          {t("permissions.save")}
        </button>
        <span role="status" className="text-sm text-muted">
          {saved ? t("settings.saved") : ""}
        </span>
      </div>
    </div>
  );
}
