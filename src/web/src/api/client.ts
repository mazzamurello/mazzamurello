// The public API (API-001), typed from the committed contract (ADR-0008).
import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Conversation = Schemas["Conversation"];
export type MessagePage = Schemas["MessagePage"];
export type PathRun = Schemas["PathRun"];
export type Run = Schemas["Run"];
export type User = Schemas["User"];
export type Connection = Schemas["Connection"];
export type ConnectionTest = Schemas["ConnectionTest"];
export type ModelOption = Schemas["ModelOption"];
export type ModelChoice = Schemas["ModelChoice"];
export type Folder = Schemas["Folder"];
export type ListEntry = Schemas["ConversationListEntry"];
export type Money = Schemas["Money"];
export type SearchResult = Schemas["SearchResult"];
export type Problem = Schemas["Problem"];
export type UserSettings = Schemas["UserSettings"];
export type UserSettingsView = Schemas["UserSettingsView"];
export type Reasoning = Schemas["Reasoning"];
export type ToolName = Schemas["ToolName"];
export type Interrupt = Schemas["Interrupt"];
export type Question = Schemas["Question"];
export type PlanStep = Schemas["PlanStep"];

export const API_BASE = "/v1";

// Every request carries this header: the session cookie authenticates a change
// only with it, and a cross-site request cannot set it (AUTH-005).
export const REQUEST_HEADER = { "X-Mazzamurello-Request": "1" };

export const api = createClient<paths>({
  baseUrl: API_BASE,
  credentials: "same-origin",
  headers: REQUEST_HEADER,
});

/** An error answer of the API, with its stable code (API-007). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    // The rest of the problem, such as the result of a failed connection test.
    readonly problem: Partial<Problem> & Record<string, unknown> = {},
  ) {
    super(code);
  }
}

/** The data of a successful answer, or else an `ApiError`. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    const problem = (result.error ?? {}) as Partial<Problem> & Record<string, unknown>;
    throw new ApiError(result.response.status, problem.code ?? "internal.error", problem);
  }
  return result.data;
}
