// Conversations through the API (API-003, CNV-004, MOD-012).
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type Conversation, type ModelChoice } from "./api/client";

export const CONVERSATIONS = ["conversations"] as const;

export function useConversations() {
  return useQuery({
    queryKey: CONVERSATIONS,
    queryFn: async () => unwrap(await api.GET("/conversations", { params: { query: { limit: 100 } } })).items,
  });
}

export async function createConversation(model?: ModelChoice): Promise<Conversation> {
  return unwrap(await api.POST("/conversations", { body: model === undefined ? {} : { model } }));
}

export async function updateConversation(
  id: string,
  body: { title?: string; archived?: boolean; model?: ModelChoice },
): Promise<Conversation> {
  return unwrap(await api.PATCH("/conversations/{conversation_id}", { params: { path: { conversation_id: id } }, body }));
}

/** Make `runId` the last run, deleting the runs after it; `null` deletes every run (ADR-0068). */
export async function rewindConversation(id: string, runId: string | null): Promise<Conversation> {
  return unwrap(
    await api.POST("/conversations/{conversation_id}/rewind", {
      params: { path: { conversation_id: id } },
      body: { run_id: runId },
    }),
  );
}

export async function deleteConversation(id: string): Promise<void> {
  const result = await api.DELETE("/conversations/{conversation_id}", { params: { path: { conversation_id: id } } });
  if (!result.response.ok) unwrap(result);
}

export function useRefreshConversations(): () => Promise<void> {
  const queries = useQueryClient();
  return () => queries.invalidateQueries({ queryKey: CONVERSATIONS });
}
