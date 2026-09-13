import React from "react";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/lib/auth-context";
import { apiClient } from "@/lib/api/client";
import { TradeHubClient } from "@/app/[locale]/trade-hub/trade-hub-client";

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
  useParams: () => ({ locale: "fa" }),
  usePathname: () => "/fa/trade-hub",
  useSearchParams: () => new URLSearchParams(),
}));

const mockCommodities = [
  {
    id: "comm-bitumen-id",
    code: "bitumen",
    name_fa: "قیر",
    name_en: "Bitumen",
    is_active: true,
  },
  {
    id: "comm-baseoil-id",
    code: "base_oil",
    name_fa: "روغن پایه",
    name_en: "Base Oil",
    is_active: true,
  },
];

const mockBuyerOrg = {
  id: "buyer-org-1",
  name: "خریدار نفت و گاز پارس",
  registration_identifier: "REG-BUYER-1",
  country: "IR",
  capabilities: ["buyer"],
  verification_status: "verified",
};

const mockSupplierOrg = {
  id: "supplier-org-1",
  name: "تأمین‌کننده نفت پارس",
  registration_identifier: "REG-SUPP-1",
  country: "IR",
  capabilities: ["supplier"],
  verification_status: "verified",
};

const mockRfqItem = {
  id: "rfq-test-1",
  organization: mockBuyerOrg,
  commodity_id: "comm-bitumen-id",
  commodity_code: "bitumen",
  commodity_name_fa: "قیر",
  commodity_name_en: "Bitumen",
  schema_version_id: "schema-v1-id",
  schema_version_number: 1,
  quantity: "1500.000",
  unit: "MT",
  target_price: "480.00",
  currency: "USD",
  incoterm: "FOB",
  origin: "Bandar Abbas",
  destination: "Jebel Ali",
  delivery_window_start: "2026-10-01",
  delivery_window_end: "2026-10-15",
  submission_deadline: "2026-09-25T12:00:00Z",
  visibility: "public",
  status: "published",
  version: 2,
  created_at: "2026-09-13T10:00:00Z",
};

const mockSupplyItem = {
  id: "supply-test-1",
  organization: mockSupplierOrg,
  commodity_id: "comm-bitumen-id",
  commodity_code: "bitumen",
  commodity_name_fa: "قیر",
  commodity_name_en: "Bitumen",
  schema_version_id: "schema-v1-id",
  schema_version_number: 1,
  quantity: "3000.000",
  unit: "MT",
  indicative_price: "475.00",
  currency: "USD",
  incoterm: "FOB",
  origin: "Bandar Abbas",
  destination: "Any",
  availability_window_start: "2026-10-05",
  availability_window_end: "2026-10-25",
  visibility: "public",
  status: "active",
  version: 2,
  created_at: "2026-09-13T11:00:00Z",
};

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

describe("T0510 — Trade Hub UI Component Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  function setupAuth(role: "owner" | "manager" | "member" | "viewer" = "owner", capabilities: string[] = ["buyer"]) {
    const org = {
      organization: {
        id: capabilities.includes("buyer") ? "buyer-org-1" : "supplier-org-1",
        name: capabilities.includes("buyer") ? "خریدار نفت و گاز پارس" : "تأمین‌کننده نفت پارس",
        country: "IR",
      },
      role,
      capabilities,
    };

    (apiClient.GET as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === "/api/auth/me") {
        return Promise.resolve({
          data: {
            id: 1,
            email: "actor@example.com",
            system_roles: [],
            organizations: [org],
          },
          response: { ok: true, status: 200 },
        });
      }
      if (path === "/api/commodities/") {
        return Promise.resolve({
          data: mockCommodities,
          response: { ok: true, status: 200 },
        });
      }
      if (path === "/api/trade-hub/rfqs/") {
        return Promise.resolve({
          data: { count: 1, results: [mockRfqItem] },
          response: { ok: true, status: 200 },
        });
      }
      if (path === "/api/trade-hub/supply-listings/") {
        return Promise.resolve({
          data: { count: 1, results: [mockSupplyItem] },
          response: { ok: true, status: 200 },
        });
      }
      return Promise.resolve({ data: null, response: { ok: false, status: 404 } });
    });
  }

  it("1. renders Trade Hub with title, Demand tab active, and RFQ card", async () => {
    setupAuth("owner", ["buyer"]);
    render(
      <Wrapper>
        <TradeHubClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("مرکز تجارت")).toBeInTheDocument();
      expect(screen.getByText("تقاضا (استعلام‌های خرید)")).toBeInTheDocument();
      expect(screen.getByText("عرضه (فهرست‌های عرضه)")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText("خریدار نفت و گاز پارس")).toBeInTheDocument();
      expect(screen.getByText(/1,500/)).toBeInTheDocument();
      expect(screen.getByText("ورود به میز کار")).toBeInTheDocument();
    });
  });

  it("2. shows 'ایجاد استعلام خرید (RFQ)' button for Buyer Owner", async () => {
    setupAuth("owner", ["buyer"]);
    const user = userEvent.setup();

    render(
      <Wrapper>
        <TradeHubClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("ایجاد استعلام خرید (RFQ)")).toBeInTheDocument();
    });

    await user.click(screen.getByText("ایجاد استعلام خرید (RFQ)"));
    expect(mockPush).toHaveBeenCalledWith("/fa/trade-hub/rfqs/new");
  });

  it("3. switches to Supply tab and displays Supply listing cards with action button", async () => {
    setupAuth("owner", ["supplier"]);
    const user = userEvent.setup();

    render(
      <Wrapper>
        <TradeHubClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("عرضه (فهرست‌های عرضه)")).toBeInTheDocument();
    });

    await user.click(screen.getByText("عرضه (فهرست‌های عرضه)"));

    await waitFor(() => {
      expect(screen.getByText("تأمین‌کننده نفت پارس")).toBeInTheDocument();
      expect(screen.getByText(/3,000/)).toBeInTheDocument();
      expect(screen.getByText("مشاهده جزئیات")).toBeInTheDocument();
      expect(screen.getByText("ثبت عرضه کالا")).toBeInTheDocument();
    });

    await user.click(screen.getByText("ثبت عرضه کالا"));
    expect(mockPush).toHaveBeenCalledWith("/fa/trade-hub/supply-listings/new");
  });

  it("4. navigates to RFQ workspace when clicking 'ورود به میز کار'", async () => {
    setupAuth("owner", ["buyer"]);
    const user = userEvent.setup();

    render(
      <Wrapper>
        <TradeHubClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("ورود به میز کار")).toBeInTheDocument();
    });

    await user.click(screen.getByText("ورود به میز کار"));
    expect(mockPush).toHaveBeenCalledWith(`/fa/trade-hub/rfqs/${mockRfqItem.id}`);
  });

  it("5. navigates to Supply listing detail when clicking 'مشاهده جزئیات'", async () => {
    setupAuth("owner", ["supplier"]);
    const user = userEvent.setup();

    render(
      <Wrapper>
        <TradeHubClient locale="fa" />
      </Wrapper>
    );

    await user.click(screen.getByText("عرضه (فهرست‌های عرضه)"));

    await waitFor(() => {
      expect(screen.getByText("مشاهده جزئیات")).toBeInTheDocument();
    });

    await user.click(screen.getByText("مشاهده جزئیات"));
    expect(mockPush).toHaveBeenCalledWith(`/fa/trade-hub/supply-listings/${mockSupplyItem.id}`);
  });

  it("6. Member role cannot create RFQ or Supply and sees role notice", async () => {
    setupAuth("member", ["buyer"]);

    render(
      <Wrapper>
        <TradeHubClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.queryByText("ایجاد استعلام خرید (RFQ)")).not.toBeInTheDocument();
      expect(
        screen.getByText("شما با دسترسی عضو/مشاهده‌گر وارد شده‌اید و مجاز به ایجاد تقاضا یا عرضه جدید نیستید.")
      ).toBeInTheDocument();
    });
  });

  it("7. renders error state with retry button when API request fails", async () => {
    setupAuth("owner", ["buyer"]);

    (apiClient.GET as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === "/api/auth/me") {
        return Promise.resolve({
          data: { id: 1, email: "actor@example.com", system_roles: [], organizations: [{ organization: { id: "org-1", name: "Org" }, role: "owner", capabilities: ["buyer"] }] },
          response: { ok: true, status: 200 },
        });
      }
      if (path === "/api/commodities/") {
        return Promise.resolve({ data: mockCommodities, response: { ok: true, status: 200 } });
      }
      if (path === "/api/trade-hub/rfqs/") {
        return Promise.resolve({ data: null, response: { ok: false, status: 500 } });
      }
      return Promise.resolve({ data: null, response: { ok: false, status: 404 } });
    });

    render(
      <Wrapper>
        <TradeHubClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("خطا در برقراری ارتباط با سرور یا دریافت داده‌های مرکز تجارت.")).toBeInTheDocument();
      expect(screen.getByText("تلاش مجدد")).toBeInTheDocument();
    });
  });

  it("8. renders empty state when no listings exist", async () => {
    setupAuth("owner", ["buyer"]);

    (apiClient.GET as ReturnType<typeof vi.fn>).mockImplementation((path: string) => {
      if (path === "/api/auth/me") {
        return Promise.resolve({
          data: { id: 1, email: "actor@example.com", system_roles: [], organizations: [{ organization: { id: "org-1", name: "Org" }, role: "owner", capabilities: ["buyer"] }] },
          response: { ok: true, status: 200 },
        });
      }
      if (path === "/api/commodities/") {
        return Promise.resolve({ data: mockCommodities, response: { ok: true, status: 200 } });
      }
      if (path === "/api/trade-hub/rfqs/") {
        return Promise.resolve({ data: { count: 0, results: [] }, response: { ok: true, status: 200 } });
      }
      return Promise.resolve({ data: null, response: { ok: false, status: 404 } });
    });

    render(
      <Wrapper>
        <TradeHubClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("در حال حاضر هیچ استعلام خریدی با شرایط جاری یافت نشد.")).toBeInTheDocument();
    });
  });
});
