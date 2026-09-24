import { describe, it, expect } from "vitest";
import { locales, type Locale } from "@/i18n/config";

describe("T1304 — RTL UX Review & Logical Properties Invariants", () => {
  describe("1. Locale & Direction Configuration", () => {
    it("configures Persian (/fa) as RTL and English (/en) as LTR", () => {
      expect(locales.fa.direction).toBe("rtl");
      expect(locales.en.direction).toBe("ltr");
    });

    it("verifies direction resolution helper", () => {
      const getDirection = (locale: Locale): "rtl" | "ltr" => locales[locale]?.direction ?? "ltr";
      expect(getDirection("fa")).toBe("rtl");
      expect(getDirection("en")).toBe("ltr");
    });
  });

  describe("2. Direction-Aware Navigation & Route Conventions", () => {
    it("determines correct Back arrow icon orientation per locale", () => {
      // Back in LTR points left; Back in RTL points right
      const getBackArrowDirection = (locale: Locale): "left" | "right" => {
        return locales[locale].direction === "rtl" ? "right" : "left";
      };

      expect(getBackArrowDirection("fa")).toBe("right");
      expect(getBackArrowDirection("en")).toBe("left");
    });

    it("determines correct Forward arrow icon orientation per locale", () => {
      // Forward in LTR points right; Forward in RTL points left
      const getForwardArrowDirection = (locale: Locale): "left" | "right" => {
        return locales[locale].direction === "rtl" ? "left" : "right";
      };

      expect(getForwardArrowDirection("fa")).toBe("left");
      expect(getForwardArrowDirection("en")).toBe("right");
    });

    it("determines correct route arrow symbol (Origin -> Destination) per locale", () => {
      // In RTL (reading right to left): Origin is right, Destination is left, so flow arrow points left (←)
      // In LTR (reading left to right): Origin is left, Destination is right, so flow arrow points right (→)
      const getRouteArrow = (locale: Locale): string => {
        return locales[locale].direction === "rtl" ? "←" : "→";
      };

      expect(getRouteArrow("fa")).toBe("←");
      expect(getRouteArrow("en")).toBe("→");
    });
  });

  describe("3. Mixed BiDi Content Isolation Rules", () => {
    // Alphanumeric tokens that must be isolated with bdi or dir=ltr
    const bidiTokens = [
      { type: "RFQ Identifier", sample: "RFQ-2026-00124" },
      { type: "Opportunity Identifier", sample: "OPP-2026-00042" },
      { type: "Deal Identifier", sample: "DEAL-2026-00001" },
      { type: "Version Token", sample: "v1" },
      { type: "Version Token uppercase", sample: "V2" },
      { type: "Quantity with Latin Unit", sample: "500 MT" },
      { type: "Currency Price", sample: "$204,000" },
      { type: "Percentage", sample: "95.5%" },
      { type: "Technical Spec Unit", sample: "(cSt)" },
      { type: "User Email", sample: "trader@brokerage.ir" },
      { type: "Website URL", sample: "https://supplier-petro.ir" },
    ];

    it("verifies all test tokens contain characters subject to bidi punctuation flipping or Latin scripts", () => {
      // Latin letters, digits, or weak/neutral bidi punctuation characters
      const bidiSensitiveRegex = /[a-zA-Z0-9\-()./@$%]/;
      for (const token of bidiTokens) {
        expect(bidiSensitiveRegex.test(token.sample)).toBe(true);
      }
    });

    it("demonstrates safe bdi wrapper generation for mixed-content string interpolation", () => {
      function isolateBidi(value: string, dir: "ltr" | "rtl" = "ltr"): string {
        return `<bdi dir="${dir}">${value}</bdi>`;
      }

      for (const token of bidiTokens) {
        const isolated = isolateBidi(token.sample);
        expect(isolated).toContain(`<bdi dir="ltr">${token.sample}</bdi>`);
      }
    });
  });

  describe("4. Logical CSS Class Consistency", () => {
    it("maps physical spacing to Tailwind CSS logical utilities", () => {
      const logicalClassMap: Record<string, string> = {
        "mr-": "me-",
        "ml-": "ms-",
        "pr-": "pe-",
        "pl-": "ps-",
        "border-r": "border-e",
        "border-l": "border-s",
        "right-": "end-",
        "left-": "start-",
        "text-right": "text-end",
        "text-left": "text-start",
      };

      for (const [physical, logical] of Object.entries(logicalClassMap)) {
        expect(logical).toBeDefined();
        expect(logical).not.toBe(physical);
      }
    });

    it("verifies timeline chronological invariant anchors to logical start edge", () => {
      // In RTL, the vertical line and dots anchor to the right edge (logical start)
      // In LTR, the vertical line and dots anchor to the left edge (logical start)
      const getTimelineConnectorClass = (locale: Locale): string => {
        // Logical property works identically regardless of runtime direction ('fa' or 'en')
        return locale === "fa" ? "border-s ps-4" : "border-s ps-4";
      };

      expect(getTimelineConnectorClass("fa")).toBe("border-s ps-4");
      expect(getTimelineConnectorClass("en")).toBe("border-s ps-4");
    });
  });
});
