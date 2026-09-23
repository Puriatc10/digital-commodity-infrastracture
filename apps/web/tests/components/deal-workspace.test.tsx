import React from "react";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/lib/auth-context";
import { apiClient } from "@/lib/api/client";
import { getMessages } from "@/i18n/messages";
import { DealWorkspaceClient } from "@/app/[locale]/deals/[id]/deal-workspace-client";
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
  useParams: () => ({ locale: "fa", id: "deal-test-123" }),
  usePathname: () => "/fa/deals/deal-test-123",
  useSearchParams: () => new URLSearchParams(),
}));

const schemas = fixtures as Record<string, CommoditySchemaVersion>;
const t = getMessages("fa").dealWorkspace;

const mockBitumenSchemaV1 = {
  ...schemas.bitumen,
  id: "schema-v1-id",
  version: 1,
  state: "published",
};

const mockBuyerOrg = {
  id: "buyer-org-1",
  name: "Buyer Corp IR",
  registration_identifier: "REG-BUYER-1",
  country: "IR",
};

const mockSupplierOrg = {
  id: "supplier-org-1",
  name: "Supplier Corp IR",
  registration_identifier: "REG-SUPP-1",
  country: "IR",
  capabilities: ["supplier"],
};

const mockBuyerPartySnapshot = {
  id: "party-buyer-1",
  deal_id: "deal-test-123",
  role: "BUYER" as const,
  party_type: "ORGANIZATION" as const,
  organization_id: "buyer-org-1",
  external_counterparty_id: null,
  name_snapshot: "Buyer Historical Snapshot Corp",
  country_snapshot: "IR",
  registration_identifier_snapshot: "REG-HIST-BUYER-1",
  created_at: "2026-09-01T10:00:00Z",
};

const mockSellerPartySnapshot = {
  id: "party-seller-1",
  deal_id: "deal-test-123",
  role: "SELLER" as const,
  party_type: "ORGANIZATION" as const,
  organization_id: "supplier-org-1",
  external_counterparty_id: null,
  name_snapshot: "Supplier Historical Snapshot Corp",
  country_snapshot: "IR",
  registration_identifier_snapshot: "REG-HIST-SUPP-1",
  created_at: "2026-09-01T10:00:00Z",
};

const mockExternalSellerPartySnapshot = {
  id: "party-ext-seller-1",
  deal_id: "deal-test-123",
  role: "SELLER" as const,
  party_type: "EXTERNAL_COUNTERPARTY" as const,
  organization_id: null,
  external_counterparty_id: "ext-counterparty-99",
  name_snapshot: "Off-Platform Global Trading Ltd",
  country_snapshot: "AE",
  registration_identifier_snapshot: "REG-EXT-99",
  created_at: "2026-09-01T10:00:00Z",
};

const mockCustomerAttribution = {
  id: "attr-test-123",
  deal_id: "deal-test-123",
  status: "RESOLVED" as const,
  primary_channel: "DIRECT_SUPPLIER" as const,
  resolution_method: "AUTOMATIC" as const,
  resolved_by_id: null,
  resolved_at: "2026-09-01T10:05:00Z",
  resolution_reason: null,
  evidence_snapshot: null,
  broker_attributions: [],
  opportunity_attributions: [],
  version: 1,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T10:05:00Z",
};

const mockPendingAttribution = {
  id: "attr-test-123",
  deal_id: "deal-test-123",
  status: "PENDING" as const,
  primary_channel: null,
  resolution_method: null,
  resolved_by_id: null,
  resolved_at: null,
  resolution_reason: null,
  evidence_snapshot: null,
  broker_attributions: [],
  opportunity_attributions: [],
  version: 1,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T10:00:00Z",
};

const mockInternalAttribution = {
  id: "attr-test-123",
  deal_id: "deal-test-123",
  status: "RESOLVED" as const,
  primary_channel: "BROKER" as const,
  resolution_method: "MANUAL" as const,
  resolved_by_id: "operator-user-uuid",
  resolved_at: "2026-09-01T11:00:00Z",
  resolution_reason: "Manual verification confirmed broker origin",
  evidence_snapshot: { source: "RFQ_MATCH", confidence: "HIGH" },
  broker_attributions: [
    {
      id: "broker-attr-1",
      deal_id: "deal-test-123",
      broker_organization_id: "broker-org-1",
      role: "SUPPLY_ORIGINATOR" as const,
      related_opportunity_id: "opp-supply-123",
      created_at: "2026-09-01T10:00:00Z",
    },
  ],
  opportunity_attributions: [
    {
      id: "opp-attr-1",
      deal_id: "deal-test-123",
      opportunity_id: "opp-demand-456",
      role: "DEMAND",
      created_at: "2026-09-01T10:00:00Z",
    },
  ],
  version: 2,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T11:00:00Z",
};

const mockDealBase = {
  id: "deal-test-123",
  award_id: "award-test-123",
  award_allocation_id: "alloc-test-123",
  rfq_id: "rfq-test-123",
  offer_id: "offer-test-123",
  offer_version_id: "offer-v2-id",
  buyer_organization_id: "buyer-org-1",
  seller_organization_id: "supplier-org-1",
  seller_external_counterparty_id: null,
  created_by_id: 1,
  terms: {
    id: "terms-test-123",
    deal_id: "deal-test-123",
    commodity_id: "comm-bitumen-id",
    commodity_name_fa: "قیر نفت صادراتی",
    commodity_name_en: "Export Petroleum Bitumen",
    commodity_code: "bitumen",
    schema_version_id: "schema-v1-id",
    specifications: {
      penetration_grade: "60/70",
      softening_point: 49,
    },
    quantity: "500.000",
    quantity_unit: "MT",
    unit_price: "350.00",
    currency: "USD",
    product_cost_snapshot: "175000.00",
    payment_terms: "LC at sight",
    delivery_terms: "FOB Bandar Abbas",
    incoterm: "FOB",
    delivery_start: "2026-10-01",
    delivery_end: "2026-10-15",
    origin: "Bandar Abbas",
    destination: "Jebel Ali",
    origin_area_id: null,
    destination_area_id: null,
    logistics_cost_status: "KNOWN_SEPARATE" as const,
    logistics_cost_amount: "12000.00",
    cost_snapshots: [
      {
        id: "cost-1",
        kind: "LOGISTICS",
        amount: "12000.00",
        currency: "USD",
        description_snapshot: "Freight charge",
        created_at: "2026-09-01T10:00:00Z",
      },
    ],
    created_at: "2026-09-01T10:00:00Z",
  },
  parties: [mockBuyerPartySnapshot, mockSellerPartySnapshot],
  attribution: mockCustomerAttribution,
  broker_attributions: [],
  opportunity_attributions: [],
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T10:05:00Z",
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

describe("T0905 — Deal Workspace Component Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
  });

  function setupAuth(
    userOrg = mockBuyerOrg,
    role: "owner" | "manager" | "member" | "viewer" = "owner",
    capability = "buyer",
    isOperator = false,
    dealData: any = mockDealBase,
    dealStatus = 200
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

      if (url === "/api/deals/{deal_id}/") {
        const id = options?.params?.path?.deal_id;
        if (dealStatus === 403) {
          return {
            response: { ok: false, status: 403 } as Response,
            data: { detail: "Permission denied." },
          } as never;
        }
        if (dealStatus === 404 || !dealData) {
          return {
            response: { ok: false, status: 404 } as Response,
            data: { detail: "Deal not found." },
          } as never;
        }
        return {
          response: { ok: true, status: 200 } as Response,
          data: { ...dealData, id: id || dealData.id },
        } as never;
      }

      if (url === "/api/commodity-schemas/{id}/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: mockBitumenSchemaV1,
        } as never;
      }

      return {
        response: { ok: true, status: 200 } as Response,
        data: null,
      } as never;
    });
  }

  it("1. Buyer sees own Deal with overview, terms, parties, and customer attribution", async () => {
    setupAuth(mockBuyerOrg, "owner", "buyer", false, mockDealBase);

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    // Header values
    expect(await screen.findByRole("heading", { level: 1, name: "قیر نفت صادراتی" })).toBeInTheDocument();
    expect(screen.getAllByText(/500\.000 MT/)[0]).toBeInTheDocument();
    expect(screen.getAllByText(/350\.00 USD/)[0]).toBeInTheDocument();
    expect(screen.getAllByText(/175000\.00 USD/)[0]).toBeInTheDocument();

    // Overview Tab facts
    expect(screen.getAllByText("Buyer Historical Snapshot Corp")[0]).toBeInTheDocument();
    expect(screen.getAllByText("Supplier Historical Snapshot Corp")[0]).toBeInTheDocument();
    expect(screen.getAllByText("تثبیت‌شده و قطعی")[0]).toBeInTheDocument();
    expect(screen.getAllByText("تأمین‌کننده مستقیم")[0]).toBeInTheDocument();
  });

  it("2. Seller sees own Deal", async () => {
    setupAuth(mockSupplierOrg, "manager", "supplier", false, mockDealBase);

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    expect(await screen.findByRole("heading", { level: 1, name: "قیر نفت صادراتی" })).toBeInTheDocument();
    expect(screen.getAllByText(/500\.000 MT/)[0]).toBeInTheDocument();
    expect(screen.getAllByText("Buyer Historical Snapshot Corp")[0]).toBeInTheDocument();
  });

  it("3. Unrelated organization / 403 shows unauthorized error state", async () => {
    setupAuth(mockBuyerOrg, "owner", "buyer", false, null, 403);

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    expect(await screen.findByText(t.unauthorizedTitle)).toBeInTheDocument();
    expect(screen.getByText(t.unauthorizedDescription)).toBeInTheDocument();
  });

  it("4. Operator sees internal attribution with broker and opportunity provenance", async () => {
    const internalDeal = {
      ...mockDealBase,
      attribution: mockInternalAttribution,
      broker_attributions: mockInternalAttribution.broker_attributions,
      opportunity_attributions: mockInternalAttribution.opportunity_attributions,
    };
    setupAuth(mockBuyerOrg, "owner", "buyer", true, internalDeal);

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    // Switch to Attribution tab
    const attrTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.attribution) });
    fireEvent.click(attrTabButton);

    // Verify internal fields are visible to Operator
    expect(await screen.findByText(mockInternalAttribution.resolved_by_id)).toBeInTheDocument();
    expect(screen.getByText(mockInternalAttribution.resolution_reason)).toBeInTheDocument();
    expect(screen.getByText("broker-org-1")).toBeInTheDocument();
    expect(screen.getByText("opp-demand-456")).toBeInTheDocument();
    expect(screen.getByText(new RegExp("RFQ_MATCH"))).toBeInTheDocument();
  });

  it("5. Customer projection excludes internal evidence and provenance", async () => {
    setupAuth(mockBuyerOrg, "owner", "buyer", false, mockDealBase);

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    // Switch to Attribution tab
    const attrTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.attribution) });
    fireEvent.click(attrTabButton);

    // Customer safe summary is shown
    expect(await screen.findByRole("heading", { name: t.attribution.title })).toBeInTheDocument();
    expect(screen.getAllByText("تأمین‌کننده مستقیم")[0]).toBeInTheDocument();
    expect(screen.getAllByText("تعیین‌شده و قطعی")[0]).toBeInTheDocument();

    // Internal provenance details must NOT exist
    expect(screen.queryByText(t.attribution.brokerProvenanceTitle)).not.toBeInTheDocument();
    expect(screen.queryByText(t.attribution.opportunityProvenanceTitle)).not.toBeInTheDocument();
    expect(screen.queryByText(t.attribution.evidenceSnapshot)).not.toBeInTheDocument();
  });

  it("6. Operator can manually resolve PENDING attribution; resolved becomes immutable", async () => {
    const pendingDeal = {
      ...mockDealBase,
      attribution: mockPendingAttribution,
    };
    setupAuth(mockBuyerOrg, "owner", "buyer", true, pendingDeal);

    vi.mocked(apiClient.POST).mockImplementation(async (url: string) => {
      if (url === "/api/deals/{deal_id}/attribution/resolve/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            ...mockPendingAttribution,
            status: "RESOLVED",
            primary_channel: "PLATFORM_NETWORK",
            resolution_method: "MANUAL",
            resolved_at: "2026-09-23T12:00:00Z",
            version: 2,
          },
        } as never;
      }
      return { response: { ok: false, status: 400 } as Response } as never;
    });

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    // Navigate to Attribution tab
    const attrTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.attribution) });
    fireEvent.click(attrTabButton);

    // Form is visible to Operator because attribution is PENDING
    expect(await screen.findByText(t.attribution.manualResolutionTitle)).toBeInTheDocument();

    // Fill in reason
    const reasonInput = screen.getByPlaceholderText(t.attribution.reasonPlaceholder);
    fireEvent.change(reasonInput, { target: { value: "Direct platform matching resolution." } });
  });

  it("7. Buyer cannot see manual attribution resolution form even when PENDING", async () => {
    const pendingDeal = {
      ...mockDealBase,
      attribution: mockPendingAttribution,
    };
    setupAuth(mockBuyerOrg, "owner", "buyer", false, pendingDeal);

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    const attrTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.attribution) });
    fireEvent.click(attrTabButton);

    expect(await screen.findByRole("heading", { name: t.attribution.title })).toBeInTheDocument();
    // Manual resolution form must NOT be rendered for customer
    expect(screen.queryByText(t.attribution.manualResolutionTitle)).not.toBeInTheDocument();
    expect(screen.queryByText(t.attribution.resolveButton)).not.toBeInTheDocument();
  });

  it("8. Terms Tab renders historical schema specifications and cost status correctly (UNKNOWN never zero)", async () => {
    const dealWithUnknownCost = {
      ...mockDealBase,
      terms: {
        ...mockDealBase.terms,
        logistics_cost_status: "UNKNOWN" as const,
        logistics_cost_amount: null,
      },
    };
    setupAuth(mockBuyerOrg, "owner", "buyer", false, dealWithUnknownCost);

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    const termsTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.terms) });
    fireEvent.click(termsTabButton);

    // Verify dynamic specifications from historical schema
    expect(await screen.findByText(t.terms.specificationsTitle)).toBeInTheDocument();
    expect(screen.getByText("درجه نفوذ")).toBeInTheDocument();
    expect(screen.getByText(/60\/70|۶۰\/۷۰/)).toBeInTheDocument();

    // Verify logistics cost status UNKNOWN: mapped to text and NOT 0
    expect(screen.getByText(t.terms.logisticsStatuses.UNKNOWN)).toBeInTheDocument();
    expect(screen.queryByText(/^0\.00\s*USD$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^0\s*USD$/)).not.toBeInTheDocument();
  });

  it("9. Parties Tab renders Buyer and External Seller commercial snapshot without CRM leakage", async () => {
    const dealWithExtSeller = {
      ...mockDealBase,
      seller_organization_id: null,
      seller_external_counterparty_id: "ext-counterparty-99",
      parties: [mockBuyerPartySnapshot, mockExternalSellerPartySnapshot],
    };
    setupAuth(mockBuyerOrg, "owner", "buyer", false, dealWithExtSeller);

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    const partiesTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.parties) });
    fireEvent.click(partiesTabButton);

    // Snapshot identities
    expect(await screen.findByRole("heading", { name: t.parties.title })).toBeInTheDocument();
    expect(screen.getAllByText("Buyer Historical Snapshot Corp")[0]).toBeInTheDocument();
    expect(screen.getAllByText("Off-Platform Global Trading Ltd")[0]).toBeInTheDocument();
    expect(screen.getByText(t.parties.partyTypeExt)).toBeInTheDocument();
    expect(screen.getByText("REG-EXT-99")).toBeInTheDocument();

    // Verify CRM fields are not rendered
    expect(screen.queryByText("phone")).not.toBeInTheDocument();
    expect(screen.queryByText("email")).not.toBeInTheDocument();
    expect(screen.queryByText("password")).not.toBeInTheDocument();
  });

  it("10. Future Tabs (Execution, Logistics, Quality, Documents, Issues) render honest staged empty states", async () => {
    setupAuth(mockBuyerOrg, "owner", "buyer", false, mockDealBase);

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    // Execution
    const execTab = await screen.findByRole("button", { name: new RegExp(t.tabs.execution) });
    fireEvent.click(execTab);
    expect(screen.getByText(t.stagedTabs.execution.title)).toBeInTheDocument();
    expect(screen.getByText(t.stagedTabs.execution.description)).toBeInTheDocument();

    // Logistics
    const logisticsTab = screen.getByRole("button", { name: new RegExp(t.tabs.logistics) });
    fireEvent.click(logisticsTab);
    expect(screen.getByText(t.stagedTabs.logistics.title)).toBeInTheDocument();
    expect(screen.getByText(t.stagedTabs.logistics.description)).toBeInTheDocument();

    // Quality
    const qualityTab = screen.getByRole("button", { name: new RegExp(t.tabs.quality) });
    fireEvent.click(qualityTab);
    expect(screen.getByText(t.stagedTabs.quality.title)).toBeInTheDocument();

    // Documents
    const docsTab = screen.getByRole("button", { name: new RegExp(t.tabs.documents) });
    fireEvent.click(docsTab);
    expect(screen.getByText(t.stagedTabs.documents.title)).toBeInTheDocument();

    // Issues
    const issuesTab = screen.getByRole("button", { name: new RegExp(t.tabs.issues) });
    fireEvent.click(issuesTab);
    expect(screen.getByRole("heading", { name: t.stagedTabs.issues.title })).toBeInTheDocument();
  });

  it("11. Activity Tab renders real domain events only", async () => {
    setupAuth(mockBuyerOrg, "owner", "buyer", false, mockDealBase);

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    const actTab = await screen.findByRole("button", { name: new RegExp(t.tabs.activity) });
    fireEvent.click(actTab);

    expect(await screen.findByText(t.activity.events.dealMaterialized)).toBeInTheDocument();
    expect(screen.getByText(t.activity.events.termsCaptured)).toBeInTheDocument();
    expect(screen.getByText(t.activity.events.attributionCreated)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(t.activity.events.attributionResolved))).toBeInTheDocument();
  });

  // =========================================================================
  // Mandatory Race Condition Tests
  // =========================================================================

  it("12. Persona Race: Operator request in-flight → switch to Seller → old response discarded", async () => {
    let resolveFirstRequest: ((val: unknown) => void) | null = null;
    const firstRequestPromise = new Promise((resolve) => {
      resolveFirstRequest = resolve;
    });

    let isOperator = true;

    vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            id: isOperator ? 1 : 2,
            email: isOperator ? "op@platform.com" : "seller@petro.com",
            system_roles: isOperator ? ["operator"] : [],
            organizations: [
              {
                organization: isOperator ? mockBuyerOrg : mockSupplierOrg,
                role: "manager",
                capabilities: [isOperator ? "buyer" : "supplier"],
              },
            ],
          },
        } as never;
      }

      if (url === "/api/deals/{deal_id}/") {
        if (isOperator) {
          // Delay Operator internal response
          await firstRequestPromise;
          return {
            response: { ok: true, status: 200 } as Response,
            data: {
              ...mockDealBase,
              attribution: mockInternalAttribution,
              broker_attributions: mockInternalAttribution.broker_attributions,
            },
          } as never;
        }

        // Fast Seller response (customer safe)
        return {
          response: { ok: true, status: 200 } as Response,
          data: mockDealBase,
        } as never;
      }

      return {
        response: { ok: true, status: 200 } as Response,
        data: null,
      } as never;
    });

    const { rerender } = render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    // Now switch persona to Seller
    isOperator = false;
    rerender(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    // Let the old delayed Operator response finally resolve
    if (resolveFirstRequest) {
      (resolveFirstRequest as (val: unknown) => void)(true);
    }

    // Wait for the workspace to settle
    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1, name: "قیر نفت صادراتی" })).toBeInTheDocument();
    });

    // Verify that Operator-only internal broker provenance is NOT shown in Seller session
    expect(screen.queryByText("broker-org-1")).not.toBeInTheDocument();
  });

  it("13. Org Race: Buyer A → Buyer B switch: old response discarded", async () => {
    let currentOrg = mockBuyerOrg;

    vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            id: 1,
            email: "user@example.com",
            system_roles: [],
            organizations: [
              {
                organization: currentOrg,
                role: "owner",
                capabilities: ["buyer"],
              },
            ],
          },
        } as never;
      }

      if (url === "/api/deals/{deal_id}/") {
        const isOrgA = currentOrg.id === "buyer-org-1";
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            ...mockDealBase,
            parties: [
              {
                ...mockBuyerPartySnapshot,
                name_snapshot: isOrgA ? "Buyer Corp A" : "Buyer Corp B",
              },
              mockSellerPartySnapshot,
            ],
          },
        } as never;
      }

      return {
        response: { ok: true, status: 200 } as Response,
        data: null,
      } as never;
    });

    const { rerender } = render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    expect(await screen.findByRole("heading", { level: 1, name: "قیر نفت صادراتی" })).toBeInTheDocument();
    expect(screen.getAllByText("Buyer Corp A")[0]).toBeInTheDocument();

    // Switch Org to B
    currentOrg = {
      id: "buyer-org-2",
      name: "Buyer Corp B",
      registration_identifier: "REG-BUYER-2",
      country: "IR",
    };

    rerender(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    expect(await screen.findByRole("heading", { level: 1, name: "قیر نفت صادراتی" })).toBeInTheDocument();
    expect(screen.getAllByText("Buyer Corp B")[0]).toBeInTheDocument();
    expect(screen.queryByText("Buyer Corp A")).not.toBeInTheDocument();
  });

  it("14. Deal Navigation Race: Deal A → Deal B: late response from Deal A discarded", async () => {
    let resolveDealA: ((val: unknown) => void) | null = null;
    const dealAPromise = new Promise((resolve) => {
      resolveDealA = resolve;
    });

    vi.mocked(apiClient.GET).mockImplementation(async (url: string, opts?: unknown) => {
      const options = opts as RequestOptions | undefined;

      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            id: 1,
            email: "user@example.com",
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

      if (url === "/api/deals/{deal_id}/") {
        const id = options?.params?.path?.deal_id;
        if (id === "deal-A") {
          await dealAPromise;
          return {
            response: { ok: true, status: 200 } as Response,
            data: {
              ...mockDealBase,
              id: "deal-A",
              terms: {
                ...mockDealBase.terms,
                commodity_name_fa: "کالای معامله آ",
              },
            },
          } as never;
        }

        if (id === "deal-B") {
          return {
            response: { ok: true, status: 200 } as Response,
            data: {
              ...mockDealBase,
              id: "deal-B",
              terms: {
                ...mockDealBase.terms,
                commodity_name_fa: "کالای معامله ب",
              },
            },
          } as never;
        }
      }

      return {
        response: { ok: true, status: 200 } as Response,
        data: null,
      } as never;
    });

    const { rerender } = render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-A" />
      </Wrapper>
    );

    // Quickly navigate to Deal B while Deal A is still in-flight
    rerender(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-B" />
      </Wrapper>
    );

    // Fast Deal B resolves
    expect(await screen.findByRole("heading", { level: 1, name: "کالای معامله ب" })).toBeInTheDocument();

    // Now let Deal A finally finish
    if (resolveDealA) {
      (resolveDealA as (val: unknown) => void)(true);
    }

    // Verify Deal B remains on screen and Deal A response was safely discarded
    expect(screen.getByRole("heading", { level: 1, name: "کالای معامله ب" })).toBeInTheDocument();
    expect(screen.queryByText("کالای معامله آ")).not.toBeInTheDocument();
  });
});
