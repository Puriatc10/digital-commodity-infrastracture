import createClient from "openapi-fetch";
import type { paths } from "./generated/schema";

const ORG_PREF_KEY = "commodity_platform_pref_org_id";

// Next's local proxy or the production ingress routes same-origin /api to Django.
export const apiClient = createClient<paths>({
  baseUrl: typeof window === "undefined" ? process.env.API_PROXY_TARGET : window.location.origin,
  credentials: "include",
});

apiClient.use({
  onRequest({ request }) {
    if (typeof document !== "undefined") {
      if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) {
        const token = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1];
        if (token) request.headers.set("X-CSRFToken", token);
      }
      try {
        const orgId = typeof localStorage !== "undefined" ? localStorage.getItem(ORG_PREF_KEY) : null;
        if (orgId && !request.headers.has("X-Organization-Id")) {
          request.headers.set("X-Organization-Id", orgId);
        }
      } catch {
        // Storage access unavailable
      }
    }
    return request;
  },
});

export async function bootstrapCsrf() {
  const { response } = await apiClient.GET("/api/auth/csrf");
  if (!response.ok) throw new Error("CSRF bootstrap failed");
}
