// Conversations through the API (API-003, CNV-004, MOD-012).
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type Conversation, type ListEntry, type ModelChoice } from "./api/client";

export const CONVERSATIONS = ["conversations"] as const;

/** Folders and conversations as one list, pinned first, then newest (CNV-008). */
export function useConversationList() {
  return useQuery({
    queryKey: CONVERSATIONS,
    queryFn: async () => {
      const items: ListEntry[] = [];
      let cursor: string | undefined;
      do {
        const query = cursor === undefined ? { limit: 100 } : { limit: 100, cursor };
        const page = unwrap(await api.GET("/conversation-list", { params: { query } }));
        items.push(...page.items);
        cursor = page.next_cursor ?? undefined;
      } while (cursor !== undefined);
      return items;
    },
  });
}

export async function createFolder(name: string) {
  return unwrap(await api.POST("/folders", { body: { name } }));
}

export async function updateFolder(id: string, body: { name?: string; pinned?: boolean; collapsed?: boolean }) {
  return unwrap(await api.PATCH("/folders/{folder_id}", { params: { path: { folder_id: id } }, body }));
}

export async function deleteFolder(id: string): Promise<void> {
  const result = await api.DELETE("/folders/{folder_id}", { params: { path: { folder_id: id } } });
  if (!result.response.ok) unwrap(result);
}

/** A new conversation from a copy of this one up to `runId` (CNV-005). */
export async function forkConversation(id: string, runId: string): Promise<Conversation> {
  return unwrap(await api.POST("/conversations/{conversation_id}/fork", { params: { path: { conversation_id: id } }, body: { run_id: runId } }));
}

export async function createConversation(model?: ModelChoice): Promise<Conversation> {
  return unwrap(await api.POST("/conversations", { body: model === undefined ? {} : { model } }));
}

export async function updateConversation(
  id: string,
  body: { title?: string; archived?: boolean; model?: ModelChoice; folder_id?: string | null; pinned?: boolean },
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

export function useConversation(id: string) {
  return useQuery({
    queryKey: ["conversation", id, "details"],
    queryFn: async () => unwrap(await api.GET("/conversations/{conversation_id}", { params: { path: { conversation_id: id } } })),
  });
}
