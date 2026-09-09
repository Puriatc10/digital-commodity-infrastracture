import fa from "./messages/fa";
import type { EnabledLocale } from "./config";

export type Messages = typeof fa;

const dictionaries: Record<EnabledLocale, Messages> = { fa };

export function getMessages(locale: EnabledLocale): Messages {
  return dictionaries[locale];
}
