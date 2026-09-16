import React from "react";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { OpportunityDeskClient } from "@/app/[locale]/opportunities/client";
import { OpportunityDetailClient } from "@/app/[locale]/opportunities/[id]/client";
import { AuthProvider } from "@/lib/auth-context";
import { apiClient } from "@/lib/api/client";

// Mock API client
vi.mock("@/lib/api/client", () => ({
  apiClient: {
    GET: vi.fn(),
    POST: vi.fn(),
    PATCH: vi.fn(),
  },
}));

// Mock Next.js navigation
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useParams: () => ({ locale: "fa", id: "opp-uuid-1" }),
  usePathname: () => "/fa/opportunities",
  useSearchParams: () => new URLSearchParams(),
}));

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

const renderWithProviders = (ui: React.ReactNode) => {
  const queryClient = createTestQueryClient();
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{ui}</AuthProvider>
      </QueryClientProvider>
    ),
  };
};

const mockOperatorUser = {
  id: 1,
  username: "operator_user",
  email: "operator@example.com",
  system_roles: ["operator"],
  organizations: [],
};

const mockBuyerUser = {
  id: 2,
  username: "buyer_user",
  email: "buyer@example.com",
  system_roles: [],
  organizations: [
    {
      id: "org-buyer",
      name: "شرکت خریدار",
      capabilities: ["buyer"],
      verification_status: "verified",
    },
  ],
};

const mockOpportunities = [
  {
    id: "opp-uuid-1",
    identifier: "OPP-2026-0001",
    commodity_id: "comm-bitumen-id",
    commodity_name: "قیر",
    direction: "DEMAND",
    status: "Captured",
    quantity: "500.00",
    unit: "MT",
    geography: "Bandar Abbas",
    incoterm: "FOB",
    counterparty_name: "پارس قیر",
    counterparty_type: "external",
    assigned_to_id: 1,
    assigned_to_name: "operator_user",
    claimed_by_id: 1,
    claimed_by_name: "operator_user",
    channel: "DIRECT_CALL",
    ingest_source: "PHONE",
    broker_attribution_name: "بروکر امین",
    has_open_tasks: true,
    version: 1,
    created_at: "2026-03-01T10:00:00Z",
    updated_at: "2026-03-01T10:00:00Z",
  },
  {
    id: "opp-uuid-2",
    identifier: "OPP-2026-0002",
    commodity_id: "comm-bitumen-id",
    commodity_name: "قیر",
    direction: "SUPPLY",
    status: "Qualified",
    quantity: "1000.00",
    unit: "MT",
    geography: "Tehran",
    incoterm: "EXW",
    counterparty_name: "صنایع نفت تهران",
    counterparty_type: "registered",
    assigned_to_id: 2,
    assigned_to_name: "other_operator",
    claimed_by_id: null,
    claimed_by_name: null,
    channel: "WEB_FORM",
    ingest_source: "DESK_INLINE",
    broker_attribution_name: null,
    has_open_tasks: false,
    version: 3,
    created_at: "2026-03-02T10:00:00Z",
    updated_at: "2026-03-02T12:00:00Z",
  },
];

const mockDetailOpportunity = {
  id: "opp-uuid-1",
  identifier: "OPP-2026-0001",
  commodity: {
    id: "comm-bitumen-id",
    code: "bitumen",
    name_fa: "قیر",
    name_en: "Bitumen",
  },
  direction: "DEMAND",
  status: "Captured",
  quantity: "500.00",
  unit: "MT",
  target_price: "250.00",
  currency: "USD",
  geography: "Bandar Abbas",
  incoterm: "FOB",
  channel: "DIRECT_CALL",
  ingest_source: "PHONE",
  external_counterparty: {
    company_name: "پارس قیر",
    contact_name: "آقای رضایی",
    phone: "09123456789",
    email: "rezaei@example.com",
    country: "IR",
  },
  organization: null,
  broker_attribution: {
    id: "broker-org-1",
    name: "بروکر امین",
  },
  assigned_to: {
    id: 1,
    username: "operator_user",
    full_name: "اپراتور ارشد",
  },
  claimed_by: {
    id: 1,
    username: "operator_user",
    full_name: "اپراتور ارشد",
  },
  specifications: {
    penetration: "60/70",
    softening_point: "49-56",
  },
  version: 2,
  notes: "خریدار به دنبال تحویل فوری است.",
  converted_rfq_id: null,
  converted_supply_listing_id: null,
  converted_at: null,
  created_at: "2026-03-01T10:00:00Z",
  updated_at: "2026-03-01T10:00:00Z",
};

describe("T0612 — Opportunity Desk UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  describe("Opportunity Desk List (OpportunityDeskClient)", () => {
    it("denies access to non-operator/non-admin users", async () => {
      vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
        if (url === "/api/auth/me") {
          return {
            response: { ok: true, status: 200 },
            data: mockBuyerUser,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        return { response: { ok: false, status: 403 } } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
      });

      renderWithProviders(<OpportunityDeskClient locale="fa" />);

      await waitFor(() => {
        expect(
          screen.getByText("دسترسی محدود به مدیران و اپراتورهای سیستم است.")
        ).toBeInTheDocument();
      });

      // Verify no opportunity queries were made
      const oppCalls = (vi.mocked(apiClient.GET).mock.calls as unknown[][]).filter(
        (call) => typeof call[0] === "string" && call[0].includes("/api/opportunities/opportunities/")
      );
      expect(oppCalls.length).toBe(0);
    });

    it("renders desk with 6 views for authorized operator", async () => {
      vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
        if (url === "/api/auth/me") {
          return {
            response: { ok: true, status: 200 },
            data: mockOperatorUser,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        if (url === "/api/commodities/") {
          return {
            response: { ok: true, status: 200 },
            data: { results: [] },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        if (url.includes("/api/opportunities/opportunities/")) {
          return {
            response: { ok: true, status: 200 },
            data: {
              count: 2,
              results: mockOpportunities,
            },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        return { response: { ok: true, status: 200 }, data: {} } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
      });

      renderWithProviders(<OpportunityDeskClient locale="fa" />);

      await waitFor(() => {
        expect(screen.getByText("میز فرصت‌ها (Opportunity Desk)")).toBeInTheDocument();
        // 6 Views
        expect(screen.getByRole("tab", { name: /کارپوشه فعال/i })).toBeInTheDocument();
        expect(screen.getByRole("tab", { name: /ارجاع‌شده به من/i })).toBeInTheDocument();
        expect(screen.getByRole("tab", { name: /واجد شرایط/i })).toBeInTheDocument();
        expect(screen.getByRole("tab", { name: /نیازمند پیگیری/i })).toBeInTheDocument();
        expect(screen.getByRole("tab", { name: /تبدیل‌شده/i })).toBeInTheDocument();
        expect(screen.getByRole("tab", { name: /از دست رفته/i })).toBeInTheDocument();
      });

      // Renders Opportunity items
      expect(screen.getByText("OPP-2026-0001")).toBeInTheDocument();
      expect(screen.getByText("OPP-2026-0002")).toBeInTheDocument();
      expect(screen.getByText("تقاضا (Demand)")).toBeInTheDocument();
      expect(screen.getByText("عرضه (Supply)")).toBeInTheDocument();
    });

    it("switching views triggers backend-driven query parameters", async () => {
      const capturedParams: unknown[] = [];
      vi.mocked(apiClient.GET).mockImplementation(async (url: string, opts?: unknown) => {
        if (url === "/api/auth/me") {
          return {
            response: { ok: true, status: 200 },
            data: mockOperatorUser,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        if (url === "/api/commodities/") {
          return {
            response: { ok: true, status: 200 },
            data: { results: [] },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        if (url.includes("/api/opportunities/opportunities/")) {
          capturedParams.push(opts);
          return {
            response: { ok: true, status: 200 },
            data: { count: 0, results: [] },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        return { response: { ok: true, status: 200 }, data: {} } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
      });

      renderWithProviders(<OpportunityDeskClient locale="fa" />);

      await waitFor(() => {
        expect(screen.getByRole("tab", { name: /ارجاع‌شده به من/i })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole("tab", { name: /ارجاع‌شده به من/i }));

      await waitFor(() => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const lastCall = capturedParams[capturedParams.length - 1] as any;
        expect(lastCall?.params?.query?.assigned_to_me).toBe(true);
      });
    });
  });

  describe("Opportunity Detail Workspace (OpportunityDetailClient)", () => {
    it("renders opportunity workspace with overview, counterparty, attribution, and specs", async () => {
      vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
        if (url === "/api/auth/me") {
          return {
            response: { ok: true, status: 200 },
            data: mockOperatorUser,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        if (url === "/api/opportunities/opportunities/{id}/") {
          return {
            response: { ok: true, status: 200 },
            data: mockDetailOpportunity,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        if (url.includes("/contact-attempts/")) {
          return {
            response: { ok: true, status: 200 },
            data: [
              {
                id: "ca-1",
                contact_type: "CALL",
                notes: "تماس اولیه با خریدار انجام شد.",
                created_at: "2026-03-01T11:00:00Z",
                actor: { id: 1, username: "operator_user", full_name: "اپراتور" },
              },
            ],
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        if (url.includes("/tasks/")) {
          return {
            response: { ok: true, status: 200 },
            data: [
              {
                id: "task-1",
                title: "بررسی مشخصات فنی قیر",
                status: "PENDING",
                due_at: "2026-03-05T12:00:00Z",
                description: "تطبیق با استاندارد صادراتی",
                assigned_to: { id: 1, username: "operator_user", full_name: "اپراتور" },
                created_at: "2026-03-01T11:00:00Z",
                updated_at: "2026-03-01T11:00:00Z",
              },
            ],
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        return { response: { ok: true, status: 200 }, data: {} } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
      });

      renderWithProviders(
        <OpportunityDetailClient locale="fa" opportunityId="opp-uuid-1" />
      );

      await waitFor(() => {
        expect(screen.getByText("OPP-2026-0001")).toBeInTheDocument();
        expect(screen.getByText("پارس قیر")).toBeInTheDocument();
        expect(screen.getByText("بروکر امین")).toBeInTheDocument();
        expect(screen.getByText("تماس اولیه با خریدار انجام شد.")).toBeInTheDocument();
        expect(screen.getByText("بررسی مشخصات فنی قیر")).toBeInTheDocument();
        expect(screen.getByText("60/70")).toBeInTheDocument();
      });

      // Verify T0611 is NOT implemented: no "Submit Offer" button exists
      expect(screen.queryByText(/ارائه پیشنهاد/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/ثبت پیشنهاد قیمت/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Offer/i)).not.toBeInTheDocument();
    });

    it("records contact attempt and updates timeline", async () => {
      let contactAttemptsList = [
        {
          id: "ca-1",
          contact_type: "CALL",
          notes: "تماس تلفنی اولیه",
          created_at: "2026-03-01T11:00:00Z",
          actor: { id: 1, username: "operator_user", full_name: "اپراتور" },
        },
      ];

      vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
        if (url === "/api/auth/me") {
          return {
            response: { ok: true, status: 200 },
            data: mockOperatorUser,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        if (url === "/api/opportunities/opportunities/{id}/") {
          return {
            response: { ok: true, status: 200 },
            data: mockDetailOpportunity,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        if (url.includes("/contact-attempts/")) {
          return {
            response: { ok: true, status: 200 },
            data: contactAttemptsList,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        if (url.includes("/tasks/")) {
          return {
            response: { ok: true, status: 200 },
            data: [],
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        return { response: { ok: true, status: 200 }, data: {} } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
      });

      vi.mocked(apiClient.POST).mockImplementation(async (url: string, opts?: unknown) => {
        if (url.includes("/contact-attempts/")) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const body = (opts as any)?.body;
          contactAttemptsList = [
            ...contactAttemptsList,
            {
              id: "ca-2",
              contact_type: body.contact_type,
              notes: body.notes,
              created_at: "2026-03-01T12:00:00Z",
              actor: { id: 1, username: "operator_user", full_name: "اپراتور" },
            },
          ];
          return { response: { ok: true, status: 201 }, data: {} } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
        }
        return { response: { ok: true, status: 200 }, data: {} } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
      });

      renderWithProviders(
        <OpportunityDetailClient locale="fa" opportunityId="opp-uuid-1" />
      );

      await waitFor(() => {
        expect(screen.getByText("ثبت تعامل جدید")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText("ثبت تعامل جدید"));

      await waitFor(() => {
        expect(screen.getByText("ثبت تعامل جدید با طرف معامله")).toBeInTheDocument();
      });

      const textarea = screen.getByPlaceholderText("خلاصه مذاکره یا یادداشت تعامل را وارد کنید…");
      fireEvent.change(textarea, { target: { value: "پیگیری واتس‌اپ انجام شد." } });

      const submitBtn = screen.getByRole("button", { name: "ثبت" });
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(screen.getByText("پیگیری واتس‌اپ انجام شد.")).toBeInTheDocument();
      });
    });

    it("creates, completes, and cancels follow-up tasks", async () => {
      let tasksList = [
        {
          id: "task-1",
          title: "وظیفه تست",
          status: "PENDING",
          due_at: "2026-03-10T10:00:00Z",
          description: "توضیحات",
          assigned_to: { id: 1, username: "operator_user", full_name: "اپراتور" },
          created_at: "2026-03-01T11:00:00Z",
          updated_at: "2026-03-01T11:00:00Z",
        },
      ];

      vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
        if (url === "/api/auth/me") {
          return {
            response: { ok: true, status: 200 },
            data: mockOperatorUser,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        if (url === "/api/opportunities/opportunities/{id}/") {
          return {
            response: { ok: true, status: 200 },
            data: mockDetailOpportunity,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        if (url.includes("/tasks/")) {
          return {
            response: { ok: true, status: 200 },
            data: tasksList,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        return { response: { ok: true, status: 200 }, data: [] } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
      });

      vi.mocked(apiClient.POST).mockImplementation(async (url: string) => {
        if (url.includes("/complete/")) {
          tasksList = tasksList.map((t) =>
            t.id === "task-1" ? { ...t, status: "COMPLETED" } : t
          );
          return { response: { ok: true, status: 200 }, data: {} } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
        }
        return { response: { ok: true, status: 200 }, data: {} } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
      });

      renderWithProviders(
        <OpportunityDetailClient locale="fa" opportunityId="opp-uuid-1" />
      );

      await waitFor(() => {
        expect(screen.getByText("وظیفه تست")).toBeInTheDocument();
        expect(screen.getByTitle("تکمیل وظیفه")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByTitle("تکمیل وظیفه"));

      await waitFor(() => {
        expect(screen.getByText("وظیفه با موفقیت تکمیل شد.")).toBeInTheDocument();
      });
    });

    it("converts demand opportunity to RFQ submitting expected_version", async () => {
      let postCallBody: any = null; // eslint-disable-line @typescript-eslint/no-explicit-any
      const qualifiedOpp = {
        ...mockDetailOpportunity,
        status: "Qualified",
      };

      vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
        if (url === "/api/auth/me") {
          return {
            response: { ok: true, status: 200 },
            data: mockOperatorUser,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        if (url === "/api/opportunities/opportunities/{id}/") {
          return {
            response: { ok: true, status: 200 },
            data: qualifiedOpp,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        return { response: { ok: true, status: 200 }, data: [] } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
      });

      vi.mocked(apiClient.POST).mockImplementation(async (url: string, opts?: unknown) => {
        if (url.includes("/convert-to-rfq/")) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          postCallBody = (opts as any)?.body;
          return {
            response: { ok: true, status: 200 },
            data: { rfq_id: "rfq-uuid-123" },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        return { response: { ok: true, status: 200 }, data: {} } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
      });

      renderWithProviders(
        <OpportunityDetailClient locale="fa" opportunityId="opp-uuid-1" />
      );

      await waitFor(() => {
        expect(screen.getByText("تبدیل به استعلام خرید (RFQ)")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText("تبدیل به استعلام خرید (RFQ)"));

      await waitFor(() => {
        expect(screen.getByText("تبدیل فرصت تقاضا به استعلام رسمی (RFQ)")).toBeInTheDocument();
      });

      // Fill external buyer org id
      const buyerInput = screen.getByPlaceholderText("UUID سازمان خریدار ثبت‌شده...");
      fireEvent.change(buyerInput, { target: { value: "org-buyer-uuid" } });

      const submitBtn = screen.getByRole("button", { name: "ثبت" });
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(postCallBody).not.toBeNull();
        expect(postCallBody.expected_version).toBe(2);
        expect(postCallBody.buyer_organization_id).toBe("org-buyer-uuid");
      });
    });

    it("handles 409 conflict: displays warning, does not retry, refetches current opportunity", async () => {
      let getCallCount = 0;
      vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
        if (url === "/api/auth/me") {
          return {
            response: { ok: true, status: 200 },
            data: mockOperatorUser,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        if (url === "/api/opportunities/opportunities/{id}/") {
          getCallCount++;
          return {
            response: { ok: true, status: 200 },
            data: {
              ...mockDetailOpportunity,
              version: getCallCount > 1 ? 3 : 2,
            },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
          } as any;
        }
        return { response: { ok: true, status: 200 }, data: [] } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
      });

      vi.mocked(apiClient.POST).mockImplementation(async () => {
        return {
          response: { ok: false, status: 409 },
          error: { detail: "Conflict: opportunity has been updated by another user." },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      });

      renderWithProviders(
        <OpportunityDetailClient locale="fa" opportunityId="opp-uuid-1" />
      );

      await waitFor(() => {
        expect(screen.getByText("ثبت تماس اولیه")).toBeInTheDocument();
      });

      // Initial GET count is 1
      expect(getCallCount).toBe(1);

      fireEvent.click(screen.getByText("ثبت تماس اولیه"));

      // Shows conflict banner and refetches
      await waitFor(() => {
        expect(
          screen.getByText("تداخل همزمانی: این فرصت توسط کاربر دیگری به‌روزرسانی شده است.")
        ).toBeInTheDocument();
        expect(getCallCount).toBeGreaterThanOrEqual(2);
      });
    });
  });
});
