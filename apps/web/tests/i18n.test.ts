import { describe, it, expect } from "vitest";
import { isEnabledLocale, defaultLocale, locales, enabledLocales, type EnabledLocale } from "@/i18n/config";

describe("i18n config", () => {
  describe("isEnabledLocale", () => {
    it("returns true for enabled locale 'fa'", () => {
      const input: string = "fa";
      expect(isEnabledLocale(input)).toBe(true);

      // Verify TypeScript type narrowing
      if (isEnabledLocale(input)) {
        const enabled: EnabledLocale = input;
        expect(enabled).toBe("fa");
      } else {
        throw new Error("Expected isEnabledLocale('fa') to narrow to EnabledLocale");
      }
    });

    it("returns false for valid locales that are not enabled", () => {
      expect(isEnabledLocale("en")).toBe(false);
    });

    it("returns false for unknown or arbitrary string inputs", () => {
      expect(isEnabledLocale("fr")).toBe(false);
      expect(isEnabledLocale("ar")).toBe(false);
      expect(isEnabledLocale("es")).toBe(false);
      expect(isEnabledLocale("de")).toBe(false);
    });

    it("returns false for empty string", () => {
      expect(isEnabledLocale("")).toBe(false);
    });

    it("is strictly case-sensitive and rejects upper/mixed case strings", () => {
      expect(isEnabledLocale("FA")).toBe(false);
      expect(isEnabledLocale("Fa")).toBe(false);
      expect(isEnabledLocale("EN")).toBe(false);
    });

    it("rejects strings with leading or trailing whitespace", () => {
      expect(isEnabledLocale(" fa")).toBe(false);
      expect(isEnabledLocale("fa ")).toBe(false);
      expect(isEnabledLocale(" fa ")).toBe(false);
      expect(isEnabledLocale("fa\n")).toBe(false);
      expect(isEnabledLocale("\tfa")).toBe(false);
    });

    it("rejects locale strings with region or script subtags", () => {
      expect(isEnabledLocale("fa-IR")).toBe(false);
      expect(isEnabledLocale("fa_IR")).toBe(false);
      expect(isEnabledLocale("en-US")).toBe(false);
      expect(isEnabledLocale("fa-Arab")).toBe(false);
    });

    it("rejects Object prototype property names", () => {
      expect(isEnabledLocale("toString")).toBe(false);
      expect(isEnabledLocale("__proto__")).toBe(false);
      expect(isEnabledLocale("constructor")).toBe(false);
      expect(isEnabledLocale("valueOf")).toBe(false);
      expect(isEnabledLocale("hasOwnProperty")).toBe(false);
    });
  });

  describe("defaultLocale and locales metadata", () => {
    it("has defaultLocale configured as 'fa'", () => {
      expect(defaultLocale).toBe("fa");
      expect(enabledLocales).toContain("fa");
    });

    it("configures RTL direction for Persian and LTR for English", () => {
      expect(locales.fa.direction).toBe("rtl");
      expect(locales.en.direction).toBe("ltr");
    });
  });
});
