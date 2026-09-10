import createClient from "openapi-fetch";
import type { paths } from "./generated/schema";

// Next's local proxy or the production ingress routes same-origin /api to Django.
export const apiClient = createClient<paths>({
  baseUrl: typeof window === "undefined" ? process.env.API_PROXY_TARGET : window.location.origin,
  credentials: "include",
});

apiClient.use({
  onRequest({ request }) {
    if (typeof document !== "undefined" && !["GET", "HEAD", "OPTIONS"].includes(request.method)) {
      const token = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1];
      if (token) request.headers.set("X-CSRFToken", token);
    }
    return request;
  },
});

export async function bootstrapCsrf() {
  const { response } = await apiClient.GET("/api/auth/csrf");
  if (!response.ok) throw new Error("CSRF bootstrap failed");
}
