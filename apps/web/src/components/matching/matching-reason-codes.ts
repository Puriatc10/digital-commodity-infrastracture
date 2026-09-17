import { getMessages } from "@/i18n/messages";
import type { EnabledLocale } from "@/i18n/config";

/**
 * Localize backend reason codes to human-readable Persian descriptions.
 * Provides a clean fallback for unexpected or future reason codes.
 */
export function getLocalizedReason(
  reasonCode: string | undefined | null,
  locale: EnabledLocale = "fa"
): string {
  if (!reasonCode) return "";

  const messages = getMessages(locale);
  const reasonMap = messages.matching.reasonCodes as Record<string, string>;

  if (reasonCode in reasonMap) {
    return reasonMap[reasonCode];
  }

  // Graceful fallback for unexpected future codes without exposing ugly raw internals
  const humanized = reasonCode
    .toLowerCase()
    .replace(/^spec_/, "")
    .replace(/^trust_/, "")
    .replace(/^geography_/, "")
    .replace(/^quantity_/, "")
    .replace(/^availability_/, "")
    .replace(/_/g, " ");

  return humanized.charAt(0).toUpperCase() + humanized.slice(1);
}
