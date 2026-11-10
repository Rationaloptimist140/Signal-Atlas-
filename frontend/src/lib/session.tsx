"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import useSWR, { type SWRConfiguration } from "swr";
import { api, buildUrl, fetcher, setCsrfToken, type Params } from "@/lib/api";
import type { Me } from "@/lib/types";

export type SourceMode = "auto" | "live" | "demo";

type SessionValue = {
  me: Me | undefined;
  loading: boolean;
  refresh: () => Promise<unknown>;
  source: SourceMode;
  setSource: (mode: SourceMode) => void;
  canEdit: boolean;
  isAdmin: boolean;
};

const SessionContext = createContext<SessionValue | null>(null);
const SOURCE_KEY = "signal-atlas:source";

export function SessionProvider({ children }: { children: ReactNode }) {
  const { data: me, isLoading, mutate } = useSWR<Me>("/auth/me", fetcher, { revalidateOnFocus: false, shouldRetryOnError: false });
  const [source, setSourceState] = useState<SourceMode>("auto");

  useEffect(() => {
    const stored = window.localStorage.getItem(SOURCE_KEY);
    if (stored === "live" || stored === "demo" || stored === "auto") setSourceState(stored);
  }, []);

  useEffect(() => {
    if (me?.csrf_token) setCsrfToken(me.csrf_token);
  }, [me?.csrf_token]);

  const setSource = useCallback((mode: SourceMode) => {
    setSourceState(mode);
    window.localStorage.setItem(SOURCE_KEY, mode);
  }, []);

  const value = useMemo<SessionValue>(
    () => ({
      me,
      loading: isLoading,
      refresh: () => mutate(),
      source,
      setSource,
      canEdit: !!me && me.role !== "viewer",
      isAdmin: !!me && (me.role === "owner" || me.role === "admin"),
    }),
    [me, isLoading, mutate, source, setSource],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>");
  return value;
}

/** SWR hook for intelligence endpoints: automatically applies the live/demo source filter. */
export function useIntel<T>(path: string | null, params?: Params, config?: SWRConfiguration<T>) {
  const { source } = useSession();
  const key = path ? buildUrl(path, { ...params, source }).replace(/^\/api\/v1/, "") : null;
  return useSWR<T>(key, fetcher, { revalidateOnFocus: false, keepPreviousData: true, ...config });
}

/** SWR hook for tenant endpoints (no source filter). */
export function useApi<T>(path: string | null, params?: Params, config?: SWRConfiguration<T>) {
  const key = path ? buildUrl(path, params).replace(/^\/api\/v1/, "") : null;
  return useSWR<T>(key, fetcher, { revalidateOnFocus: false, ...config });
}

export async function logout() {
  try {
    await api("/auth/logout", { method: "POST" });
  } finally {
    setCsrfToken(null);
    window.location.assign("/login");
  }
}
