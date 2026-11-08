// Temporary conversations: deleted when their user leaves them or signs out (CNV-011, ADR-0082).
import { useEffect } from "react";
import { useLocation } from "react-router";

import { api } from "./api/client";

const RETRIES = 10;
const RETRY_MS = 500;

// The temporary conversation open now, if any.
let open: string | null = null;

/** The open conversation is temporary: it goes when its user leaves it. */
export function openTemporary(id: string) {
  open = id;
}

/** Delete a temporary conversation, stopping its run first: a run in progress keeps it. */
async function discard(id: string) {
  for (let attempt = 0; attempt < RETRIES; attempt++) {
    const result = await api.DELETE("/conversations/{conversation_id}", { params: { path: { conversation_id: id } } });
    if (result.response.ok || result.response.status === 404) return;
    if (result.response.status !== 409) break;
    const conversation = await api.GET("/conversations/{conversation_id}", { params: { path: { conversation_id: id } } });
    const run = conversation.data?.active_run_id;
    if (run) await api.POST("/runs/{run_id}/cancel", { params: { path: { run_id: run } } });
    await new Promise((resolve) => setTimeout(resolve, RETRY_MS));
  }
  // The worker deletes it a day after its last activity.
}

/** Delete the open temporary conversation now, as before signing out. */
export async function discardOpenTemporary() {
  const id = open;
  open = null;
  if (id !== null) await discard(id);
}

/** Leaving the open temporary conversation for another screen deletes it; a reload does not. */
export function useLeavingTemporary() {
  const { pathname } = useLocation();
  useEffect(() => {
    if (open !== null && pathname !== `/c/${open}`) void discardOpenTemporary();
  }, [pathname]);
}
