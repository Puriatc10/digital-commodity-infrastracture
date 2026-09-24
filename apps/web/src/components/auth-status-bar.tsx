"use client";

import { useAuth } from "@/lib/auth-context";
import type { Messages } from "@/i18n/messages";

export function AuthStatusBar({ messages }: { messages: Messages["session"] }) {
  const { state, setOrganization } = useAuth();
  const roleLabel = (role: string) => messages.roles[role as keyof typeof messages.roles] ?? role;

  if (state.status === "loading") {
    return <span className="text-muted-foreground text-xs">{messages.loading}</span>;
  }

  if (state.status === "unauthenticated") {
    return <span className="text-muted-foreground text-xs">{messages.unauthenticated}</span>;
  }

  if (state.status === "error") {
    return <span className="text-destructive text-xs">{messages.error}</span>;
  }

  if (state.status === "authenticated") {
    const orgOptions = state.availableOrganizations.map(o => (
      <option key={o.organization.id} value={o.organization.id}>
        {o.organization.name} ({roleLabel(o.role)})
      </option>
    ));

    return (
      <div className="flex items-center gap-3">
        {state.systemRoles.length > 0 && (
          <span className="rounded-md bg-destructive/10 text-destructive px-2 py-1 font-medium text-xs">
            {state.systemRoles.map(roleLabel).join("، ")}
          </span>
        )}
        <span className="text-muted-foreground font-medium text-xs">
          <bdi dir="ltr">{state.user.email}</bdi>
        </span>
        {state.availableOrganizations.length > 0 ? (
          <select
            aria-label={messages.organization}
            className="rounded-md border border-border bg-card px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-primary"
            value={state.currentOrganization?.organization.id || ""}
            onChange={(e) => setOrganization(e.target.value)}
          >
            {orgOptions}
          </select>
        ) : (
          <span className="text-muted-foreground text-xs">{messages.noOrganization}</span>
        )}
      </div>
    );
  }

  return null;
}
