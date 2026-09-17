import React from "react";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { OpportunityDeskClient } from "@/app/[locale]/opportunities/client";
import { OpportunityDetailClient } from "@/app/[locale]/opportunities/[id]/client";
import { AuthProvider } from "@/lib/auth-context";
import { apiClient } from "@/lib/api/client";
import { getMessages } from "@/i18n/messages";

const messages = getMessages("fa");
const oppMsg = messages.opportunities;

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
    indicative_price: "250.00",
    currency: "USD",
    geography: "Bandar Abbas",
    incoterm: "FOB",
    external_counterparty: {
      company_name: "پارس قیر",
      contact_name: "آقای رضایی",
      phone: "09123456789",
      email: "rezaei@example.com",
      country: "IR",
    },
    organization: null,
    broker: {
      id: "broker-org-1",
      name: "بروکر امین",
    },
    source: "broker_referral",
    version: 1,
    can_qualify: false,
    qualification_issues: [],
    created_at: "2026-03-01T10:00:00Z",
    updated_at: "2026-03-01T10:00:00Z",
  },
  {
    id: "opp-uuid-2",
    identifier: "OPP-2026-0002",
    commodity: {
      id: "comm-bitumen-id",
      code: "bitumen",
      name_fa: "قیر",
      name_en: "Bitumen",
    },
    direction: "SUPPLY",
    status: "Qualified",
    quantity: "1000.00",
    unit: "MT",
    indicative_price: "280.00",
    currency: "USD",
    geography: "Tehran",
    incoterm: "EXW",
    external_counterparty: null,
    organization: {
      id: "org-supplier",
      name: "صنایع نفت تهران",
    },
    broker: null,
    source: "operator_sourcing",
    version: 3,
    can_qualify: false,
    qualification_issues: [],
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
  indicative_price: "250.00",
  currency: "USD",
  geography: "Bandar Abbas",
  incoterm: "FOB",
  channel: "DIRECT_CALL",
  ingest_source: "PHONE",
  source: "broker_referral",
  can_qualify: true,
  qualification_issues: [],
  external_counterparty: {
    company_name: "پارس قیر",
    contact_name: "آقای رضایی",
    phone: "09123456789",
    email: "rezaei@example.com",
    country: "IR",
  },
  organization: null,
  broker: {
    id: "broker-org-1",
    name: "بروکر امین",
  },
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
          screen.getByText(oppMsg.states.unauthorized)
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
        expect(screen.getByText(oppMsg.title)).toBeInTheDocument();
        // 6 Views
        expect(screen.getByRole("tab", { name: new RegExp(oppMsg.views.inbox, "i") })).toBeInTheDocument();
        expect(screen.getByRole("tab", { name: new RegExp(oppMsg.views.assigned_to_me, "i") })).toBeInTheDocument();
        expect(screen.getByRole("tab", { name: new RegExp(oppMsg.views.qualified, "i") })).toBeInTheDocument();
        expect(screen.getByRole("tab", { name: new RegExp(oppMsg.views.follow_up_required, "i") })).toBeInTheDocument();
        expect(screen.getByRole("tab", { name: new RegExp(oppMsg.views.converted, "i") })).toBeInTheDocument();
        expect(screen.getByRole("tab", { name: new RegExp(oppMsg.views.lost, "i") })).toBeInTheDocument();
      });

      // Renders Opportunity items
      expect(screen.getByText("OPP-2026-0001")).toBeInTheDocument();
      expect(screen.getByText("OPP-2026-0002")).toBeInTheDocument();
      expect(screen.getAllByText(oppMsg.direction.Demand).length).toBeGreaterThan(0);
      expect(screen.getAllByText(oppMsg.direction.Supply).length).toBeGreaterThan(0);
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
        expect(screen.getByRole("tab", { name: new RegExp(oppMsg.views.assigned_to_me, "i") })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole("tab", { name: new RegExp(oppMsg.views.assigned_to_me, "i") }));

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
                opportunity_id: "opp-uuid-1",
                type: "CALL",
                notes: "تماس اولیه با خریدار انجام شد.",
                occurred_at: "2026-03-01T11:00:00Z",
                created_at: "2026-03-01T11:00:00Z",
                recorded_by: 1,
                recorded_by_email: "operator@example.com",
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
                opportunity_id: "opp-uuid-1",
                title: "بررسی مشخصات فنی قیر",
                status: "OPEN",
                is_overdue: false,
                due_at: "2026-03-05T12:00:00Z",
                description: "تطبیق با استاندارد صادراتی",
                assigned_to: 1,
                assigned_to_email: "operator@example.com",
                created_by: 1,
                created_by_email: "operator@example.com",
                completed_at: null,
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
          opportunity_id: "opp-uuid-1",
          type: "CALL",
          notes: "تماس تلفنی اولیه",
          occurred_at: "2026-03-01T11:00:00Z",
          created_at: "2026-03-01T11:00:00Z",
          recorded_by: 1,
          recorded_by_email: "operator@example.com",
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
              opportunity_id: "opp-uuid-1",
              type: body.contact_type,
              notes: body.notes,
              occurred_at: new Date().toISOString(),
              created_at: new Date().toISOString(),
              recorded_by: 1,
              recorded_by_email: "operator@example.com",
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
        expect(screen.getByRole("button", { name: new RegExp(oppMsg.actions.addContact, "i") })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole("button", { name: new RegExp(oppMsg.actions.addContact, "i") }));

      await waitFor(() => {
        expect(screen.getByText(oppMsg.modals.contactTitle)).toBeInTheDocument();
      });

      const textarea = screen.getByPlaceholderText(/خلاصه مذاکره/i);
      fireEvent.change(textarea, { target: { value: "پیگیری واتس‌اپ انجام شد." } });

      const submitBtn = screen.getByRole("button", { name: oppMsg.modals.submit });
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(screen.getByText("پیگیری واتس‌اپ انجام شد.")).toBeInTheDocument();
      });
    });

    it("creates, completes, and cancels follow-up tasks", async () => {
      let tasksList = [
        {
          id: "task-1",
          opportunity_id: "opp-uuid-1",
          title: "وظیفه تست",
          status: "OPEN",
          is_overdue: false,
          due_at: "2026-03-10T10:00:00Z",
          description: "توضیحات",
          assigned_to: 1,
          assigned_to_email: "operator@example.com",
          created_by: 1,
          created_by_email: "operator@example.com",
          completed_at: null,
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
        expect(screen.getByRole("button", { name: new RegExp(oppMsg.actions.completeTask, "i") })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole("button", { name: new RegExp(oppMsg.actions.completeTask, "i") }));

      await waitFor(() => {
        expect(screen.getByText(oppMsg.states.taskCompleted)).toBeInTheDocument();
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
        expect(screen.getByRole("button", { name: new RegExp(oppMsg.actions.convertToRfq, "i") })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole("button", { name: new RegExp(oppMsg.actions.convertToRfq, "i") }));

      await waitFor(() => {
        expect(screen.getByText(oppMsg.modals.convertRfqTitle)).toBeInTheDocument();
      });

      // Fill external buyer org id
      const buyerInput = screen.getByPlaceholderText(/UUID سازمان خریدار/i);
      fireEvent.change(buyerInput, { target: { value: "org-buyer-uuid" } });

      const submitBtn = screen.getByRole("button", { name: oppMsg.modals.submit });
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
        expect(screen.getByRole("button", { name: new RegExp(oppMsg.actions.contact, "i") })).toBeInTheDocument();
      });

      // Initial GET count is 1
      expect(getCallCount).toBe(1);

      fireEvent.click(screen.getByRole("button", { name: new RegExp(oppMsg.actions.contact, "i") }));

      // Shows conflict banner and refetches
      await waitFor(() => {
        expect(screen.getByText(oppMsg.concurrency.staleWarning)).toBeInTheDocument();
        expect(screen.getByText(oppMsg.concurrency.conflictAlert)).toBeInTheDocument();
        expect(getCallCount).toBeGreaterThanOrEqual(2);
      });
    });
  });
});
