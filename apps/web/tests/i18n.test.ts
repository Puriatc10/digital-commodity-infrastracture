import { describe, it, expect } from "vitest";
import { isEnabledLocale, defaultLocale, locales, enabledLocales } from "@/i18n/config";

describe("i18n config", () => {
  it("recognizes enabled locale 'fa'", () => {
    expect(isEnabledLocale("fa")).toBe(true);
  });

  it("rejects non-enabled or unknown locales", () => {
    expect(isEnabledLocale("en")).toBe(false);
    expect(isEnabledLocale("fr")).toBe(false);
    expect(isEnabledLocale("")).toBe(false);
    expect(isEnabledLocale("ar")).toBe(false);
  });

  it("handles case-sensitivity and whitespace padding correctly", () => {
    expect(isEnabledLocale("FA")).toBe(false);
    expect(isEnabledLocale("Fa")).toBe(false);
    expect(isEnabledLocale(" fa ")).toBe(false);
    expect(isEnabledLocale("fa\n")).toBe(false);
  });

  it("has defaultLocale configured as 'fa'", () => {
    expect(defaultLocale).toBe("fa");
    expect(enabledLocales).toContain("fa");
  });

  it("configures RTL direction for Persian and LTR for English", () => {
    expect(locales.fa.direction).toBe("rtl");
    expect(locales.en.direction).toBe("ltr");
  });
});
