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
  baseUrl: API_BASE_URL,
});
