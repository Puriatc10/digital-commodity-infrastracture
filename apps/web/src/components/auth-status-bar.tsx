"use client";

import { useAuth } from "@/lib/auth-context";

export function AuthStatusBar() {
  const { state, setOrganization } = useAuth();

  if (state.status === "loading") {
    return <span className="text-muted-foreground text-xs">Loading...</span>;
  }

  if (state.status === "unauthenticated") {
    return <span className="text-muted-foreground text-xs">Not logged in</span>;
  }

  if (state.status === "error") {
    return <span className="text-destructive text-xs">Auth Error</span>;
  }

  if (state.status === "authenticated") {
    const orgOptions = state.availableOrganizations.map(o => (
      <option key={o.organization.id} value={o.organization.id}>
        {o.organization.name} ({o.role})
      </option>
    ));

    return (
      <div className="flex items-center gap-3">
        {state.systemRoles.length > 0 && (
          <span className="rounded-md bg-destructive/10 text-destructive px-2 py-1 font-medium text-xs">
            {state.systemRoles.join(", ")}
          </span>
        )}
        <span className="text-muted-foreground font-medium text-xs">{state.user.email}</span>
        {state.availableOrganizations.length > 0 ? (
          <select
            className="rounded-md border border-border bg-card px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-primary"
            value={state.currentOrganization?.organization.id || ""}
            onChange={(e) => setOrganization(e.target.value)}
          >
            {orgOptions}
          </select>
        ) : (
          <span className="text-muted-foreground text-xs">No Organization</span>
        )}
      </div>
    );
  }

  return null;
}
