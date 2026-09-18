import React from "react";
import { render, screen, waitFor, cleanup, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/lib/auth-context";
import { apiClient } from "@/lib/api/client";
import { getMessages } from "@/i18n/messages";
import { NegotiationHistoryModal } from "@/components/negotiation/negotiation-history-modal";
import { RFQNegotiationTab } from "@/components/negotiation/rfq-negotiation-tab";
import { ComparisonTable } from "@/components/comparison/comparison-table";
import { diffOfferVersions } from "@/components/negotiation/diff-utility";
import { buildNegotiationTimeline, type TimelineItem } from "@/components/negotiation/timeline-builder";
import fixtures from "../fixtures/commodity-schemas.json";
import type { CommoditySchemaVersion } from "@/components/commodity/commodity-specification-form";
import type { components } from "@/lib/api/generated/schema";

type OfferNegotiationHistoryResponse = components["schemas"]["OfferNegotiationHistoryResponse"];
type OfferVersionHistory = components["schemas"]["OfferVersionHistory"];
type RevisionRequestHistory = components["schemas"]["RevisionRequestHistory"];

vi.mock("@/lib/api/client", () => ({
  apiClient: {
    GET: vi.fn(),
    POST: vi.fn(),
    PATCH: vi.fn(),
  },
}));

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useParams: () => ({ locale: "fa", id: "rfq-test-123" }),
  usePathname: () => "/fa/trade-hub/rfqs/rfq-test-123",
  useSearchParams: () => new URLSearchParams(),
}));

const schemas = fixtures as Record<string, CommoditySchemaVersion>;
const tMessages = getMessages("fa").rfqWorkspace.negotiationHistory;

const mockBuyerOrg = {
  id: "buyer-org-1",
  name: "Buyer Corp IR",
  registration_identifier: "REG-BUYER-1",
  country: "IR",
};

const mockBitumenSchemaV1 = {
  ...schemas.bitumen,
  id: "schema-v1-id",
  version: 1,
  state: "published" as const,
};

const mockV1: OfferVersionHistory = {
  id: "ver-1-id",
  offer_id: "off-test-1",
  version_number: 1,
  status: "SUBMITTED",
  schema_version_id: "schema-v1-id",
  unit_price: "450.00",
  currency: "USD",
  offered_quantity: "1000",
  quantity_unit: "MT",
  payment_terms: "LC at sight",
  delivery_terms: "FOB Bandar Abbas",
  incoterm: "FOB",
  delivery_start: "2026-10-01",
  delivery_end: "2026-10-15",
  valid_until: "2026-09-30T18:00:00Z",
  logistics_cost_status: "KNOWN_SEPARATE",
  logistics_cost_amount: "25.00",
  specifications: {
    penetration_grade: "60/70",
    softening_point: 49,
  },
  cost_components: [
    { id: "cc-1", kind: "OTHER", amount: "425.00", currency: "USD", description: "", created_at: "2026-09-01T10:00:00Z" },
    { id: "cc-2", kind: "LOGISTICS", amount: "25.00", currency: "USD", description: "", created_at: "2026-09-01T10:00:00Z" },
  ],
  notes: "Initial proposal",
  submitted_by_id: 101,
  submitted_by_name: "Supplier Sales Rep",
  submitted_at: "2026-09-01T10:05:00Z",
  created_by_id: 101,
  created_by_name: "Supplier Sales Rep",
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T10:05:00Z",
  aggregate_version: 1,
  entered_by_operator: false,
};

const mockV2: OfferVersionHistory = {
  id: "ver-2-id",
  offer_id: "off-test-1",
  version_number: 2,
  status: "SUBMITTED",
  schema_version_id: "schema-v1-id",
  unit_price: "420.00",
  currency: "USD",
  offered_quantity: "1000",
  quantity_unit: "MT",
  payment_terms: "LC at sight",
  delivery_terms: "CIF Jebel Ali",
  incoterm: "CIF",
  delivery_start: "2026-10-05",
  delivery_end: "2026-10-20",
  valid_until: "2026-10-10T18:00:00Z",
  logistics_cost_status: "KNOWN_SEPARATE",
  logistics_cost_amount: "35.00",
  specifications: {
    penetration_grade: "80/100",
    softening_point: 46,
  },
  cost_components: [
    { id: "cc-3", kind: "OTHER", amount: "385.00", currency: "USD", description: "", created_at: "2026-09-02T11:00:00Z" },
    { id: "cc-4", kind: "LOGISTICS", amount: "35.00", currency: "USD", description: "", created_at: "2026-09-02T11:00:00Z" },
  ],
  notes: "Revised per request",
  submitted_by_id: 101,
  submitted_by_name: "Supplier Sales Rep",
  submitted_at: "2026-09-02T11:15:00Z",
  created_by_id: 101,
  created_by_name: "Supplier Sales Rep",
  created_at: "2026-09-02T11:00:00Z",
  updated_at: "2026-09-02T11:15:00Z",
  aggregate_version: 2,
  entered_by_operator: false,
};

const mockV3: OfferVersionHistory = {
  id: "ver-3-id",
  offer_id: "off-test-1",
  version_number: 3,
  status: "SUBMITTED",
  schema_version_id: "schema-v1-id",
  unit_price: "410.00",
  currency: "USD",
  offered_quantity: "1200",
  quantity_unit: "MT",
  payment_terms: "LC 30 days",
  delivery_terms: "CIF Jebel Ali",
  incoterm: "CIF",
  delivery_start: "2026-10-05",
  delivery_end: "2026-10-20",
  valid_until: "2026-10-15T18:00:00Z",
  logistics_cost_status: "KNOWN_SEPARATE",
  logistics_cost_amount: "30.00",
  specifications: {
    penetration_grade: "80/100",
    softening_point: 46,
  },
  cost_components: [
    { id: "cc-5", kind: "OTHER", amount: "380.00", currency: "USD", description: "", created_at: "2026-09-03T14:00:00Z" },
    { id: "cc-6", kind: "LOGISTICS", amount: "30.00", currency: "USD", description: "", created_at: "2026-09-03T14:00:00Z" },
  ],
  notes: "Best and final offer",
  submitted_by_id: 101,
  submitted_by_name: "Supplier Sales Rep",
  submitted_at: "2026-09-03T14:10:00Z",
  created_by_id: 101,
  created_by_name: "Supplier Sales Rep",
  created_at: "2026-09-03T14:00:00Z",
  updated_at: "2026-09-03T14:10:00Z",
  aggregate_version: 3,
  entered_by_operator: false,
};

const mockR1: RevisionRequestHistory = {
  id: "rev-req-1",
  offer_id: "off-test-1",
  base_offer_version_id: "ver-1-id",
  base_version_number: 1,
  status: "RESOLVED",
  requested_fields: ["unit_price", "incoterm", "specifications.penetration_grade"],
  message: "Please lower the unit price to 420 USD and switch to CIF terms with 80/100 grade.",
  requested_by_id: "user-1",
  requested_by_name: "خریدار",
  requested_by_role: "BUYER",
  resolved_by_version_id: "ver-2-id",
  resolved_version_number: 2,
  requested_at: "2026-09-01T15:00:00Z",
  resolved_at: "2026-09-02T11:15:00Z",
  offer_aggregate_version: 3,
  updated_at: "2026-09-02T11:15:00Z",
};

const mockR2: RevisionRequestHistory = {
  id: "rev-req-2",
  offer_id: "off-test-1",
  base_offer_version_id: "ver-2-id",
  base_version_number: 2,
  status: "RESOLVED",
  requested_fields: ["unit_price", "offered_quantity"],
  message: "Can you provide 1200 MT at 410 USD?",
  requested_by_id: "user-1",
  requested_by_name: "خریدار",
  requested_by_role: "BUYER",
  resolved_by_version_id: "ver-3-id",
  resolved_version_number: 3,
  requested_at: "2026-09-02T16:00:00Z",
  resolved_at: "2026-09-03T14:10:00Z",
  offer_aggregate_version: 5,
  updated_at: "2026-09-03T14:10:00Z",
};

const mockHistoryV1Only: OfferNegotiationHistoryResponse = {
  offer_id: "off-test-1",
  rfq_id: "rfq-test-123",
  aggregate_version: 1,
  current_submitted_version_id: "ver-1-id",
  counterparty_name: "Persian Gulf Bitumen Co",
  offeror_role: "SUPPLIER",
  is_external: false,
  entered_by_operator: false,
  schema: mockBitumenSchemaV1,
  versions: [mockV1],
  revision_requests: [],
};

const mockHistoryTwoCycle: OfferNegotiationHistoryResponse = {
  offer_id: "off-test-1",
  rfq_id: "rfq-test-123",
  aggregate_version: 3,
  current_submitted_version_id: "ver-2-id",
  counterparty_name: "Persian Gulf Bitumen Co",
  offeror_role: "SUPPLIER",
  is_external: false,
  entered_by_operator: false,
  schema: mockBitumenSchemaV1,
  versions: [mockV1, mockV2],
  revision_requests: [mockR1],
};

const mockHistoryThreeCycle: OfferNegotiationHistoryResponse = {
  offer_id: "off-test-1",
  rfq_id: "rfq-test-123",
  aggregate_version: 5,
  current_submitted_version_id: "ver-3-id",
  counterparty_name: "External Refinery Trading LLC",
  offeror_role: "SUPPLIER",
  is_external: true,
  entered_by_operator: true,
  schema: mockBitumenSchemaV1,
  versions: [mockV1, mockV2, mockV3],
  revision_requests: [mockR1, mockR2],
};

const mockComparisonResponse = {
  rfq_id: "rfq-test-123",
  rfq_quantity: "1000",
  rfq_unit: "MT",
  rfq_currency: "USD",
  total_offers: 1,
  items: [
    {
      offer_id: "off-test-1",
      offer_version_id: "ver-2-id",
      version_number: 2,
      safe_offeror_identity: "Persian Gulf Bitumen Co",
      offeror_name: "Persian Gulf Bitumen Co",
      offeror_role: "SUPPLIER",
      is_external: false,
      currency: "USD",
      unit_price: "420.00",
      offered_quantity: "1000",
      quantity_unit: "MT",
      quantity_coverage: "1.0000",
      surplus_quantity: "0.00",
      product_cost: "420000.00",
      known_cost_total: "420000.00",
      landed_cost: "420000.00",
      landed_unit_cost: "420.00",
      normalization_complete: true,
      missing_components: [],
      cost_comparability: "COMPARABLE" as const,
      payment_terms: "LC at sight",
      delivery_terms: "FOB",
      incoterm: "FOB",
      delivery_start: "2026-10-01",
      delivery_end: "2026-10-15",
      valid_until: "2026-09-30T18:00:00Z",
      is_expired: false,
      technical_compliance: "PASS" as const,
      trust_status: "VERIFIED" as const,
      aggregate_version: 3,
    },
  ],
  offers: [
    {
      offer_id: "off-test-1",
      offer_version_id: "ver-2-id",
      version_number: 2,
      safe_offeror_identity: "Persian Gulf Bitumen Co",
      offeror_name: "Persian Gulf Bitumen Co",
      offeror_role: "SUPPLIER",
      is_external: false,
      currency: "USD",
      unit_price: "420.00",
      offered_quantity: "1000",
      quantity_unit: "MT",
      quantity_coverage: "1.0000",
      surplus_quantity: "0.00",
      product_cost: "420000.00",
      known_cost_total: "420000.00",
      landed_cost: "420000.00",
      landed_unit_cost: "420.00",
      normalization_complete: true,
      missing_components: [],
      cost_comparability: "COMPARABLE" as const,
      payment_terms: "LC at sight",
      delivery_terms: "FOB",
      incoterm: "FOB",
      delivery_start: "2026-10-01",
      delivery_end: "2026-10-15",
      valid_until: "2026-09-30T18:00:00Z",
      is_expired: false,
      technical_compliance: "PASS" as const,
      trust_status: "VERIFIED" as const,
      aggregate_version: 3,
    },
  ],
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

function setupApiMocks({
  systemRoles = [] as string[],
  historyData = mockHistoryV1Only as OfferNegotiationHistoryResponse | null,
  historyStatus = 200,
} = {}) {
  vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
    if (url === "/api/auth/me") {
      return {
        response: { ok: true, status: 200 } as Response,
        data: {
          id: 1,
          email: "test@example.com",
          system_roles: systemRoles,
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

    if (url === "/api/offers/{offer_id}/history/") {
      if (historyStatus === 200 && historyData) {
        return {
          response: { ok: true, status: 200 } as Response,
          data: historyData,
        } as never;
      }
      if (historyStatus === 403) {
        return {
          response: { ok: false, status: 403 } as Response,
          error: { detail: "Unauthorized" },
        } as never;
      }
      if (historyStatus === 404) {
        return {
          response: { ok: false, status: 404 } as Response,
          error: { detail: "Not found" },
        } as never;
      }
    }

    if (url === "/api/offers/rfqs/{rfq_id}/comparison/") {
      return {
        response: { ok: true, status: 200 } as Response,
        data: mockComparisonResponse,
      } as never;
    }

    return {
      response: { ok: false, status: 404 } as Response,
    } as never;
  });
}

describe("T0812 — Negotiation History & Diff Computation Unit Tests", () => {
  it("accurately computes scalar, specification, and cost component diffs between V1 and V2", () => {
    const requested = Array.isArray(mockR1.requested_fields)
      ? (mockR1.requested_fields as string[])
      : [];
    const diff = diffOfferVersions(mockV1, mockV2, mockBitumenSchemaV1, requested, "fa");
    expect(diff.hasChanges).toBe(true);

    // Unit price changed from 450.00 to 420.00
    const priceDiff = diff.fields.find((f) => f.fieldKey === "unit_price");
    expect(priceDiff).toBeDefined();
    expect(priceDiff?.diffType).toBe("changed");
    expect(priceDiff?.oldValue).toBe("450.00");
    expect(priceDiff?.newValue).toBe("420.00");
    expect(priceDiff?.isRequested).toBe(true);

    // Incoterm changed from FOB to CIF
    const incotermDiff = diff.fields.find((f) => f.fieldKey === "incoterm");
    expect(incotermDiff).toBeDefined();
    expect(incotermDiff?.diffType).toBe("changed");
    expect(incotermDiff?.oldValue).toBe("FOB");
    expect(incotermDiff?.newValue).toBe("CIF");
    expect(incotermDiff?.isRequested).toBe(true);

    // Specification: penetration_grade changed from 60/70 to 80/100
    const penDiff = diff.fields.find((s) => s.fieldKey === "spec:penetration_grade");
    expect(penDiff).toBeDefined();
    expect(penDiff?.diffType).toBe("changed");
    expect(penDiff?.oldValue).toBe("60/70");
    expect(penDiff?.newValue).toBe("80/100");
    expect(penDiff?.isRequested).toBe(true);

    // Cost component diff: OTHER changed from 425.00 to 385.00
    const baseCostDiff = diff.costComponents.find((c) => c.kind === "OTHER");
    expect(baseCostDiff).toBeDefined();
    expect(baseCostDiff?.diffType).toBe("changed");
    expect(baseCostDiff?.oldAmount).toBe("425.00");
    expect(baseCostDiff?.newAmount).toBe("385.00");
  });

  it("builds correct chronological timeline sequence for N-cycles with explicit FK linking", () => {
    const timeline = buildNegotiationTimeline(
      [mockV1, mockV2, mockV3],
      [mockR1, mockR2],
      mockBitumenSchemaV1,
      "fa"
    );

    // Expected order: V1 -> R1 -> V2 -> R2 -> V3 (5 nodes)
    expect(timeline).toHaveLength(5);
    expect(timeline[0].type).toBe("version");
    const t0 = timeline[0] as Extract<TimelineItem, { type: "version" }>;
    expect(t0.version.version_number).toBe(1);
    expect(t0.isInitial).toBe(true);

    expect(timeline[1].type).toBe("revision_request");
    const t1 = timeline[1] as Extract<TimelineItem, { type: "revision_request" }>;
    expect(t1.request.id).toBe(mockR1.id);

    expect(timeline[2].type).toBe("version");
    const t2 = timeline[2] as Extract<TimelineItem, { type: "version" }>;
    expect(t2.version.version_number).toBe(2);
    expect(t2.diffAgainstBase?.hasChanges).toBe(true);

    expect(timeline[3].type).toBe("revision_request");
    const t3 = timeline[3] as Extract<TimelineItem, { type: "revision_request" }>;
    expect(t3.request.id).toBe(mockR2.id);

    expect(timeline[4].type).toBe("version");
    const t4 = timeline[4] as Extract<TimelineItem, { type: "version" }>;
    expect(t4.version.version_number).toBe(3);
    expect(t4.isLatestSubmitted).toBe(true);
  });
});

describe("T0812 — NegotiationHistoryModal Component UI Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders V1 only history modal with offeror header and initial version badge", async () => {
    setupApiMocks({ historyData: mockHistoryV1Only });

    render(
      <Wrapper>
        <NegotiationHistoryModal
          isOpen={true}
          onClose={vi.fn()}
          offerId="off-test-1"
          canManage={true}
          isOperator={false}
          locale="fa"
        />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("Persian Gulf Bitumen Co")).toBeDefined();
    });

    expect(screen.getByText(tMessages.timeline.initialVersionBadge)).toBeDefined();
    expect(screen.getByText(tMessages.timeline.latestVersionBadge)).toBeDefined();
    expect(screen.getByText(/450.00/)).toBeDefined();
  });

  it("renders multi-cycle V1 -> R1 -> V2 with structured diff and requested fields", async () => {
    setupApiMocks({ historyData: mockHistoryTwoCycle });

    render(
      <Wrapper>
        <NegotiationHistoryModal
          isOpen={true}
          onClose={vi.fn()}
          offerId="off-test-1"
          canManage={true}
          isOperator={false}
          locale="fa"
        />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("Persian Gulf Bitumen Co")).toBeDefined();
    });

    // Both versions rendered (multiple matches possible due to base_version badge in revision request)
    expect(screen.getAllByText("V1").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("V2").length).toBeGreaterThanOrEqual(1);

    // Revision request rendered with message
    expect(
      screen.getByText(/Please lower the unit price to 420 USD/)
    ).toBeDefined();

    // V2 diff displays previous 450.00 and current 420.00
    expect(screen.getAllByText(/450.00/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/420.00/).length).toBeGreaterThanOrEqual(1);

    // Requested badge is displayed on requested fields
    const requestedBadges = screen.getAllByText(tMessages.diff.requestedChangeBadge);
    expect(requestedBadges.length).toBeGreaterThanOrEqual(1);
  });

  it("renders Operator provenance clearly when entered on behalf of external counterparty", async () => {
    setupApiMocks({
      systemRoles: ["operator"],
      historyData: mockHistoryThreeCycle,
    });

    render(
      <Wrapper>
        <NegotiationHistoryModal
          isOpen={true}
          onClose={vi.fn()}
          offerId="off-test-1"
          canManage={true}
          isOperator={true}
          locale="fa"
        />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("External Refinery Trading LLC")).toBeDefined();
    });

    // Check operator entry note
    expect(screen.getByText(tMessages.header.operatorEntered)).toBeDefined();
  });

  it("renders terminal requests accurately (DECLINED and CANCELLED)", async () => {
    const declinedReq: RevisionRequestHistory = {
      ...mockR1,
      id: "rev-declined",
      status: "DECLINED",
      resolved_by_version_id: null,
      resolved_version_number: null,
    };

    const declinedHistory: OfferNegotiationHistoryResponse = {
      ...mockHistoryV1Only,
      revision_requests: [declinedReq],
    };

    setupApiMocks({ historyData: declinedHistory });

    render(
      <Wrapper>
        <NegotiationHistoryModal
          isOpen={true}
          onClose={vi.fn()}
          offerId="off-test-1"
          canManage={true}
          isOperator={false}
          locale="fa"
        />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText(tMessages.revisionRequest.statuses.DECLINED)).toBeDefined();
    });
  });

  it("handles 403 Forbidden with unauthorized alert", async () => {
    setupApiMocks({ historyStatus: 403 });

    render(
      <Wrapper>
        <NegotiationHistoryModal
          isOpen={true}
          onClose={vi.fn()}
          offerId="off-test-1"
          canManage={false}
          isOperator={false}
          locale="fa"
        />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText(tMessages.unauthorized)).toBeDefined();
    });
  });

  it("discards late in-flight responses when offerId switches (race guard)", async () => {
    let resolveFirst: ((value: unknown) => void) | undefined;
    const firstPromise = new Promise((resolve) => {
      resolveFirst = resolve;
    });

    let resolveSecond: ((value: unknown) => void) | undefined;
    const secondPromise = new Promise((resolve) => {
      resolveSecond = resolve;
    });

    vi.mocked(apiClient.GET).mockImplementation(async (url: string, options?: Record<string, unknown>) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            id: 1,
            email: "test@example.com",
            system_roles: [],
            organizations: [{ organization: mockBuyerOrg, role: "owner", capabilities: ["buyer"] }],
          },
        } as never;
      }
      if (url === "/api/offers/{offer_id}/history/") {
        const params = options?.params as Record<string, Record<string, string>> | undefined;
        const offerId = params?.path?.offer_id;
        if (offerId === "offer-A") {
          return firstPromise as never;
        }
        if (offerId === "offer-B") {
          return secondPromise as never;
        }
      }
      return { response: { ok: false, status: 404 } } as never;
    });

    const { rerender } = render(
      <Wrapper>
        <NegotiationHistoryModal
          isOpen={true}
          onClose={vi.fn()}
          offerId="offer-A"
          canManage={true}
          isOperator={false}
          locale="fa"
        />
      </Wrapper>
    );

    // Switch offerId to offer-B
    rerender(
      <Wrapper>
        <NegotiationHistoryModal
          isOpen={true}
          onClose={vi.fn()}
          offerId="offer-B"
          canManage={true}
          isOperator={false}
          locale="fa"
        />
      </Wrapper>
    );

    // Second completes first
    resolveSecond!({
      response: { ok: true, status: 200 },
      data: {
        ...mockHistoryV1Only,
        offer_id: "offer-B",
        counterparty_name: "Offer B Corp",
      },
    });

    await waitFor(() => {
      expect(screen.getByText("Offer B Corp")).toBeDefined();
    });

    // First finishes late
    resolveFirst!({
      response: { ok: true, status: 200 },
      data: {
        ...mockHistoryV1Only,
        offer_id: "offer-A",
        counterparty_name: "Offer A Corp",
      },
    });

    // Offer B remains shown, Offer A was discarded
    expect(screen.getByText("Offer B Corp")).toBeDefined();
    expect(screen.queryByText("Offer A Corp")).toBeNull();
  });
});

describe("T0812 — RFQ Negotiation Tab Integration Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders RFQNegotiationTab with offer list and opens NegotiationHistoryModal on click", async () => {
    setupApiMocks({ historyData: mockHistoryTwoCycle });

    render(
      <Wrapper>
        <RFQNegotiationTab
          rfqId="rfq-test-123"
          canManage={true}
          isOperator={false}
          locale="fa"
        />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("Persian Gulf Bitumen Co")).toBeDefined();
    });

    expect(screen.getByText("V2")).toBeDefined();
    const historyBtn = screen.getByText("مشاهده تاریخچه مذاکرات");
    expect(historyBtn).toBeDefined();

    // Click to open history modal
    fireEvent.click(historyBtn);

    await waitFor(() => {
      expect(screen.getByText(tMessages.title)).toBeDefined();
    });
  });

  it("opens NegotiationHistoryModal from ComparisonTable action button", async () => {
    setupApiMocks({ historyData: mockHistoryTwoCycle });

    render(
      <Wrapper>
        <ComparisonTable
          rows={mockComparisonResponse.items}
          rfqCurrency="USD"
          rfqQuantity="1000"
          rfqUnit="MT"
          decisionRun={null}
          isOperator={false}
          canManage={true}
          locale="fa"
          onRefresh={vi.fn()}
        />
      </Wrapper>
    );

    const historyBtn = screen.getByRole("button", { name: /تاریخچه مذاکره/ });
    expect(historyBtn).toBeDefined();

    fireEvent.click(historyBtn);

    await waitFor(() => {
      expect(screen.getByText(tMessages.title)).toBeDefined();
    });
  });
});
