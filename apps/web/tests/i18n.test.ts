import { describe, it, expect } from "vitest";
import { isEnabledLocale, defaultLocale, locales, enabledLocales, type EnabledLocale } from "@/i18n/config";
import { getMessages } from "@/i18n/messages";

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

describe("Persian Messages Bundle (fa)", () => {
  const messages = getMessages("fa");

  it("contains all required top-level domain sections", () => {
    const requiredSections = [
      "session",
      "metadata",
      "shell",
      "foundation",
      "tradeHub",
      "rfqBuilder",
      "rfqWorkspace",
      "supplyListingBuilder",
      "supplyListingDetail",
      "opportunities",
      "matching",
      "dealsList",
      "dealWorkspace",
      "directory",
      "verification",
    ];

    const msgRecord = messages as unknown as Record<string, unknown>;
    for (const section of requiredSections) {
      expect(messages).toHaveProperty(section);
      expect(typeof msgRecord[section]).toBe("object");
    }
  });

  it("recursively ensures all message string leaves are non-empty", () => {
    let leafCount = 0;

    function validateLeaves(obj: Record<string, unknown>, path: string) {
      for (const [key, value] of Object.entries(obj)) {
        const currentPath = path ? `${path}.${key}` : key;
        if (typeof value === "string") {
          leafCount++;
          expect(value.trim().length, `Leaf at "${currentPath}" is empty`).toBeGreaterThan(0);
        } else if (typeof value === "object" && value !== null) {
          validateLeaves(value as Record<string, unknown>, currentPath);
        }
      }
    }

    validateLeaves(messages, "");
    expect(leafCount).toBeGreaterThan(300);
  });

  it("ensures Directory namespace is fully localized in Persian", () => {
    const dir = messages.directory;
    expect(dir.title).toBe("شرکت‌ها");
    expect(dir.filters.searchLabel).toBe("جستجو در نام سازمان");
    expect(dir.filters.roles.buyer).toBe("خریدار");
    expect(dir.filters.roles.supplier).toBe("تامین‌کننده");
    expect(dir.filters.roles.broker).toBe("کارگزار");
    expect(dir.table.name).toBe("نام شرکت");
    expect(dir.table.empty).toBe("شرکتی یافت نشد.");
    expect(dir.profile.title).toBe("پروفایل شرکت");
    expect(dir.profile.roles).toBe("نقش‌ها");
    expect(dir.profile.commodities).toBe("کالاها");
  });

  it("ensures Verification namespace is fully localized in Persian", () => {
    const ver = messages.verification;
    expect(ver.queue.title).toBe("صف بررسی و احراز هویت");
    expect(ver.queue.tableTitle).toBe("پرونده‌های احراز هویت سازمان‌ها");
    expect(ver.statuses.verified).toBe("تایید شده");
    expect(ver.statuses.under_review).toBe("در حال بررسی");
    expect(ver.statuses.suspended).toBe("تعلیق شده");
    expect(ver.caseDetail.unauthorizedTitle).toBe("دسترسی غیرمجاز");
    expect(ver.caseDetail.actions.startReview).toBe("شروع بررسی پرونده");
    expect(ver.caseDetail.actions.approveFull).toBe("تایید کامل سازمان");
    expect(ver.caseDetail.documents.title).toBe("چک‌لیست مدارک احراز هویت");
  });

  it("ensures RFQ Negotiation History namespace is fully localized in Persian", () => {
    const nh = messages.rfqWorkspace.negotiationHistory;
    expect(nh.title).toBe("تاریخچه مذاکره و سیر بازنگری پیشنهاد");
    expect(nh.tab.title).toBe("مذاکرات و تاریخچه پیشنهادها");
    expect(nh.tab.emptyTitle).toBe("هیچ پیشنهادی برای مذاکره ثبت نشده است");
    expect(nh.diff.title).toBe("تغییرات نسبت به نسخه {base}");
    expect(nh.toasts.declineSuccess).toContain("با موفقیت رد شد");
  });

  it("ensures Opportunities Desk namespace error messages and modals are localized", () => {
    const opp = messages.opportunities;
    expect(opp.title).toBe("میز فرصت‌ها");
    expect(opp.states.actionError).toBe("خطا در انجام عملیات.");
    expect(opp.states.contactError).toBe("خطا در ثبت تعامل.");
    expect(opp.states.taskError).toBe("خطا در ایجاد یا به‌روزرسانی وظیفه.");
    expect(opp.states.conversionError).toBe("خطا در تبدیل فرصت تجاری.");
    expect(opp.modals.reasonTitle).toBe("ثبت علت اقدام");
    expect(opp.modals.contactTitle).toBe("ثبت تعامل با طرف تجاری");
  });

  it("ensures message strings contain Persian text for user-facing descriptions", () => {
    const persianRegex = /[\u0600-\u06FF]/;
    // Samples across key domains
    const sampleStrings = [
      messages.session.loading,
      messages.shell.tradeHub,
      messages.shell.directory,
      messages.shell.deals,
      messages.tradeHub.title,
      messages.directory.title,
      messages.verification.queue.title,
      messages.dealWorkspace.title,
      messages.rfqWorkspace.loadingRfq,
      messages.matching.tabTitle,
    ];

    for (const str of sampleStrings) {
      expect(persianRegex.test(str), `Expected "${str}" to contain Persian characters`).toBe(true);
    }
  });
});
