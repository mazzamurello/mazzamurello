// The signed-in user, from the session cookie (ADR-0067).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";

import { ApiError, api, unwrap, type User } from "./api/client";

export const ME = ["me"] as const;

/** The signed-in user, `null` when there is no session, `undefined` while loading. */
export function useMe(): User | null | undefined {
  const query = useQuery({
    queryKey: ME,
    queryFn: async () => {
      try {
        return unwrap(await api.GET("/me"));
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
  });
  return query.data;
}

export function useSignOut(): () => Promise<void> {
  const queries = useQueryClient();
  const navigate = useNavigate();
  return async () => {
    await api.POST("/auth/logout");
    // Clearing the cache would detach the app from the user it shows:
    // forget the user first, which shows the sign-in page, then the rest.
    queries.setQueryData(ME, null);
    queries.removeQueries({ predicate: (query) => query.queryKey[0] !== ME[0] });
    await navigate("/");
  };
}
