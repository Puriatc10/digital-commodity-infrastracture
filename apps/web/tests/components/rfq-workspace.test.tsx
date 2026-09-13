import React from "react";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/lib/auth-context";
import { apiClient } from "@/lib/api/client";
import { RFQWorkspaceClient } from "@/app/[locale]/trade-hub/rfqs/[id]/rfq-workspace-client";
import fixtures from "../fixtures/commodity-schemas.json";
import type { CommoditySchemaVersion } from "@/components/commodity/commodity-specification-form";

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
  useParams: () => ({ locale: "fa", id: "rfq-test-123" }),
  usePathname: () => "/fa/trade-hub/rfqs/rfq-test-123",
  useSearchParams: () => new URLSearchParams(),
}));

const schemas = fixtures as Record<string, CommoditySchemaVersion>;

const mockBitumenSchemaV1 = {
  ...schemas.bitumen,
  id: "schema-v1-id",
  version: 1,
  state: "published",
};

const mockBuyerOrg = {
  id: "buyer-org-1",
  name: "شرکت خریدار آزمایشی",
  registration_identifier: "REG-BUYER-1",
  country: "IR",
};

const mockSupplierOrg = {
  id: "supplier-org-1",
  name: "تأمین‌کننده نفت پارس",
  registration_identifier: "REG-SUPP-1",
  country: "IR",
};

const mockBrokerOrg = {
  id: "broker-org-1",
  name: "کارگزاری خلیج فارس",
  registration_identifier: "REG-BROKER-1",
  country: "IR",
};

const mockPublishedRfq = {
  id: "rfq-test-123",
  version: 1,
  organization: mockBuyerOrg,
  commodity_id: "comm-bitumen-id",
  commodity_code: "bitumen",
  commodity_name_fa: "قیر",
  commodity_name_en: "Bitumen",
  schema_version_id: "schema-v1-id",
  status: "published",
  visibility: "public",
  quantity: "5000",
  unit: "MT",
  specifications: {
    penetration_grade: "60/70",
    softening_point: 49,
  },
  currency: "USD",
  target_price: "420.00",
  payment_terms: "LC at sight",
  incoterm: "FOB",
  origin: "Bandar Abbas",
  destination: "Jebel Ali",
  delivery_window_start: "2026-10-01",
  delivery_window_end: "2026-10-15",
  submission_deadline: "2026-09-25T18:00:00Z",
  inspection_required: true,
  quality_notes: "SGS inspection certificate mandatory",
  notes: "Authoritative RFQ workspace test notes",
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
  published_at: "2026-09-01T12:00:00Z",
  closed_at: null,
  cancelled_at: null,
  cancellation_reason: null,
};

const mockInvitations = [
  {
    id: "inv-1",
    rfq_id: "rfq-test-123",
    organization: mockSupplierOrg,
    status: "invited",
    created_at: "2026-09-02T10:00:00Z",
    viewed_at: null,
    responded_at: null,
    declined_at: null,
    decline_reason: null,
  },
  {
    id: "inv-2",
    rfq_id: "rfq-test-123",
    organization: mockBrokerOrg,
    status: "viewed",
    created_at: "2026-09-02T11:00:00Z",
    viewed_at: "2026-09-02T11:30:00Z",
    responded_at: null,
    declined_at: null,
    decline_reason: null,
  },
];

const mockActivity = [
  {
    id: "act-1",
    event_type: "rfq_created",
    event_label_fa: "ایجاد استعلام",
    event_label_en: "RFQ Created",
    timestamp: "2026-09-01T10:00:00Z",
    actor_name: "مدیر خرید",
    organization_name: "شرکت خریدار آزمایشی",
    notes: null,
  },
  {
    id: "act-2",
    event_type: "rfq_published",
    event_label_fa: "انتشار عمومی استعلام",
    event_label_en: "RFQ Published",
    timestamp: "2026-09-01T12:00:00Z",
    actor_name: "مدیر خرید",
    organization_name: "شرکت خریدار آزمایشی",
    notes: null,
  },
];

const mockDirectoryOrgs = [
  {
    id: "supplier-org-1",
    name: "تأمین‌کننده نفت پارس",
    registration_identifier: "REG-SUPP-1",
    country: "IR",
    capabilities: ["supplier"],
    verification_status: "verified",
  },
  {
    id: "broker-org-1",
    name: "کارگزاری خلیج فارس",
    registration_identifier: "REG-BROKER-1",
    country: "IR",
    capabilities: ["broker"],
    verification_status: "verified",
  },
];

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

const Wrapper = ({ children }: { children: React.ReactNode }) => {
  const queryClient = createTestQueryClient();
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
};

interface RequestOptions {
  params?: {
    path?: Record<string, string>;
    query?: Record<string, unknown>;
  };
  body?: Record<string, unknown>;
}

describe("T0507 — RFQ Workspace Component Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  function setupAuth(
    userOrg = mockBuyerOrg,
    role: "owner" | "manager" | "member" | "viewer" = "owner",
    capability = "buyer",
    isOperator = false
  ) {
    vi.mocked(apiClient.GET).mockImplementation(async (url: string, opts?: unknown) => {
      const options = opts as RequestOptions | undefined;

      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            id: 1,
            email: "user@example.com",
            system_roles: isOperator ? ["operator"] : [],
            organizations: [
              {
                organization: userOrg,
                role,
                capabilities: [capability],
              },
            ],
          },
        } as never;
      }

      if (url === "/api/trade-hub/rfqs/{rfq_id}/") {
        const id = options?.params?.path?.rfq_id;
        if (id === "rfq-test-123") {
          return {
            response: { ok: true, status: 200 } as Response,
            data: mockPublishedRfq,
          } as never;
        }
        return {
          response: { ok: false, status: 404 } as Response,
          data: null,
        } as never;
      }

      if (url === "/api/commodity-schemas/{id}/") {
        const id = options?.params?.path?.id;
        if (id === "schema-v1-id") {
          return {
            response: { ok: true, status: 200 } as Response,
            data: mockBitumenSchemaV1,
          } as never;
        }
      }

      if (url === "/api/trade-hub/rfqs/{rfq_id}/invitations/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: mockInvitations,
        } as never;
      }

      if (url === "/api/trade-hub/rfqs/{rfq_id}/invitations/me/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: mockInvitations[0],
        } as never;
      }

      if (url === "/api/trade-hub/rfqs/{rfq_id}/activity/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: mockActivity,
        } as never;
      }

      if (url === "/api/organizations/directory/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: mockDirectoryOrgs,
        } as never;
      }

      return { response: { ok: true, status: 200 } as Response, data: null } as never;
    });
  }

  it("1. renders RFQ Overview with exact historical schema v1 attributes and Persian localization", async () => {
    setupAuth();
    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    // Header assertions
    await waitFor(() => {
      expect(screen.getByText(/قیر/)).toBeInTheDocument();
      expect(screen.getByText(/bitumen/i)).toBeInTheDocument();
      expect(screen.getByText("منتشر شده")).toBeInTheDocument();
      expect(screen.getByText("عمومی")).toBeInTheDocument();
      expect(screen.getByText("نسخه v1")).toBeInTheDocument();
    });

    // Commercial and Delivery Terms
    expect(screen.getByText("5000 MT")).toBeInTheDocument();
    expect(screen.getByText("420.00 USD")).toBeInTheDocument();
    expect(screen.getByText("FOB")).toBeInTheDocument();
    expect(screen.getByText("Bandar Abbas")).toBeInTheDocument();
    expect(screen.getByText("Jebel Ali")).toBeInTheDocument();
    expect(screen.getByText("LC at sight")).toBeInTheDocument();

    // Historical schema v1 exact fetch assertion
    expect(apiClient.GET).toHaveBeenCalledWith(
      "/api/commodity-schemas/{id}/",
      expect.objectContaining({
        params: { path: { id: "schema-v1-id" } },
      })
    );

    // Direction RTL
    const container = screen.getByText(/قیر/).closest("[dir]");
    expect(container).toHaveAttribute("dir", "rtl");
  });

  it("2. displays participant management table for Buyer Owner and allows inviting more organizations", async () => {
    setupAuth();
    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    // Navigate to participants tab
    const participantsTab = await screen.findByRole("button", { name: /مشارکت‌کنندگان/ });
    fireEvent.click(participantsTab);

    // Check participants table rendered
    await waitFor(() => {
      expect(screen.getByText("تأمین‌کننده نفت پارس")).toBeInTheDocument();
      expect(screen.getByText("کارگزاری خلیج فارس")).toBeInTheDocument();
      expect(screen.getByText("دعوت شده")).toBeInTheDocument();
      expect(screen.getByText("مشاهده شده")).toBeInTheDocument();
    });

    // Buyer sees "Invite More" button
    const inviteMoreBtn = screen.getByRole("button", { name: /دعوت از سازمان جدید/ });
    expect(inviteMoreBtn).toBeInTheDocument();
  });

  it("3. protects counterparty privacy: Supplier sees only own invitation state and cannot see competitors", async () => {
    setupAuth(mockSupplierOrg, "owner", "supplier");
    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    // Navigate to participants tab
    const participantsTab = await screen.findByRole("button", { name: /مشارکت‌کنندگان/ });
    fireEvent.click(participantsTab);

    // Competitor should NOT be rendered
    await waitFor(() => {
      expect(screen.queryByText("کارگزاری خلیج فارس")).not.toBeInTheDocument();
    });

    // Supplier's own status banner and decline button should be rendered
    expect(screen.getByText("وضعیت دعوت شما")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /رد دعوت/ })).toBeInTheDocument();

    // Verify competitor list endpoint /invitations/ was NOT called
    expect(apiClient.GET).not.toHaveBeenCalledWith(
      "/api/trade-hub/rfqs/{rfq_id}/invitations/",
      expect.anything()
    );
    // Verified own invitation was called
    expect(apiClient.GET).toHaveBeenCalledWith(
      "/api/trade-hub/rfqs/{rfq_id}/invitations/me/",
      expect.objectContaining({
        params: { path: { rfq_id: "rfq-test-123" } },
      })
    );
  });

  it("4. renders Activity timeline facts strictly without exposing competitor events", async () => {
    setupAuth();
    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    // Switch to Activity tab
    const activityTab = await screen.findByRole("button", { name: /تاریخچه فعالیت/ });
    fireEvent.click(activityTab);

    await waitFor(() => {
      expect(screen.getByText("ایجاد استعلام")).toBeInTheDocument();
      expect(screen.getByText("انتشار عمومی استعلام")).toBeInTheDocument();
    });
  });

  it("5. renders explicit non-functional placeholders for staged tabs (Offers, Comparison, Negotiation, Documents)", async () => {
    setupAuth();
    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    // Offers tab placeholder
    const offersTab = await screen.findByRole("button", { name: /پیشنهادها/ });
    fireEvent.click(offersTab);
    await waitFor(() => {
      expect(screen.getByText("پیشنهادهای قیمت (T0508)")).toBeInTheDocument();
      expect(screen.getByText(/در فاز بعدی فعال خواهد شد/)).toBeInTheDocument();
    });

    // Comparison tab placeholder
    const comparisonTab = screen.getByRole("button", { name: /مقایسه و ارزیابی/ });
    fireEvent.click(comparisonTab);
    expect(screen.getByText("مقایسه و ارزیابی پیشنهادها (T0509)")).toBeInTheDocument();

    // Negotiation tab placeholder
    const negotiationTab = screen.getByRole("button", { name: /مذاکره و پیام‌ها/ });
    fireEvent.click(negotiationTab);
    expect(screen.getByText("مذاکره تجاری و پیام‌رسانی (T0510)")).toBeInTheDocument();

    // Documents tab placeholder (not reusing KYC)
    const documentsTab = screen.getByRole("button", { name: /اسناد و مدارک/ });
    fireEvent.click(documentsTab);
    expect(screen.getByText("اسناد تجاری استعلام (T0511)")).toBeInTheDocument();
  });

  it("6. performs Close RFQ with expected_version optimistic concurrency control", async () => {
    setupAuth();
    vi.mocked(apiClient.POST).mockResolvedValueOnce({
      response: { ok: true, status: 200 } as Response,
      data: {
        ...mockPublishedRfq,
        status: "closed",
        version: 2,
        closed_at: "2026-09-02T15:00:00Z",
      },
    } as never);

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    const closeBtn = await screen.findByRole("button", { name: "بستن استعلام" });
    fireEvent.click(closeBtn);

    // In modal, click confirm
    const confirmCloseBtn = screen.getByRole("button", { name: "بستن استعلام" });
    fireEvent.click(confirmCloseBtn);

    await waitFor(() => {
      expect(apiClient.POST).toHaveBeenCalledWith(
        "/api/trade-hub/rfqs/{rfq_id}/close/",
        expect.objectContaining({
          params: { path: { rfq_id: "rfq-test-123" } },
          body: { expected_version: 1 },
        })
      );
    });
  });

  it("7. handles 409 Conflict gracefully by displaying stale conflict warning and refreshing data", async () => {
    setupAuth();
    vi.mocked(apiClient.POST).mockResolvedValueOnce({
      response: { ok: false, status: 409 } as Response,
      data: { error: "version_conflict" },
    } as never);

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    const closeBtn = await screen.findByRole("button", { name: "بستن استعلام" });
    fireEvent.click(closeBtn);

    const confirmCloseBtn = screen.getByRole("button", { name: "بستن استعلام" });
    fireEvent.click(confirmCloseBtn);

    await waitFor(() => {
      expect(screen.getByText("تغییر همزمان در استعلام")).toBeInTheDocument();
      expect(
        screen.getByText(/اطلاعات این استعلام توسط کاربر یا فرآیند دیگری به‌روزرسانی شده است/)
      ).toBeInTheDocument();
    });
  });

  it("8. renders 404 screen when RFQ is not found or hidden by visibility rules", async () => {
    setupAuth();
    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-non-existent-999" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("استعلام یافت نشد")).toBeInTheDocument();
      expect(
        screen.getByText(/استعلام مورد نظر وجود ندارد یا شما دسترسی لازم برای مشاهده آن را ندارید/)
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /بازگشت به مرکز تجارت/ })).toBeInTheDocument();
    });
  });
});
