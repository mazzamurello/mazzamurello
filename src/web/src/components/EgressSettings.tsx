// Local models only: the user's own choice, a household admin's for the household and for each user (UX-024,
// MOD-003, ADR-0091).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api, unwrap, type EgressPolicy } from "../api/client";
import { MODELS, useModels } from "../models";
import { useNotify } from "../notices";
import { Switch } from "./AssistantSettings";

function policyOf(on: boolean): EgressPolicy {
  return on ? "local_only" : "any";
}

/** A switch that saves at once, saying so; `save` answers the policy as stored. */
function SavingSwitch(props: {
  label: string;
  description?: string;
  value: EgressPolicy;
  locked?: boolean | undefined;
  save: (policy: EgressPolicy) => Promise<EgressPolicy>;
}) {
  const { t } = useTranslation();
  const notify = useNotify();
  const [value, setValue] = useState(props.value);
  const [saved, setSaved] = useState(false);

  async function change(on: boolean) {
    const before = value;
    setValue(policyOf(on));
    setSaved(false);
    try {
      setValue(await props.save(policyOf(on)));
      setSaved(true);
    } catch {
      setValue(before);
      notify({ kind: "error", title: t("errors.title"), text: t("assistant.notSaved") });
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <Switch label={props.label} description={props.description} checked={props.locked === true || value === "local_only"} locked={props.locked === true} onChange={(on) => void change(on)} strong />
      <span role="status" className="px-1 text-sm text-muted">
        {saved ? t("settings.saved") : ""}
      </span>
    </div>
  );
}

/** The user's own choice, locked on when the household or an admin already chose it for them. */
export function OwnEgressSwitch() {
  const { t } = useTranslation();
  const models = useModels();
  const queries = useQueryClient();
  const egress = models.data?.egress;
  if (!egress) return null;
  const chosenBy = egress.household === "local_only" ? "household" : egress.admin === "local_only" ? "admin" : null;
  return (
    <div>
      <h3 className="mb-1 text-sm font-bold">{t("egress.title")}</h3>
      <p className="mb-2.5 max-w-[62ch] text-sm text-muted">{t("egress.hint")}</p>
      <SavingSwitch
        label={t("egress.own")}
        description={chosenBy === "household" ? t("egress.byHousehold") : chosenBy === "admin" ? t("egress.byAdmin") : t("egress.ownHint")}
        value={egress.own}
        locked={chosenBy !== null}
        save={async (policy) => {
          const stored = unwrap(await api.PUT("/me/egress-policy", { body: { policy } }));
          await queries.invalidateQueries({ queryKey: MODELS });
          return stored.own;
        }}
      />
    </div>
  );
}

/** The household's policy, among its models. */
export function HouseholdEgressSection() {
  const { t } = useTranslation();
  const models = useModels();
  const queries = useQueryClient();
  const egress = models.data?.egress;
  if (!egress) return null;
  return (
    <section>
      <h2 className="mb-1 text-base font-bold">{t("egress.title")}</h2>
      <p className="mb-3.5 max-w-[62ch] text-sm text-muted">{t("egress.householdHint")}</p>
      <SavingSwitch
        label={t("egress.everyone")}
        value={egress.household}
        save={async (policy) => {
          const stored = unwrap(await api.PUT("/tenant/egress-policy", { body: { policy } }));
          await queries.invalidateQueries({ queryKey: MODELS });
          return stored.policy;
        }}
      />
    </section>
  );
}

/** A household admin's choice for one user, with that user's tool permissions. */
export function UserEgressSwitch({ userId }: { userId: string }) {
  const { t } = useTranslation();
  const queries = useQueryClient();
  const stored = useQuery({
    queryKey: ["tenant", "users", userId, "egress-policy"],
    queryFn: async () => unwrap(await api.GET("/tenant/users/{user_id}/egress-policy", { params: { path: { user_id: userId } } })),
  });
  if (!stored.data) return null;
  return (
    <SavingSwitch
      label={t("egress.forUser")}
      description={t("egress.forUserHint")}
      value={stored.data.policy}
      save={async (policy) => {
        const saved = unwrap(await api.PUT("/tenant/users/{user_id}/egress-policy", { params: { path: { user_id: userId } }, body: { policy } }));
        await queries.invalidateQueries({ queryKey: MODELS });
        return saved.policy;
      }}
    />
  );
}
