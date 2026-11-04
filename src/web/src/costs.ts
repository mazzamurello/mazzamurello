// Costs, from the cost ledger (MOD-007, UX-008, ADR-0073).
import { useQuery } from "@tanstack/react-query";

import { api, unwrap, type Money } from "./api/client";

export const USAGE = ["usage"] as const;

export function useUsage() {
  return useQuery({ queryKey: USAGE, queryFn: async () => unwrap(await api.GET("/me/usage")) });
}

/** Amounts per currency, shortly: `$0.00042`, `$1.25`, or `€2 · $1`. */
export function formatMoney(amounts: Money[] | null | undefined): string {
  const shown = (amounts ?? []).filter((item) => Number(item.amount) !== 0);
  if (shown.length === 0) return "$0";
  return shown
    .map((item) => {
      const value = Number(item.amount);
      const text = value >= 0.01 ? value.toFixed(2) : String(Number(value.toPrecision(2)));
      return item.currency === "USD" ? `$${text}` : `${text} ${item.currency}`;
    })
    .join(" · ");
}

/** Whether anything was paid: local models cost nothing and show no cost. */
export function isPaid(amounts: Money[] | null | undefined): boolean {
  return (amounts ?? []).some((item) => Number(item.amount) !== 0);
}
