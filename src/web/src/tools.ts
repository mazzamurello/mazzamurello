// The assistant's tools, what applies to each for the user, and how a call was decided (AGT-002, UX-023, ADR-0090).
import { useQuery } from "@tanstack/react-query";
import type { TFunction } from "i18next";

import { api, unwrap, type ApprovalOutcome, type ApprovalScope, type ToolName } from "./api/client";

export const TOOLS = ["tools"] as const;

/** Every tool, with its classes and what applies to it for the user. */
export function useTools() {
  return useQuery({ queryKey: TOOLS, queryFn: async () => unwrap(await api.GET("/tools")).items });
}

/** The tools the user's household admin turned off: switched off and locked (CNV-013). */
export function useLockedTools(): Set<ToolName> {
  const tools = useTools();
  return new Set((tools.data ?? []).filter((tool) => tool.effective === "deny").map((tool) => tool.name));
}

/** A tool's label, or its own name for a tool without one, such as the output limits' (ADR-0090). */
export function toolLabel(t: TFunction, name: string): string {
  return t(`assistant.toolNames.${name}`, { defaultValue: name });
}

/** How a call was decided, in a few words (UX-023). */
export function outcomeLabel(t: TFunction, outcome: ApprovalOutcome, scope: ApprovalScope | null | undefined): string {
  if ((outcome === "approved" || outcome === "allowed") && scope === "conversation") return t("approvals.outcomes.inChat");
  if ((outcome === "approved" || outcome === "allowed") && scope === "turn") return t("approvals.outcomes.forTurn");
  return t(`approvals.outcomes.${outcome}`);
}
