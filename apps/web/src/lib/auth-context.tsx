"use client";

import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import { readOrganizationPreference, saveOrganizationPreference, selectOrganization } from "./organization-preference";

type User = components["schemas"]["User"];
type OrganizationContext = components["schemas"]["OrganizationContext"];

type AuthState =
  | { status: "loading" }
  | { status: "unauthenticated" }
  | { status: "error"; error: Error }
  | { status: "authenticated"; user: User; systemRoles: string[]; availableOrganizations: OrganizationContext[]; currentOrganization: OrganizationContext | null };

interface AuthContextValue {
  state: AuthState;
  setOrganization: (organizationId: string) => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });
  const requestVersion = useRef(0);
  const previousUser = useRef<number | null>(null);

  const loadUser = useCallback(async () => {
    const version = ++requestVersion.current;
    try {
      const { data, response } = await apiClient.GET("/api/auth/me");
      if (version !== requestVersion.current) return;
      if (response.status === 401 || response.status === 403) {
        previousUser.current = null;
        saveOrganizationPreference(null);
        setState({ status: "unauthenticated" });
        return;
      }
      if (!response.ok || !data) throw new Error("Session request failed");

      const changedUser = previousUser.current !== null && previousUser.current !== data.id;
      const currentOrganization = selectOrganization(data.organizations, changedUser ? null : readOrganizationPreference());
      saveOrganizationPreference(currentOrganization?.organization.id ?? null);
      previousUser.current = data.id;
      setState({ status: "authenticated", user: data, systemRoles: data.system_roles, availableOrganizations: data.organizations, currentOrganization });
    } catch (err) {
      if (version !== requestVersion.current) return;
      setState({ status: "error", error: err instanceof Error ? err : new Error("Session request failed") });
    }
  }, []);

  useEffect(() => {
    // Refresh on return to the page and periodically so expired sessions lose UX privileges.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadUser();
    const onFocus = () => { void loadUser(); };
    window.addEventListener("focus", onFocus);
    const interval = window.setInterval(onFocus, 60_000);
    return () => {
      // This is a request counter, not a DOM ref: invalidate the latest request.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      ++requestVersion.current;
      window.removeEventListener("focus", onFocus);
      window.clearInterval(interval);
    };
  }, [loadUser]);

  const setOrganization = useCallback((organizationId: string) => {
    if (state.status !== "authenticated") return;
    const org = state.availableOrganizations.find((o) => o.organization.id === organizationId);
    if (!org) return;
    saveOrganizationPreference(organizationId);
    setState({ ...state, currentOrganization: org });
  }, [state]);

  return <AuthContext.Provider value={{ state, setOrganization, refresh: loadUser }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) throw new Error("useAuth must be used within an AuthProvider");
  return context;
}
