import type { components } from "./api/generated/schema";

type OrganizationContext = components["schemas"]["OrganizationContext"];
const ORG_PREF_KEY = "commodity_platform_pref_org_id";

export function readOrganizationPreference(): string | null {
  try { return localStorage.getItem(ORG_PREF_KEY); } catch { return null; }
}

export function saveOrganizationPreference(id: string | null) {
  try {
    if (id) localStorage.setItem(ORG_PREF_KEY, id);
    else localStorage.removeItem(ORG_PREF_KEY);
  } catch { /* Storage is an optional preference, never an authentication dependency. */ }
}

export function selectOrganization(organizations: OrganizationContext[], savedId: string | null) {
  return organizations.find((org) => org.organization.id === savedId) ?? organizations[0] ?? null;
}
