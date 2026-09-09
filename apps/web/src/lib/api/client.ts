import createClient from "openapi-fetch";
import type { paths } from "./generated/schema";

/**
 * Minimal generic client foundation for consuming the generated API contract.
 * Ensure NEXT_PUBLIC_API_BASE_URL is set in the environment.
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;

if (!API_BASE_URL) {
  throw new Error("Set NEXT_PUBLIC_API_BASE_URL before importing the API client.");
}

export const apiClient = createClient<paths>({
  fetch: (url: RequestInfo | URL, init?: RequestInit) => {
    const options = init || {};
    options.credentials = "include";

    // Extract CSRF token from cookies for state-changing requests
    if (
      typeof window !== "undefined" &&
      options.method &&
      ["POST", "PUT", "PATCH", "DELETE"].includes(options.method.toUpperCase())
    ) {
      const match = document.cookie.match(new RegExp("(^| )csrftoken=([^;]+)"));
      if (match && match[2]) {
        options.headers = {
          ...options.headers,
          "X-CSRFToken": match[2],
        };
      }
    }

    return fetch(url, options);
  },
  baseUrl: API_BASE_URL,
});
