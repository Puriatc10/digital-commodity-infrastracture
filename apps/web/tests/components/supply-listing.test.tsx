import React from "react";
import { render, screen, waitFor, cleanup, fireEvent, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/lib/auth-context";
import { apiClient } from "@/lib/api/client";
import { SupplyListingBuilderClient } from "@/app/[locale]/trade-hub/supply-listings/new/supply-listing-builder-client";
import { SupplyListingDetailClient } from "@/app/[locale]/trade-hub/supply-listings/[id]/supply-listing-detail-client";
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
  useParams: () => ({ locale: "fa", id: "listing-test-123" }),
  usePathname: () => "/fa/trade-hub/supply-listings/new",
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

const mockSupplierOrg = {
  id: "supplier-org-1",
  name: "تأمین‌کننده نفت پارس",
  registration_identifier: "REG-SUPP-1",
  country: "IR",
  capabilities: ["supplier"],
  verification_status: "verified",
};

const mockBuyerOrg = {
  id: "buyer-org-1",
  name: "خریدار خلیج فارس",
  registration_identifier: "REG-BUYER-1",
  country: "IR",
  capabilities: ["buyer"],
  verification_status: "verified",
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

interface RequestOptions {
  params?: {
    path?: Record<string, string>;
    query?: Record<string, unknown>;
  };
  body?: Record<string, unknown>;
}

describe("T0509 — Supply Listing UI Component Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    HTMLElement.prototype.hasPointerCapture = vi.fn().mockReturnValue(false);
    HTMLElement.prototype.releasePointerCapture = vi.fn();
    HTMLElement.prototype.setPointerCapture = vi.fn();
  });

  afterEach(() => {
    cleanup();
  });

  function setupAuth(
    role: "owner" | "manager" | "member" | "viewer",
    capabilities: string[] = ["supplier"],
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
            email: "supplier@example.com",
            system_roles: isOperator ? ["operator"] : [],
            organizations: [
              {
                organization: mockSupplierOrg,
                role,
                capabilities,
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

      if (url === "/api/commodity-schemas/{id}/") {
        const id = options?.params?.path?.id;
        if (id === "bitumen-v1" || id === schemas.bitumen.id) {
          return {
            response: { ok: true, status: 200 } as Response,
            data: schemas.bitumen,
          } as never;
        }
        if (id === "bitumen-v2" || id === schemas.bitumen_v2.id) {
          return {
            response: { ok: true, status: 200 } as Response,
            data: schemas.bitumen_v2,
          } as never;
        }
        if (id === "base_oil-v1" || id === schemas.base_oil.id) {
          return {
            response: { ok: true, status: 200 } as Response,
            data: schemas.base_oil,
          } as never;
        }
      }

      if (url === "/api/trade-hub/supply-listings/{listing_id}/") {
        if (initialDraftData) {
          return {
            response: { ok: true, status: 200 } as Response,
            data: initialDraftData,
          } as never;
        }
        return {
          response: { ok: false, status: 404 } as Response,
          data: { detail: "Supply listing not found." },
        } as never;
      }

      return { response: { ok: false, status: 404 } as Response, data: null } as never;
    });
  }

  it("1. Owner/Manager access: allowed to render supply listing builder", async () => {
    setupAuth("owner", ["supplier"]);

    render(
      <Wrapper>
        <SupplyListingBuilderClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("ثبت آگهی عرضه کالا")).toBeInTheDocument();
      expect(screen.getByText("اطلاعات محصول و مشخصات فنی")).toBeInTheDocument();
      expect(screen.getByText("نوع کالا")).toBeInTheDocument();
    });
  });

  it("2. Member/Viewer access: denied with Persian unauthorized message", async () => {
    setupAuth("member", ["supplier"]);

    render(
      <Wrapper>
        <SupplyListingBuilderClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("دسترسی غیرمجاز")).toBeInTheDocument();
      expect(
        screen.getByText("تنها مالک یا مدیر یک سازمان با قابلیت تأمین‌کننده مجاز به ایجاد یا ویرایش آگهی عرضه است.")
      ).toBeInTheDocument();
    });
  });

  it("3. Non-supplier organization: denied access", async () => {
    setupAuth("owner", ["buyer"]); // Buyer capability only

    render(
      <Wrapper>
        <SupplyListingBuilderClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("دسترسی غیرمجاز")).toBeInTheDocument();
    });
  });

  it("4. Platform Operator access: allowed even without supplier organization", async () => {
    setupAuth("member", ["buyer"], true); // Operator flag true

    render(
      <Wrapper>
        <SupplyListingBuilderClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("ثبت آگهی عرضه کالا")).toBeInTheDocument();
    });
  });

  it("5. Draft creation: creates initial draft via POST and stores authoritative ID and version", async () => {
    const user = userEvent.setup();
    setupAuth("manager", ["supplier"]);

    vi.mocked(apiClient.POST).mockImplementation(async (url: string, opts?: unknown) => {
      if (url === "/api/trade-hub/supply-listings/") {
        const body = (opts as RequestOptions)?.body;
        return {
          response: { ok: true, status: 201 } as Response,
          data: {
            id: "listing-created-123",
            version: 1,
            commodity_id: body?.commodity_id,
            schema_version_id: body?.schema_version_id,
            quantity: body?.quantity,
            unit: body?.unit,
            status: "draft",
            visibility: "public",
          },
        } as never;
      }
      return { response: { ok: false, status: 400 } as Response } as never;
    });

    render(
      <Wrapper>
        <SupplyListingBuilderClient locale="fa" />
      </Wrapper>
    );

    const combobox = await screen.findByRole("combobox", { name: /نوع کالا/ });
    await user.click(combobox);

    const bitumenOption = await screen.findByRole("option", { name: /قیر/ });
    await user.click(bitumenOption);

    // Enter positive quantity
    const quantityInput = screen.getByPlaceholderText("مثال: ۱۰۰۰");
    fireEvent.change(quantityInput, { target: { value: "2500" } });

    // Click Save Draft
    const saveButton = screen.getByText("ذخیره پیش‌نویس");
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(apiClient.POST).toHaveBeenCalledWith(
        "/api/trade-hub/supply-listings/",
        expect.objectContaining({
          body: expect.objectContaining({
            commodity_id: "comm-bitumen-id",
            schema_version_id: schemas.bitumen.id,
            quantity: "2500",
            unit: "MT",
            visibility: "public",
          }),
        })
      );
      expect(screen.getByText("پیش‌نویس با موفقیت ذخیره شد.")).toBeInTheDocument();
      expect(screen.getByText("نسخه پیش‌نویس: 1")).toBeInTheDocument();
    });
  });

  it("6. Version persistence and save draft: subsequent saves use expected_version", async () => {
    const existingDraft = {
      id: "listing-edit-123",
      version: 2,
      commodity_id: "comm-bitumen-id",
      commodity_code: "bitumen",
      schema_version_id: schemas.bitumen.id,
      quantity: "3000",
      unit: "MT",
      specifications: { penetration_grade: "60/70" },
      status: "draft",
      visibility: "public",
      indicative_price: "450.00",
      currency: "USD",
      payment_terms: "LC",
      incoterm: "FOB",
      origin: "Bandar Abbas",
      destination: "Dubai",
      availability_window_start: "2026-10-01",
      availability_window_end: "2026-10-20",
      quality_notes: "Quality note sample",
      notes: "Internal note sample",
    };

    setupAuth("owner", ["supplier"], false, existingDraft);

    vi.mocked(apiClient.PATCH).mockImplementation(async (url: string) => {
      if (url === "/api/trade-hub/supply-listings/{listing_id}/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            ...existingDraft,
            version: 3,
            quantity: "3500",
          },
        } as never;
      }
      return { response: { ok: false, status: 400 } as Response } as never;
    });

    render(
      <Wrapper>
        <SupplyListingBuilderClient locale="fa" initialListingId="listing-edit-123" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("نسخه پیش‌نویس: 2")).toBeInTheDocument();
      expect(screen.getByDisplayValue("3000")).toBeInTheDocument();
    });

    // Update quantity
    const quantityInput = screen.getByDisplayValue("3000");
    fireEvent.change(quantityInput, { target: { value: "3500" } });

    // Click Save Draft
    const saveButton = screen.getByText("ذخیره پیش‌نویس");
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(apiClient.PATCH).toHaveBeenCalledWith(
        "/api/trade-hub/supply-listings/{listing_id}/",
        expect.objectContaining({
          params: { path: { listing_id: "listing-edit-123" } },
          body: expect.objectContaining({
            expected_version: 2,
            quantity: "3500",
          }),
        })
      );
      expect(screen.getByText("نسخه پیش‌نویس: 3")).toBeInTheDocument();
    });
  });

  it("7. Stale concurrency conflict (409): displays Persian error, refetches authoritative draft, does not overwrite", async () => {
    const staleDraft = {
      id: "listing-stale-123",
      version: 1,
      commodity_id: "comm-bitumen-id",
      commodity_code: "bitumen",
      schema_version_id: schemas.bitumen.id,
      quantity: "1000",
      unit: "MT",
      specifications: {},
      status: "draft",
      visibility: "public",
    };

    setupAuth("owner", ["supplier"], false, staleDraft);

    vi.mocked(apiClient.PATCH).mockResolvedValueOnce({
      response: { ok: false, status: 409 } as Response,
      data: { detail: "Optimistic concurrency conflict. State has advanced." },
      error: { detail: "Optimistic concurrency conflict. State has advanced." },
    } as never);

    render(
      <Wrapper>
        <SupplyListingBuilderClient locale="fa" initialListingId="listing-stale-123" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByDisplayValue("1000")).toBeInTheDocument();
    });

    // Change value and save
    const quantityInput = screen.getByDisplayValue("1000");
    fireEvent.change(quantityInput, { target: { value: "1200" } });

    const saveButton = screen.getByText("ذخیره پیش‌نویس");
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(screen.getByText("تداخل ویرایش همزمان (نسخه منقضی)")).toBeInTheDocument();
      expect(
        screen.getByText("اطلاعات پیش‌نویس توسط عملیات یا کاربر دیگری تغییر کرده است. آخرین اطلاعات از سرور دریافت شد. لطفاً تغییرات خود را مجدداً بررسی کنید.")
      ).toBeInTheDocument();
    });
  });

  it("8. Multi-commodity dynamic rendering: renders Bitumen and Base Oil without branching", async () => {
    const user = userEvent.setup();
    setupAuth("owner", ["supplier"]);

    render(
      <Wrapper>
        <SupplyListingBuilderClient locale="fa" />
      </Wrapper>
    );

    const combobox = await screen.findByRole("combobox", { name: /نوع کالا/ });

    // Select Bitumen
    await user.click(combobox);
    const bitumenOption = await screen.findByRole("option", { name: /قیر/ });
    await user.click(bitumenOption);

    await waitFor(() => {
      expect(screen.getByText("درجه نفوذ")).toBeInTheDocument();
      expect(screen.getByText("نقطه نرمی")).toBeInTheDocument();
    });

    // Switch to Base Oil
    await user.click(combobox);
    const baseOilOption = await screen.findByRole("option", { name: /روغن پایه/ });
    await user.click(baseOilOption);

    await waitFor(() => {
      expect(screen.getByText("گرانروی در ۴۰ درجه")).toBeInTheDocument();
      expect(screen.getByText("نقطه اشتعال")).toBeInTheDocument();
      expect(screen.queryByText("درجه نفوذ")).not.toBeInTheDocument();
    });
  });

  it("9. Dynamic specification backend errors: maps structured errors to fields", async () => {
    const user = userEvent.setup();
    setupAuth("owner", ["supplier"]);

    vi.mocked(apiClient.POST).mockResolvedValueOnce({
      response: { ok: false, status: 400 } as Response,
      data: {
        detail: "Dynamic specifications validation failed.",
        errors: [
          { field: "penetration_grade", message: "This field is required." },
          { field: "softening_point", message: "Value must be at least 30." },
        ],
      },
      error: {
        detail: "Dynamic specifications validation failed.",
        errors: [
          { field: "penetration_grade", message: "This field is required." },
          { field: "softening_point", message: "Value must be at least 30." },
        ],
      },
    } as never);

    render(
      <Wrapper>
        <SupplyListingBuilderClient locale="fa" />
      </Wrapper>
    );

    // Select Bitumen & enter quantity
    const combobox = await screen.findByRole("combobox", { name: /نوع کالا/ });
    await user.click(combobox);
    const bitumenOption = await screen.findByRole("option", { name: /قیر/ });
    await user.click(bitumenOption);

    fireEvent.change(screen.getByPlaceholderText("مثال: ۱۰۰۰"), { target: { value: "100" } });

    // Save draft to trigger backend validation errors
    fireEvent.click(screen.getByText("ذخیره پیش‌نویس"));

    await waitFor(() => {
      expect(screen.getByText("Dynamic specifications validation failed.")).toBeInTheDocument();
      expect(screen.getByText("This field is required.")).toBeInTheDocument();
      expect(screen.getByText("Value must be at least 30.")).toBeInTheDocument();
    });
  });

  it("10. Commercial and availability fields rendering: renders all supported T0508 fields", async () => {
    const user = userEvent.setup();
    setupAuth("owner", ["supplier"]);

    render(
      <Wrapper>
        <SupplyListingBuilderClient locale="fa" />
      </Wrapper>
    );

    // Select commodity & quantity
    const combobox = await screen.findByRole("combobox", { name: /نوع کالا/ });
    await user.click(combobox);
    const bitumenOption = await screen.findByRole("option", { name: /قیر/ });
    await user.click(bitumenOption);

    fireEvent.change(screen.getByPlaceholderText("مثال: ۱۰۰۰"), { target: { value: "500" } });

    vi.mocked(apiClient.POST).mockResolvedValueOnce({
      response: { ok: true, status: 201 } as Response,
      data: { id: "listing-step2", version: 1, status: "draft" },
    } as never);

    // Advance to Step 2
    fireEvent.click(screen.getByText("مرحله بعد"));

    await waitFor(() => {
      expect(screen.getByText("شرایط تجاری، جغرافیا و بازه زمانی")).toBeInTheDocument();
      expect(screen.getByText("قیمت پیشنهادی / شاخص (اختیاری)")).toBeInTheDocument();
      expect(screen.getByText("ارز معامله")).toBeInTheDocument();
      expect(screen.getByText("شرایط پرداخت")).toBeInTheDocument();
      expect(screen.getByText("قاعده اینکوترمز (Incoterm)")).toBeInTheDocument();
      expect(screen.getByText("مبدأ بارگیری / کارخانه")).toBeInTheDocument();
      expect(screen.getByText("مقصد مجاز (در صورت محدودیت)")).toBeInTheDocument();
      expect(screen.getByText("آغاز بازه عرضه")).toBeInTheDocument();
      expect(screen.getByText("پایان بازه عرضه")).toBeInTheDocument();
      expect(screen.getByText("توضیحات و الزامات کیفی")).toBeInTheDocument();
      expect(screen.getByText("یادداشت‌های داخلی سازمان (محرمانه)")).toBeInTheDocument();
    });
  });

  it("11. Preview & Explicit Activation: activates draft via explicit endpoint and expected_version", async () => {
    const user = userEvent.setup();
    const existingDraft = {
      id: "listing-preview-123",
      version: 1,
      commodity_id: "comm-bitumen-id",
      commodity_code: "bitumen",
      schema_version_id: schemas.bitumen.id,
      quantity: "5000",
      unit: "MT",
      specifications: { penetration_grade: "60/70" },
      indicative_price: "420.00",
      currency: "USD",
      payment_terms: "LC at sight",
      incoterm: "FOB",
      origin: "Bandar Abbas",
      status: "draft",
      visibility: "public",
    };

    setupAuth("owner", ["supplier"], false, existingDraft);

    vi.mocked(apiClient.POST).mockImplementation(async (url: string) => {
      if (url === "/api/trade-hub/supply-listings/{listing_id}/activate/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            ...existingDraft,
            version: 2,
            status: "active",
          },
        } as never;
      }
      return { response: { ok: false, status: 400 } as Response } as never;
    });

    render(
      <Wrapper>
        <SupplyListingBuilderClient locale="fa" initialListingId="listing-preview-123" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByDisplayValue("5000")).toBeInTheDocument();
    });

    // Jump to Step 4 (Preview & Activate)
    const step4Btn = screen.getByRole("button", { name: /پیش‌نمایش و فعال‌سازی/ });
    await user.click(step4Btn);

    await waitFor(() => {
      expect(screen.getByText("پیش‌نمایش آگهی عرضه کالا")).toBeInTheDocument();
      expect(screen.getByText("420.00 USD")).toBeInTheDocument();
      expect(screen.getByText("Bandar Abbas")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /فعال‌سازی آگهی/ })).toBeInTheDocument();
    });

    // Click Activate Listing
    const activateBtn = screen.getByRole("button", { name: /فعال‌سازی آگهی/ });
    await user.click(activateBtn);

    await waitFor(() => {
      expect(apiClient.POST).toHaveBeenCalledWith(
        "/api/trade-hub/supply-listings/{listing_id}/activate/",
        expect.objectContaining({
          params: { path: { listing_id: "listing-preview-123" } },
          body: { expected_version: 1 },
        })
      );
      expect(mockPush).toHaveBeenCalledWith("/fa/trade-hub/supply-listings/listing-preview-123");
    });
  });

  it("12. Detail View (Owner projection): exposes internal notes and owner controls", async () => {
    const listingOwnerData = {
      id: "listing-detail-123",
      version: 2,
      organization: mockSupplierOrg,
      commodity_id: "comm-bitumen-id",
      commodity_code: "bitumen",
      commodity_name_fa: "قیر",
      commodity_name_en: "Bitumen",
      schema_version_id: schemas.bitumen.id,
      schema_version_number: 1,
      specifications: { penetration_grade: "60/70" },
      quantity: "5000",
      unit: "MT",
      indicative_price: "410.00",
      currency: "USD",
      payment_terms: "TT",
      incoterm: "CIF",
      origin: "Isfahan",
      destination: "Mumbai",
      availability_window_start: "2026-10-01",
      availability_window_end: "2026-10-31",
      quality_notes: "SGS certificate available",
      notes: "Internal confidential note for supplier",
      status: "active",
      visibility: "public",
      created_by_operator: true,
      activated_at: "2026-09-01T10:00:00Z",
      closed_at: null,
      expired_at: null,
      created_at: "2026-09-01T09:00:00Z",
      updated_at: "2026-09-01T10:00:00Z",
    };

    setupAuth("owner", ["supplier"], false, listingOwnerData);

    render(
      <Wrapper>
        <SupplyListingDetailClient locale="fa" listingId="listing-detail-123" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("قیر")).toBeInTheDocument();
      expect(screen.getByText("فعال")).toBeInTheDocument();
      expect(screen.getByText("ثبت‌شده توسط اپراتور")).toBeInTheDocument();
      expect(screen.getByText("Internal confidential note for supplier")).toBeInTheDocument();
      expect(screen.getByText("این یادداشت تنها برای سازمان تأمین‌کننده و اپراتور سیستم قابل مشاهده است.")).toBeInTheDocument();
      expect(screen.getByText("بستن آگهی")).toBeInTheDocument();
    });
  });

  it("13. Detail View (External safe projection): hides internal notes and owner action controls", async () => {
    // External viewer belongs to a different organization (Buyer Corp)
    const listingPublicData = {
      id: "listing-detail-ext-123",
      version: 2,
      organization: mockSupplierOrg, // Owned by supplier
      commodity_id: "comm-bitumen-id",
      commodity_code: "bitumen",
      commodity_name_fa: "قیر",
      commodity_name_en: "Bitumen",
      schema_version_id: schemas.bitumen.id,
      schema_version_number: 1,
      specifications: { penetration_grade: "60/70" },
      quantity: "5000",
      unit: "MT",
      indicative_price: "410.00",
      currency: "USD",
      payment_terms: "TT",
      incoterm: "CIF",
      origin: "Isfahan",
      destination: "Mumbai",
      availability_window_start: "2026-10-01",
      availability_window_end: "2026-10-31",
      quality_notes: "SGS certificate available",
      status: "active",
      visibility: "public",
      activated_at: "2026-09-01T10:00:00Z",
      created_at: "2026-09-01T09:00:00Z",
    };

    // User is logged into Buyer Org
    vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            id: 2,
            email: "buyer@example.com",
            system_roles: [],
            organizations: [
              {
                organization: mockBuyerOrg,
                role: "owner",
                capabilities: ["buyer"],
              },
            ],
          },
        } as never;
      }
      if (url === "/api/trade-hub/supply-listings/{listing_id}/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: listingPublicData,
        } as never;
      }
      if (url === "/api/commodity-schemas/{id}/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: schemas.bitumen,
        } as never;
      }
      return { response: { ok: false, status: 404 } as Response } as never;
    });

    render(
      <Wrapper>
        <SupplyListingDetailClient locale="fa" listingId="listing-detail-ext-123" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("قیر")).toBeInTheDocument();
      expect(screen.getByText("فعال")).toBeInTheDocument();
      // External viewer should not see internal notes or owner actions
      expect(screen.queryByText("یادداشت‌های داخلی سازمان (محرمانه)")).not.toBeInTheDocument();
      expect(screen.queryByText("بستن آگهی")).not.toBeInTheDocument();
      expect(screen.queryByText("ویرایش پیش‌نویس")).not.toBeInTheDocument();
    });
  });

  it("14. Exact Schema Binding: historical listing uses stored schema version v1 even if commodity updated to v2", async () => {
    const historicalListing = {
      id: "listing-historical-v1",
      version: 3,
      organization: mockSupplierOrg,
      commodity_id: "comm-bitumen-id",
      commodity_code: "bitumen",
      commodity_name_fa: "قیر",
      commodity_name_en: "Bitumen",
      schema_version_id: "bitumen-v1", // Stored schema version is v1
      schema_version_number: 1,
      specifications: { penetration_grade: "60/70" },
      quantity: "2000",
      unit: "MT",
      status: "active",
      visibility: "public",
    };

    setupAuth("owner", ["supplier"], false, historicalListing);

    render(
      <Wrapper>
        <SupplyListingDetailClient locale="fa" listingId="listing-historical-v1" />
      </Wrapper>
    );

    await waitFor(() => {
      // Must load exact schema v1 via /api/commodity-schemas/bitumen-v1/
      expect(apiClient.GET).toHaveBeenCalledWith(
        "/api/commodity-schemas/{id}/",
        expect.objectContaining({ params: { path: { id: "bitumen-v1" } } })
      );
      // Confirms rendering v1 attribute label
      expect(screen.getByText("درجه نفوذ")).toBeInTheDocument();
      // Does not render v2 attribute label ("درجه نفوذ جدید")
      expect(screen.queryByText("درجه نفوذ جدید")).not.toBeInTheDocument();
    });
  });

  it("15. Close listing: closes active listing using expected_version and confirmation modal", async () => {
    const user = userEvent.setup();
    const activeListing = {
      id: "listing-to-close-123",
      version: 2,
      organization: mockSupplierOrg,
      commodity_id: "comm-bitumen-id",
      commodity_code: "bitumen",
      commodity_name_fa: "قیر",
      commodity_name_en: "Bitumen",
      schema_version_id: schemas.bitumen.id,
      schema_version_number: 1,
      specifications: {},
      quantity: "5000",
      unit: "MT",
      status: "active",
      visibility: "public",
    };

    setupAuth("owner", ["supplier"], false, activeListing);

    vi.mocked(apiClient.POST).mockImplementation(async (url: string) => {
      if (url === "/api/trade-hub/supply-listings/{listing_id}/close/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            ...activeListing,
            version: 3,
            status: "closed",
          },
        } as never;
      }
      return { response: { ok: false, status: 400 } as Response } as never;
    });

    render(
      <Wrapper>
        <SupplyListingDetailClient locale="fa" listingId="listing-to-close-123" />
      </Wrapper>
    );

    const closeBtn = await screen.findByRole("button", { name: "بستن آگهی" });
    await user.click(closeBtn);

    await waitFor(() => {
      expect(screen.getByText("تأیید بستن آگهی عرضه")).toBeInTheDocument();
    });

    // Confirm close in modal
    const modal = screen.getByText("تأیید بستن آگهی عرضه").closest("div[class*='fixed']")!;
    const confirmBtn = within(modal as HTMLElement).getByRole("button", { name: "بستن آگهی" });
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(apiClient.POST).toHaveBeenCalledWith(
        "/api/trade-hub/supply-listings/{listing_id}/close/",
        expect.objectContaining({
          params: { path: { listing_id: "listing-to-close-123" } },
          body: { expected_version: 2 },
        })
      );
      expect(screen.getByText("بسته‌شده")).toBeInTheDocument();
    });
  });

  it("16. Hidden / Unauthorized listing direct route renders safe 404 view", async () => {
    setupAuth("owner", ["supplier"]);

    vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: { id: 1, email: "u@ex.com", system_roles: [], organizations: [{ organization: mockSupplierOrg, role: "owner", capabilities: ["supplier"] }] },
        } as never;
      }
      if (url === "/api/trade-hub/supply-listings/{listing_id}/") {
        return {
          response: { ok: false, status: 404 } as Response,
          data: { detail: "Supply listing not found." },
        } as never;
      }
      return { response: { ok: false, status: 404 } as Response } as never;
    });

    render(
      <Wrapper>
        <SupplyListingDetailClient locale="fa" listingId="hidden-uuid-999" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("آگهی پیدا نشد")).toBeInTheDocument();
      expect(
        screen.getByText("این آگهی عرضه وجود ندارد یا شما دسترسی لازم برای مشاهده آن را ندارید.")
      ).toBeInTheDocument();
      expect(screen.getByText("بازگشت به مرکز معاملات")).toBeInTheDocument();
    });
  });
});
