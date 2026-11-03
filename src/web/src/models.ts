// The models of the household and the model of a conversation (MOD-010 to MOD-012, MOD-014, UX-015).
import { useQuery } from "@tanstack/react-query";

import { api, unwrap, type ModelChoice, type ModelOption } from "./api/client";

export const MODELS = ["models"] as const;

export function useModels() {
  return useQuery({ queryKey: MODELS, queryFn: async () => unwrap(await api.GET("/models")) });
}

export function sameModel(option: ModelOption, choice: ModelChoice | null | undefined): boolean {
  return choice != null && option.connection_id === choice.connection_id && option.model === choice.model;
}

export function findModel(options: ModelOption[] | undefined, choice: ModelChoice | null | undefined): ModelOption | undefined {
  return options?.find((option) => sameModel(option, choice));
}

/** A price per million tokens, as short as it can be: `0.27`, `2.5`, `15`. */
export function shortPrice(value: string): string {
  const number = Number(value);
  return number >= 1 ? String(Number(number.toFixed(2))) : String(Number(number.toPrecision(2)));
}
