// Conversations through the API (API-003).
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type Conversation } from "./api/client";

export const CONVERSATIONS = ["conversations"] as const;

export function useConversations() {
  return useQuery({
    queryKey: CONVERSATIONS,
    queryFn: async () => unwrap(await api.GET("/conversations", { params: { query: { limit: 100 } } })).items,
  });
}

export async function createConversation(): Promise<Conversation> {
  return unwrap(await api.POST("/conversations", { body: {} }));
}

export async function updateConversation(
  id: string,
  body: { title?: string; archived?: boolean; active_run_id?: string | null },
): Promise<Conversation> {
  return unwrap(await api.PATCH("/conversations/{conversation_id}", { params: { path: { conversation_id: id } }, body }));
}

export async function deleteConversation(id: string): Promise<void> {
  const result = await api.DELETE("/conversations/{conversation_id}", { params: { path: { conversation_id: id } } });
  if (!result.response.ok) unwrap(result);
}

export function useRefreshConversations(): () => Promise<void> {
  const queries = useQueryClient();
  return () => queries.invalidateQueries({ queryKey: CONVERSATIONS });
}
