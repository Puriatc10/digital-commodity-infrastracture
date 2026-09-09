"use client";

import { useState, useEffect } from "react";
import { apiClient } from "@/lib/api/client";

type AllowedPersona = "buyer" | "supplier" | "broker" | "operator" | "admin";

export function DemoPersonaSwitcher() {
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(false);
  const [personas, setPersonas] = useState<AllowedPersona[]>([]);

  const ORG_PREF_KEY = "commodity_platform_pref_org_id";

  useEffect(() => {
    async function checkEnabled() {
      try {
        const { data, error } = await apiClient.GET("/api/auth/demo-switch");
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
    try {
      const { data, error } = await apiClient.POST("/api/auth/demo-switch", {
        body: { persona }
      });

      if (!error && data) {
        if (typeof window !== "undefined") {
          localStorage.removeItem(ORG_PREF_KEY);
          window.location.reload();
        }
      }
    } catch (err) {
      console.error("Failed to switch persona", err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
        Demo Persona
      </span>
      <select
        className="rounded-md border border-primary/20 bg-primary/10 text-primary px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-primary"
        onChange={handleSwitch}
        disabled={loading}
        value=""
      >
        <option value="" disabled>Select...</option>
        {personas.map(p => (
          <option key={p} value={p}>
            {p.charAt(0).toUpperCase() + p.slice(1)}
          </option>
        ))}
      </select>
    </div>
  );
}
