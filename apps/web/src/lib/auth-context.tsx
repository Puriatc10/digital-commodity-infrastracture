"use client";

import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { apiClient } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";

type User = components["schemas"]["User"];
type OrganizationContext = components["schemas"]["OrganizationContext"];

type AuthState =
  | { status: "loading" }
  | { status: "unauthenticated" }
  | { status: "error"; error: Error }
  | {
      status: "authenticated";
      user: User;
      systemRoles: string[];
      availableOrganizations: OrganizationContext[];
      currentOrganization: OrganizationContext | null;
    };

interface AuthContextValue {
  state: AuthState;
  setOrganization: (organizationId: string) => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const ORG_PREF_KEY = "commodity_platform_pref_org_id";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  const loadUser = useCallback(async (isInitial = false) => {
    if (!isInitial) setState({ status: "loading" });
    try {
      const { data, error } = await apiClient.GET("/api/auth/me");
      if (error || !data) {
        setState({ status: "unauthenticated" });
        return;
      }

      const availableOrganizations = data.organizations || [];
      const systemRoles = data.system_roles || [];

      let currentOrganization: OrganizationContext | null = null;
      if (availableOrganizations.length === 1) {
        currentOrganization = availableOrganizations[0];
      } else if (availableOrganizations.length > 1) {
        const savedId = typeof window !== "undefined" ? localStorage.getItem(ORG_PREF_KEY) : null;
        if (savedId) {
          const match = availableOrganizations.find((o) => o.organization.id === savedId);
          if (match) {
            currentOrganization = match;
          }
        }
        if (!currentOrganization) {
          currentOrganization = availableOrganizations[0];
        }
      }

      setState({
        status: "authenticated",
        user: data,
        systemRoles,
        availableOrganizations,
        currentOrganization,
      });
    } catch (err) {
      setState({ status: "error", error: err instanceof Error ? err : new Error("Failed to authenticate") });
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadUser(true);
  }, [loadUser]);

  const setOrganization = useCallback(
    (organizationId: string) => {
      setState((prev) => {
        if (prev.status !== "authenticated") return prev;

        const org = prev.availableOrganizations.find((o) => o.organization.id === organizationId);
        if (org) {
          if (typeof window !== "undefined") {
            localStorage.setItem(ORG_PREF_KEY, organizationId);
          }
          return { ...prev, currentOrganization: org };
        }
        return prev;
      });
    },
    []
  );

  return (
    <AuthContext.Provider value={{ state, setOrganization, refresh: loadUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
