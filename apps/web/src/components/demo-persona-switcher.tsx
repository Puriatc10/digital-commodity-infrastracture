"use client";

import { useState, useEffect } from "react";
import { apiClient, bootstrapCsrf } from "@/lib/api/client";
import type { components } from "@/lib/api/generated/schema";
import type { Messages } from "@/i18n/messages";
import { saveOrganizationPreference } from "@/lib/organization-preference";

type AllowedPersona = components["schemas"]["DemoPersonaSwitcherRequest"]["persona"];

export function DemoPersonaSwitcher({ messages }: { messages: Messages["session"] }) {
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(false);
  const [personas, setPersonas] = useState<AllowedPersona[]>([]);

  const [failed, setFailed] = useState(false);

  useEffect(() => {
    async function checkEnabled() {
      try {
        const { data, error } = await apiClient.GET("/api/auth/demo-switch", {});
        if (data && !error && Array.isArray(data)) {
          setEnabled(true);
          setPersonas(data as AllowedPersona[]);
        }
      } catch {
        // Disabled or backend unreachable
      }
    }
    checkEnabled();
  }, []);

  if (!enabled) {
    return null;
  }

  const handleSwitch = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const persona = e.target.value as AllowedPersona;
    if (!persona) return;

    setLoading(true);
    setFailed(false);
    try {
      await bootstrapCsrf();
      const { data, error } = await apiClient.POST("/api/auth/demo-switch", {
        body: { persona }
      });

      if (!error && data) {
        if (typeof window !== "undefined") {
          saveOrganizationPreference(null);
          window.location.reload();
        }
      } else setFailed(true);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
        {messages.demoPersona}
      </span>
      <select
        aria-label={messages.demoPersona}
        className="rounded-md border border-primary/20 bg-primary/10 text-primary px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-primary"
        onChange={handleSwitch}
        disabled={loading}
        value=""
      >
        <option value="" disabled>{messages.selectPersona}</option>
        {personas.map(p => (
          <option key={p} value={p}>
            {messages.roles[p]}
          </option>
        ))}
      </select>
      {failed && <span role="alert" className="text-xs text-destructive">{messages.switchError}</span>}
    </div>
  );
}
