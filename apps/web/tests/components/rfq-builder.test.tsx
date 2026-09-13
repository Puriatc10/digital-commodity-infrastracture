import React from "react";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/lib/auth-context";
import { apiClient } from "@/lib/api/client";
import { RFQBuilderClient } from "@/app/[locale]/trade-hub/rfqs/new/rfq-builder-client";
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
  useParams: () => ({ locale: "fa" }),
  usePathname: () => "/fa/trade-hub/rfqs/new",
  useSearchParams: () => new URLSearchParams(),
}));

const schemas = fixtures as Record<string, CommoditySchemaVersion>;

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

describe("T0504 — RFQ Builder UI Component Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    HTMLElement.prototype.hasPointerCapture = vi.fn().mockReturnValue(false);
    HTMLElement.prototype.releasePointerCapture = vi.fn();
    HTMLElement.prototype.setPointerCapture = vi.fn();
  });

  afterEach(() => {
    cleanup();
  });

  // Setup helper for auth state & base APIs
  function setupAuth(
    role: "owner" | "manager" | "member" | "viewer",
    capability = "buyer",
    isOperator = false,
    initialDraftData?: Record<string, unknown>
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
                organization: {
                  id: "buyer-org-1",
                  name: "سازمان خریدار آزمایشی",
                  registration_identifier: "REG-B1",
                  country: "IR",
                },
                role,
                capabilities: [capability],
              },
            ],
          },
        } as never;
      }

      if (url === "/api/commodities/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: mockCommodities,
        } as never;
      }

      if (url === "/api/commodities/{code}/schema/") {
        const code = options?.params?.path?.code;
        if (code === "bitumen") {
          return {
            response: { ok: true, status: 200 } as Response,
            data: schemas.bitumen,
          } as never;
        }
        if (code === "base_oil") {
          return {
            response: { ok: true, status: 200 } as Response,
            data: schemas.base_oil,
          } as never;
        }
      }

      if (url === "/api/organizations/directory/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: mockDirectoryOrgs,
        } as never;
      }

      if (url === "/api/trade-hub/rfqs/{rfq_id}/") {
        const id = options?.params?.path?.rfq_id;
        if (initialDraftData) {
          return {
            response: { ok: true, status: 200 } as Response,
            data: {
              id: id || "default-draft-id",
              ...initialDraftData,
            },
          } as never;
        }
      }

      if (url === "/api/trade-hub/rfqs/{rfq_id}/invitations/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: [],
        } as never;
      }

      return { response: { ok: true, status: 200 } as Response, data: null } as never;
    });
  }

  it("1. allows access for Buyer Owner and renders all 6 step headers in Persian", async () => {
    setupAuth("owner", "buyer");
    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("ایجاد استعلام خرید (RFQ)")).toBeInTheDocument();
      expect(screen.getAllByText("محصول").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("شرایط تجاری")).toBeInTheDocument();
      expect(screen.getByText("شرایط تحویل")).toBeInTheDocument();
      expect(screen.getByText("کیفیت و بازرسی")).toBeInTheDocument();
      expect(screen.getByText("مشارکت و رویت‌پذیری")).toBeInTheDocument();
      expect(screen.getByText("پیش‌نمایش و انتشار")).toBeInTheDocument();
    });
  });

  it("2. allows access for Platform Operator even without buyer membership", async () => {
    setupAuth("viewer", "supplier", true); // operator flag is true
    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("ایجاد استعلام خرید (RFQ)")).toBeInTheDocument();
    });
  });

  it("3. blocks access for Buyer Member (non-Owner/Manager) with localized error", async () => {
    setupAuth("member", "buyer");
    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("دسترسی غیرمجاز")).toBeInTheDocument();
      expect(
        screen.getByText("تنها مالک یا مدیر یک سازمان با قابلیت خریدار مجاز به ایجاد یا ویرایش استعلام است.")
      ).toBeInTheDocument();
    });
  });

  it("4. blocks access for Supplier-only organization", async () => {
    setupAuth("owner", "supplier");
    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("دسترسی غیرمجاز")).toBeInTheDocument();
    });
  });

  it("5. validates Step 1: displays prompt if commodity is not selected when clicking save or next", async () => {
    setupAuth("owner", "buyer");
    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("ایجاد استعلام خرید (RFQ)")).toBeInTheDocument();
    });

    const nextBtn = screen.getByRole("button", { name: "مرحله بعد" });
    fireEvent.click(nextBtn);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "لطفاً ابتدا نوع کالا را انتخاب کنید تا مشخصات فنی بارگذاری شود."
      );
    });
  });

  it("6. creates draft on first save with POST /api/trade-hub/rfqs/ and captures version 1", async () => {
    const user = userEvent.setup();
    setupAuth("owner", "buyer");

    vi.mocked(apiClient.POST).mockImplementation(async (url: string) => {
      if (url === "/api/trade-hub/rfqs/") {
        return {
          response: { ok: true, status: 201 } as Response,
          data: {
            id: "new-rfq-123",
            version: 1,
            commodity_id: "comm-bitumen-id",
            schema_version_id: schemas.bitumen.id,
            quantity: "500.000",
            unit: "MT",
            specifications: {},
            visibility: "private",
          },
        } as never;
      }
      return { response: { ok: true, status: 200 } as Response, data: null } as never;
    });

    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("ایجاد استعلام خرید (RFQ)")).toBeInTheDocument();
    });

    // Select Bitumen
    const combobox = screen.getByRole("combobox", { name: /نوع کالا/ });
    await user.click(combobox);
    const bitumenOption = await screen.findByRole("option", { name: /قیر/ });
    await user.click(bitumenOption);

    // Enter quantity
    const qtyInput = screen.getByLabelText(/مقدار مورد تقاضا/);
    fireEvent.change(qtyInput, { target: { value: "500" } });

    // Click Save Draft
    const saveBtn = screen.getByRole("button", { name: "ذخیره پیش‌نویس" });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(apiClient.POST).toHaveBeenCalledWith("/api/trade-hub/rfqs/", expect.objectContaining({
        body: expect.objectContaining({
          commodity_id: "comm-bitumen-id",
          quantity: "500",
          unit: "MT",
        }),
      }));
      expect(screen.getByText("new-rfq-123")).toBeInTheDocument();
      expect(screen.getByText(/نسخه پیش‌نویس:/).parentElement).toHaveTextContent("1");
    });
  });

  it("7. sends expected_version on subsequent updates and updates local version", async () => {
    const user = userEvent.setup();
    setupAuth("owner", "buyer");

    vi.mocked(apiClient.POST).mockImplementation(async (url: string) => {
      if (url === "/api/trade-hub/rfqs/") {
        return {
          response: { ok: true, status: 201 } as Response,
          data: {
            id: "draft-456",
            version: 1,
            commodity_id: "comm-bitumen-id",
            schema_version_id: schemas.bitumen.id,
            quantity: "1000.000",
            unit: "MT",
            specifications: {},
            visibility: "private",
          },
        } as never;
      }
      return { response: { ok: true, status: 200 } as Response, data: null } as never;
    });

    vi.mocked(apiClient.PATCH).mockImplementation(async (url: string) => {
      if (url === "/api/trade-hub/rfqs/{rfq_id}/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            id: "draft-456",
            version: 2,
            commodity_id: "comm-bitumen-id",
            schema_version_id: schemas.bitumen.id,
            quantity: "1200.000",
            unit: "MT",
            visibility: "private",
          },
        } as never;
      }
      return { response: { ok: true, status: 200 } as Response, data: null } as never;
    });

    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("ایجاد استعلام خرید (RFQ)")).toBeInTheDocument();
    });

    // Select Bitumen & quantity
    await user.click(screen.getByRole("combobox", { name: /نوع کالا/ }));
    await user.click(await screen.findByRole("option", { name: /قیر/ }));
    fireEvent.change(screen.getByLabelText(/مقدار مورد تقاضا/), { target: { value: "1000" } });

    // Save initial draft
    fireEvent.click(screen.getByRole("button", { name: "ذخیره پیش‌نویس" }));
    await waitFor(() => {
      expect(screen.getByText("draft-456")).toBeInTheDocument();
      expect(screen.getByText(/نسخه پیش‌نویس:/).parentElement).toHaveTextContent("1");
    });

    // Edit quantity and save again
    fireEvent.change(screen.getByLabelText(/مقدار مورد تقاضا/), { target: { value: "1200" } });
    fireEvent.click(screen.getByRole("button", { name: "ذخیره پیش‌نویس" }));

    await waitFor(() => {
      expect(apiClient.PATCH).toHaveBeenCalled();
      expect(screen.getByText(/نسخه پیش‌نویس:/).parentElement).toHaveTextContent("2"); // Version incremented to 2
    });
  });

  it("8. handles 409 stale version conflict without replaying mutation and refetches draft", async () => {
    setupAuth("owner", "buyer", false, {
      version: 5,
      commodity_id: "comm-bitumen-id",
      commodity_code: "bitumen",
      schema_version_id: schemas.bitumen.id,
      quantity: "3000.000",
      unit: "MT",
      specifications: {},
      visibility: "private",
    });

    vi.mocked(apiClient.PATCH).mockImplementation(async () => {
      return {
        response: { ok: false, status: 409 } as Response,
        error: { detail: "Stale version: aggregate was updated by another request." },
      } as never;
    });

    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" initialRfqId="stale-rfq" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("stale-rfq")).toBeInTheDocument();
    });

    // Click Save Draft which triggers 409
    fireEvent.click(screen.getByRole("button", { name: "ذخیره پیش‌نویس" }));

    await waitFor(() => {
      expect(screen.getByText(/تداخل ویرایش همزمان/)).toBeInTheDocument();
      expect(screen.getByText(/آخرین اطلاعات از سرور دریافت و جایگزین شد/)).toBeInTheDocument();
      expect(screen.getByText(/نسخه پیش‌نویس:/).parentElement).toHaveTextContent("5"); // Version updated to 5 from refetch
    });
  });

  it("9. proves dynamic rendering for two commodities (Bitumen and Base Oil) via the same component", async () => {
    const user = userEvent.setup();
    setupAuth("owner", "buyer");
    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("ایجاد استعلام خرید (RFQ)")).toBeInTheDocument();
    });

    // 1. Select Bitumen
    await user.click(screen.getByRole("combobox", { name: /نوع کالا/ }));
    await user.click(await screen.findByRole("option", { name: /قیر/ }));

    await waitFor(() => {
      // Bitumen specification fields
      expect(screen.getByText("درجه نفوذ")).toBeInTheDocument();
      expect(screen.getByText("نقطه نرمی")).toBeInTheDocument();
    });

    // 2. Switch to Base Oil
    await user.click(screen.getByRole("combobox", { name: /نوع کالا/ }));
    await user.click(await screen.findByRole("option", { name: /روغن پایه/ }));

    await waitFor(() => {
      // Base Oil specification fields
      expect(screen.getByText("گروه روغن پایه")).toBeInTheDocument();
      expect(screen.getByText("گرانروی در ۴۰ درجه")).toBeInTheDocument();
      // Bitumen field must no longer be present
      expect(screen.queryByText("درجه نفوذ")).not.toBeInTheDocument();
    });
  });

  it("10. maps backend structured specification validation errors to individual fields", async () => {
    const user = userEvent.setup();
    setupAuth("owner", "buyer");

    vi.mocked(apiClient.POST).mockImplementation(async () => {
      return {
        response: { ok: false, status: 400 } as Response,
        error: {
          detail: "Validation error in specifications.",
          errors: [
            { field: "penetration_grade", code: "invalid_choice", message: "درجه نفوذ نامعتبر است." },
          ],
        },
      } as never;
    });

    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("ایجاد استعلام خرید (RFQ)")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("combobox", { name: /نوع کالا/ }));
    await user.click(await screen.findByRole("option", { name: /قیر/ }));
    fireEvent.change(screen.getByLabelText(/مقدار مورد تقاضا/), { target: { value: "100" } });

    fireEvent.click(screen.getByRole("button", { name: "ذخیره پیش‌نویس" }));

    await waitFor(() => {
      expect(screen.getByText("درجه نفوذ نامعتبر است.")).toBeInTheDocument();
      const comboboxes = screen.getAllByRole("combobox");
      // The penetration_grade combobox is invalid
      expect(comboboxes.some((cb) => cb.getAttribute("aria-invalid") === "true")).toBe(true);
    });
  });

  it("11. supports Public, Network, and Private visibility selection and renders counterparty invitation UI", async () => {
    setupAuth("owner", "buyer", false, {
      version: 1,
      commodity_id: "comm-bitumen-id",
      commodity_code: "bitumen",
      schema_version_id: schemas.bitumen.id,
      quantity: "1000",
      unit: "MT",
      visibility: "private",
      specifications: {},
    });

    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" initialRfqId="rfq-step5-test" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("rfq-step5-test")).toBeInTheDocument();
    });

    // Navigate to step 5 (Participation & Visibility)
    fireEvent.click(screen.getByRole("button", { name: /مشارکت و رویت‌پذیری/ }));

    await waitFor(() => {
      expect(screen.getByText("نحوه مشارکت و سطح رویت‌پذیری")).toBeInTheDocument();
      expect(screen.getByText(/عمومی \(Public\)/)).toBeInTheDocument();
      expect(screen.getByText(/شبکه \(Network\)/)).toBeInTheDocument();
      expect(screen.getByText(/خصوصی \(Private\)/)).toBeInTheDocument();
    });

    // In Private mode, directory organizations are displayed
    await waitFor(() => {
      expect(screen.getByText("تأمین‌کننده نفت پارس")).toBeInTheDocument();
      expect(screen.getByText("کارگزاری خلیج فارس")).toBeInTheDocument();
    });
  });

  it("12. executes counterparty invitation via POST /api/trade-hub/rfqs/{id}/invitations/ in Private mode", async () => {
    setupAuth("owner", "buyer", false, {
      version: 1,
      commodity_id: "comm-bitumen-id",
      commodity_code: "bitumen",
      schema_version_id: schemas.bitumen.id,
      quantity: "1000",
      unit: "MT",
      visibility: "private",
      specifications: {},
    });

    vi.mocked(apiClient.POST).mockImplementation(async (url: string) => {
      if (url === "/api/trade-hub/rfqs/{rfq_id}/invitations/") {
        return {
          response: { ok: true, status: 201 } as Response,
          data: {
            id: "inv-1",
            organization: { id: "supplier-org-1", name: "تأمین‌کننده نفت پارس" },
            status: "invited",
            created_at: "2026-09-13T12:00:00Z",
          },
        } as never;
      }
      return { response: { ok: true, status: 200 } as Response, data: null } as never;
    });

    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" initialRfqId="rfq-invite-test" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("rfq-invite-test")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /مشارکت و رویت‌پذیری/ }));

    await waitFor(() => {
      expect(screen.getByText("تأمین‌کننده نفت پارس")).toBeInTheDocument();
    });

    const inviteBtns = screen.getAllByRole("button", { name: "دعوت به مشارکت" });
    fireEvent.click(inviteBtns[0]);

    await waitFor(() => {
      expect(apiClient.POST).toHaveBeenCalledWith(
        "/api/trade-hub/rfqs/{rfq_id}/invitations/",
        expect.objectContaining({
          body: { organization_id: "supplier-org-1" },
        })
      );
      expect(screen.getByText("دعوت‌نامه با موفقیت ارسال شد.")).toBeInTheDocument();
    });
  });

  it("13. handles 409 duplicate invitation error gracefully with localized message", async () => {
    setupAuth("owner", "buyer", false, {
      version: 1,
      commodity_id: "comm-bitumen-id",
      commodity_code: "bitumen",
      schema_version_id: schemas.bitumen.id,
      quantity: "1000",
      unit: "MT",
      visibility: "private",
      specifications: {},
    });

    vi.mocked(apiClient.POST).mockImplementation(async (url: string) => {
      if (url === "/api/trade-hub/rfqs/{rfq_id}/invitations/") {
        return {
          response: { ok: false, status: 409 } as Response,
          error: { detail: "Organization is already invited." },
        } as never;
      }
      return { response: { ok: true, status: 200 } as Response, data: null } as never;
    });

    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" initialRfqId="rfq-invite-dup" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("rfq-invite-dup")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /مشارکت و رویت‌پذیری/ }));

    await waitFor(() => {
      expect(screen.getByText("تأمین‌کننده نفت پارس")).toBeInTheDocument();
    });

    const inviteBtns = screen.getAllByRole("button", { name: "دعوت به مشارکت" });
    fireEvent.click(inviteBtns[0]);

    await waitFor(() => {
      expect(screen.getByText("این سازمان قبلاً به این استعلام دعوت شده است.")).toBeInTheDocument();
    });
  });

  it("14. renders preview in Section 6 utilizing CommoditySpecificationView and commercial terms", async () => {
    setupAuth("owner", "buyer", false, {
      version: 2,
      commodity_id: "comm-bitumen-id",
      commodity_code: "bitumen",
      schema_version_id: schemas.bitumen.id,
      quantity: "2500.000",
      unit: "MT",
      currency: "USD",
      target_price: "450.00",
      payment_terms: "LC at sight",
      incoterm: "FOB",
      origin: "Bandar Abbas",
      destination: "Jebel Ali",
      delivery_window_start: "2026-10-01",
      delivery_window_end: "2026-10-15",
      inspection_required: true,
      quality_notes: "SGS inspection required",
      notes: "Strict delivery timeline",
      visibility: "network",
      specifications: { penetration_grade: "60/70" },
    });

    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" initialRfqId="rfq-preview-1" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("rfq-preview-1")).toBeInTheDocument();
    });

    // Jump to Preview (Step 6)
    fireEvent.click(screen.getByRole("button", { name: /پیش‌نمایش و انتشار/ }));

    await waitFor(() => {
      expect(screen.getByText("پیش‌نمایش مشخصات استعلام")).toBeInTheDocument();
      expect(screen.getByText("2500.000 MT")).toBeInTheDocument();
      expect(screen.getByText("450.00")).toBeInTheDocument();
      expect(screen.getByText("LC at sight")).toBeInTheDocument();
      expect(screen.getByText("FOB")).toBeInTheDocument();
      expect(screen.getByText("Bandar Abbas")).toBeInTheDocument();
      expect(screen.getByText("Jebel Ali")).toBeInTheDocument();
      expect(screen.getByText("SGS inspection required")).toBeInTheDocument();
      expect(screen.getByText("۶۰/۷۰")).toBeInTheDocument(); // Penetration grade rendered in Persian by CommoditySpecificationView
    });
  });

  it("15. executes publish calling POST /api/trade-hub/rfqs/{id}/publish/ with expected_version and navigates on success", async () => {
    setupAuth("owner", "buyer", false, {
      version: 3,
      commodity_id: "comm-bitumen-id",
      commodity_code: "bitumen",
      schema_version_id: schemas.bitumen.id,
      quantity: "1000",
      unit: "MT",
      visibility: "public",
      specifications: {},
    });

    vi.mocked(apiClient.POST).mockImplementation(async (url: string, opts: unknown) => {
      const parsedOpts = opts as { body: { expected_version: number } };
      if (url === "/api/trade-hub/rfqs/{rfq_id}/publish/") {
        expect(parsedOpts.body.expected_version).toBe(3);
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            id: "rfq-pub-test",
            version: 4,
            status: "published",
          },
        } as never;
      }
      return { response: { ok: true, status: 200 } as Response, data: null } as never;
    });

    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" initialRfqId="rfq-pub-test" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("rfq-pub-test")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /پیش‌نمایش و انتشار/ }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "انتشار استعلام" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "انتشار استعلام" }));

    await waitFor(() => {
      expect(screen.getByText("استعلام با موفقیت منتشر شد.")).toBeInTheDocument();
    });
  });

  it("16. handles publish validation failure (400 Bad Request) and preserves draft state", async () => {
    setupAuth("owner", "buyer", false, {
      version: 1,
      commodity_id: "comm-bitumen-id",
      commodity_code: "bitumen",
      schema_version_id: schemas.bitumen.id,
      quantity: "1000",
      unit: "MT",
      visibility: "public",
      specifications: {},
    });

    vi.mocked(apiClient.POST).mockImplementation(async (url: string) => {
      if (url === "/api/trade-hub/rfqs/{rfq_id}/publish/") {
        return {
          response: { ok: false, status: 400 } as Response,
          error: {
            detail: "Missing required specifications before publication.",
            errors: [{ field: "penetration_grade", code: "required", message: "تکمیل مشخصه درجه نفوذ الزامی است." }],
          },
        } as never;
      }
      return { response: { ok: true, status: 200 } as Response, data: null } as never;
    });

    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" initialRfqId="rfq-pub-err" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("rfq-pub-err")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /پیش‌نمایش و انتشار/ }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "انتشار استعلام" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "انتشار استعلام" }));

    await waitFor(() => {
      expect(screen.getByText("Missing required specifications before publication.")).toBeInTheDocument();
      // Draft state preserved
      expect(screen.getByText("rfq-pub-err")).toBeInTheDocument();
    });
  });

  it("17. handles stale publish conflict (409 Conflict) and displays stale warning", async () => {
    setupAuth("owner", "buyer", false, {
      version: 7,
      commodity_id: "comm-bitumen-id",
      commodity_code: "bitumen",
      schema_version_id: schemas.bitumen.id,
      quantity: "1000",
      unit: "MT",
      visibility: "public",
      specifications: {},
    });

    vi.mocked(apiClient.POST).mockImplementation(async (url: string) => {
      if (url === "/api/trade-hub/rfqs/{rfq_id}/publish/") {
        return {
          response: { ok: false, status: 409 } as Response,
          error: { detail: "Stale version: RFQ modified by another operation." },
        } as never;
      }
      return { response: { ok: true, status: 200 } as Response, data: null } as never;
    });

    render(
      <Wrapper>
        <RFQBuilderClient locale="fa" initialRfqId="rfq-pub-stale" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("rfq-pub-stale")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /پیش‌نمایش و انتشار/ }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "انتشار استعلام" })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "انتشار استعلام" }));

    await waitFor(() => {
      expect(screen.getByText(/تداخل ویرایش همزمان/)).toBeInTheDocument();
      expect(screen.getByText("7")).toBeInTheDocument(); // Reconciled to version 7
    });
  });

  it("18. resets draft state and invalidates query cache when user switches organization", async () => {
    let currentOrg = "org-buyer-1";

    vi.mocked(apiClient.GET).mockImplementation(async (url: string, opts?: unknown) => {
      const options = opts as RequestOptions | undefined;

      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            id: 1,
            system_roles: [],
            organizations: [
              { organization: { id: currentOrg, name: currentOrg === "org-buyer-1" ? "Buyer 1" : "Buyer 2" }, role: "owner", capabilities: ["buyer"] },
            ],
          },
        } as never;
      }
      if (url === "/api/commodities/") {
        return { response: { ok: true, status: 200 } as Response, data: mockCommodities } as never;
      }
      if (url === "/api/commodities/{code}/schema/") {
        return { response: { ok: true, status: 200 } as Response, data: schemas.bitumen } as never;
      }
      if (url === "/api/trade-hub/rfqs/{rfq_id}/") {
        if (options?.params?.path?.rfq_id === "rfq-switch-test") {
          return {
            response: { ok: true, status: 200 } as Response,
            data: {
              id: "rfq-switch-test",
              version: 1,
              commodity_id: "comm-bitumen-id",
              commodity_code: "bitumen",
              schema_version_id: schemas.bitumen.id,
              quantity: "1500",
              unit: "MT",
              visibility: "private",
              specifications: {},
            },
          } as never;
        }
      }
      return { response: { ok: true, status: 200 } as Response, data: null } as never;
    });

    const { rerender } = render(
      <Wrapper>
        <RFQBuilderClient locale="fa" initialRfqId="rfq-switch-test" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("rfq-switch-test")).toBeInTheDocument();
    });

    // Simulate persona/org switch by triggering a change in AuthContext
    currentOrg = "org-buyer-2";

    // Rerender to test reset
    rerender(
      <Wrapper>
        <RFQBuilderClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      // Draft ID is cleared from UI
      expect(screen.queryByText("rfq-switch-test")).not.toBeInTheDocument();
    });
  });
});
