export const locales = {
  fa: { direction: "rtl" },
  en: { direction: "ltr" },
} as const;

export type Locale = keyof typeof locales;
export const enabledLocales = ["fa"] as const satisfies readonly Locale[];
export type EnabledLocale = (typeof enabledLocales)[number];
export const defaultLocale: EnabledLocale = "fa";

export function isEnabledLocale(value: string): value is EnabledLocale {
  return enabledLocales.some((locale) => locale === value);
}
