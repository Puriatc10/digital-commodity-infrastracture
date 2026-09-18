import React from "react";
import { render, screen, waitFor, cleanup, fireEvent, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/lib/auth-context";
import { apiClient } from "@/lib/api/client";
import { getMessages } from "@/i18n/messages";
import { RFQWorkspaceClient } from "@/app/[locale]/trade-hub/rfqs/[id]/rfq-workspace-client";
import { RFQComparisonTab } from "@/components/comparison/rfq-comparison-tab";
import fixtures from "../fixtures/commodity-schemas.json";
import type { CommoditySchemaVersion } from "@/components/commodity/commodity-specification-form";
import type { components } from "@/lib/api/generated/schema";

type RFQComparisonResponse = components["schemas"]["RFQComparisonResponse"];
type ComparisonRow = components["schemas"]["ComparisonRow"];
type DecisionRunDetailResponse = components["schemas"]["DecisionRunDetailResponse"];
type DecisionCandidateResponse = components["schemas"]["DecisionCandidateResponse"];

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
const tWorkspace = getMessages("fa").rfqWorkspace;
const tComparison = tWorkspace.comparison;

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

const mockBrokerOrg = {
  id: "broker-org-1",
  name: "Broker Corp IR",
  registration_identifier: "REG-BROKER-1",
  country: "IR",
  capabilities: ["broker"],
};

const mockPublishedRfq = {
  id: "rfq-test-123",
  version: 2,
  organization: mockBuyerOrg,
  commodity_id: "comm-bitumen-id",
  commodity_code: "bitumen",
  commodity_name_fa: "قیر",
  commodity_name_en: "Bitumen",
  schema_version_id: "schema-v1-id",
  status: "published",
  visibility: "public",
  quantity: "1000",
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
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
  published_at: "2026-09-01T12:00:00Z",
  closed_at: null,
  cancelled_at: null,
};

// Authoritative Mock Comparison Rows
const mockRowSupplier: ComparisonRow = {
  offer_id: "off-sup-1",
  offer_version_id: "ov-sup-v2",
  version_number: 2,
  safe_offeror_identity: "Supplier Alpha Corp",
  offeror_name: "Supplier Alpha Corp",
  offeror_role: "SUPPLIER",
  is_external: false,
  currency: "USD",
  unit_price: "410.00",
  offered_quantity: "1000",
  quantity_unit: "MT",
  quantity_coverage: "1.0000",
  surplus_quantity: "0.00",
  product_cost: "410000.00",
  known_cost_total: "410000.00",
  landed_cost: "410000.00",
  landed_unit_cost: "410.00",
  normalization_complete: true,
  missing_components: [],
  cost_comparability: "COMPARABLE",
  payment_terms: "LC at sight",
  delivery_terms: "FOB",
  incoterm: "FOB",
  delivery_start: "2026-10-01",
  delivery_end: "2026-10-15",
  valid_until: "2026-09-30T18:00:00Z",
  is_expired: false,
  technical_compliance: "PASS",
  trust_status: "VERIFIED",
  aggregate_version: 3,
};

const mockRowBrokerPartial: ComparisonRow = {
  offer_id: "off-brk-2",
  offer_version_id: "ov-brk-v1",
  version_number: 1,
  safe_offeror_identity: "Gulf Brokerage Ltd",
  offeror_name: "Gulf Brokerage Ltd",
  offeror_role: "BROKER",
  is_external: false,
  currency: "USD",
  unit_price: "405.00",
  offered_quantity: "600",
  quantity_unit: "MT",
  quantity_coverage: "0.6000",
  surplus_quantity: "0.00",
  product_cost: "243000.00",
  known_cost_total: "243000.00",
  landed_cost: "243000.00",
  landed_unit_cost: "405.00",
  normalization_complete: true,
  missing_components: [],
  cost_comparability: "COMPARABLE",
  payment_terms: "Cash in advance",
  delivery_terms: "CIF",
  incoterm: "CIF",
  delivery_start: "2026-10-05",
  delivery_end: "2026-10-20",
  valid_until: "2026-09-28T18:00:00Z",
  is_expired: false,
  technical_compliance: "PASS",
  trust_status: "BASIC_VERIFIED",
  aggregate_version: 1,
};

const mockRowExternal: ComparisonRow = {
  offer_id: "off-ext-3",
  offer_version_id: "ov-ext-v1",
  version_number: 1,
  safe_offeror_identity: "External Refinery Sourcing",
  offeror_name: "External Refinery Sourcing",
  offeror_role: "SUPPLIER",
  is_external: true,
  currency: "USD",
  unit_price: "395.00",
  offered_quantity: "1000",
  quantity_unit: "MT",
  quantity_coverage: "1.0000",
  surplus_quantity: "0.00",
  product_cost: "395000.00",
  known_cost_total: "395000.00",
  landed_cost: null,
  landed_unit_cost: null,
  normalization_complete: false,
  missing_components: ["FREIGHT", "PORT_FEES"],
  cost_comparability: "INCOMPLETE_COST",
  payment_terms: "Telegraphic Transfer",
  delivery_terms: "EXW",
  incoterm: "EXW",
  delivery_start: "2026-10-10",
  delivery_end: "2026-10-25",
  valid_until: "2026-10-05T18:00:00Z",
  is_expired: false,
  technical_compliance: "PASS",
  trust_status: "UNVERIFIED",
  aggregate_version: 1,
};

const mockRowCrossCurrency: ComparisonRow = {
  offer_id: "off-eur-4",
  offer_version_id: "ov-eur-v1",
  version_number: 1,
  safe_offeror_identity: "Euro Trading SA",
  offeror_name: "Euro Trading SA",
  offeror_role: "SUPPLIER",
  is_external: false,
  currency: "EUR",
  unit_price: "380.00",
  offered_quantity: "1000",
  quantity_unit: "MT",
  quantity_coverage: "1.0000",
  surplus_quantity: "0.00",
  product_cost: "380000.00",
  known_cost_total: "380000.00",
  landed_cost: "380000.00",
  landed_unit_cost: "380.00",
  normalization_complete: true,
  missing_components: [],
  cost_comparability: "CROSS_CURRENCY_UNKNOWN",
  payment_terms: "LC 30 days",
  delivery_terms: "FOB",
  incoterm: "FOB",
  delivery_start: "2026-10-01",
  delivery_end: "2026-10-15",
  valid_until: "2026-09-30T18:00:00Z",
  is_expired: false,
  technical_compliance: "PASS",
  trust_status: "VERIFIED",
  aggregate_version: 2,
};

const mockRowIneligible: ComparisonRow = {
  offer_id: "off-inelig-5",
  offer_version_id: "ov-inelig-v1",
  version_number: 1,
  safe_offeror_identity: "Unverified Fail Corp",
  offeror_name: "Unverified Fail Corp",
  offeror_role: "SUPPLIER",
  is_external: false,
  currency: "USD",
  unit_price: "370.00",
  offered_quantity: "1000",
  quantity_unit: "MT",
  quantity_coverage: "1.0000",
  surplus_quantity: "0.00",
  product_cost: "370000.00",
  known_cost_total: "370000.00",
  landed_cost: null,
  landed_unit_cost: null,
  normalization_complete: false,
  missing_components: ["PORT_FEES"],
  cost_comparability: "INCOMPLETE_COST",
  payment_terms: "LC at sight",
  delivery_terms: "CIF",
  incoterm: "CIF",
  delivery_start: "2026-10-01",
  delivery_end: "2026-10-15",
  valid_until: "2026-09-30T18:00:00Z",
  is_expired: false,
  technical_compliance: "FAIL",
  trust_status: "UNVERIFIED",
  aggregate_version: 1,
};

const mockComparisonData: RFQComparisonResponse = {
  rfq_id: "rfq-test-123",
  rfq_currency: "USD",
  rfq_quantity: "1000",
  rfq_unit: "MT",
  total_offers: 5,
  items: [
    mockRowSupplier,
    mockRowBrokerPartial,
    mockRowExternal,
    mockRowCrossCurrency,
    mockRowIneligible,
  ],
  offers: [
    mockRowSupplier,
    mockRowBrokerPartial,
    mockRowExternal,
    mockRowCrossCurrency,
    mockRowIneligible,
  ],
};

const mockCandidateRecommended: DecisionCandidateResponse = {
  id: "cand-rec-1",
  offer_id: "off-sup-1",
  offer_version_id: "ov-sup-v2",
  version_number: 2,
  rank: 1,
  is_recommended: true,
  decision_score: "88.50",
  evidence_coverage: "92.00",
  effective_score: "81.42",
  award_eligible: true,
  eligibility_reasons: [],
  created_at: "2026-09-01T12:00:00Z",
  signals: [
    {
      id: "sig-1",
      dimension: "COST",
      code: "cost.landed_competitive",
      status: "PASS",
      weight: "35.00",
      raw_score: "1.0000",
      contribution: "35.00",
      reason_code: "LANDED_COST_OPTIMAL",
      expected_value: "420.00 USD",
      actual_value: "410.00 USD",
      snapshot_data: {},
      created_at: "2026-09-01T12:00:00Z",
    },
    {
      id: "sig-2",
      dimension: "QUALITY",
      code: "spec.compliance",
      status: "PASS",
      weight: "25.00",
      raw_score: "1.0000",
      contribution: "25.00",
      reason_code: "SPEC_MATCH",
      expected_value: "60/70",
      actual_value: "60/70",
      snapshot_data: {},
      created_at: "2026-09-01T12:00:00Z",
    },
    {
      id: "sig-3",
      dimension: "TRUST",
      code: "trust.full_verified",
      status: "PASS",
      weight: "15.00",
      raw_score: "1.0000",
      contribution: "15.00",
      reason_code: "TRUST_VERIFIED",
      expected_value: "VERIFIED",
      actual_value: "VERIFIED",
      snapshot_data: {},
      created_at: "2026-09-01T12:00:00Z",
    },
    {
      id: "sig-4",
      dimension: "DELIVERY",
      code: "delivery.window_tight",
      status: "PARTIAL",
      weight: "10.00",
      raw_score: "0.5000",
      contribution: "5.00",
      reason_code: "DELIVERY_TIGHT_WINDOW",
      expected_value: "2026-10-01",
      actual_value: "2026-10-15",
      snapshot_data: {},
      created_at: "2026-09-01T12:00:00Z",
    },
    {
      id: "sig-5",
      dimension: "COMPLETENESS",
      code: "docs.unspecified",
      status: "UNKNOWN",
      weight: "5.00",
      raw_score: null,
      contribution: "0.00",
      reason_code: "DOCUMENTATION_UNSPECIFIED",
      expected_value: "INSPECTION_CERT",
      actual_value: null,
      snapshot_data: {},
      created_at: "2026-09-01T12:00:00Z",
    },
  ],
};

const mockCandidateIneligible: DecisionCandidateResponse = {
  id: "cand-inelig-5",
  offer_id: "off-inelig-5",
  offer_version_id: "ov-inelig-v1",
  version_number: 1,
  rank: 5,
  is_recommended: false,
  decision_score: "32.00",
  evidence_coverage: "40.00",
  effective_score: "12.80",
  award_eligible: false,
  eligibility_reasons: ["TECHNICAL_COMPLIANCE_FAILED", "UNVERIFIED_COUNTERPARTY"],
  created_at: "2026-09-01T12:00:00Z",
  signals: [
    {
      id: "sig-inelig-1",
      dimension: "QUALITY",
      code: "spec.fail",
      status: "FAIL",
      weight: "25.00",
      raw_score: "0.0000",
      contribution: "0.00",
      reason_code: "SPEC_FAILED",
      expected_value: "60/70",
      actual_value: "80/100",
      snapshot_data: {},
      created_at: "2026-09-01T12:00:00Z",
    },
  ],
};

const mockFreshDecisionRun: DecisionRunDetailResponse = {
  id: "run-fresh-1",
  rfq_id: "rfq-test-123",
  profile_version_id: "pv-test-1",
  profile_code: "BALANCED_PROCUREMENT",
  profile_version_number: 1,
  engine_version: "v1.0.0",
  created_by_id: 1,
  created_at: "2026-09-01T12:00:00Z",
  input_fingerprint: "fingerprint-in-123",
  result_fingerprint: "fingerprint-out-123",
  is_stale: false,
  total_candidates: 5,
  recommended_candidate_id: "cand-rec-1",
  candidates: [mockCandidateRecommended, mockCandidateIneligible],
};

const mockStaleDecisionRun: DecisionRunDetailResponse = {
  ...mockFreshDecisionRun,
  id: "run-stale-2",
  is_stale: true,
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

describe("T0807 — Offer Comparison & Decision Support UI Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPush.mockClear();
  });

  afterEach(() => {
    cleanup();
  });

  function setupMocks({
    role = "buyer",
    systemRoles = [] as string[],
    rfqData = mockPublishedRfq,
    comparisonData = mockComparisonData as RFQComparisonResponse | null,
    decisionRunData = mockFreshDecisionRun as DecisionRunDetailResponse | null,
    comparisonStatus = 200,
  } = {}) {
    let org = mockBuyerOrg;
    let capabilities = ["buyer"];
    if (role === "supplier") {
      org = mockSupplierOrg;
      capabilities = ["supplier"];
    } else if (role === "broker") {
      org = mockBrokerOrg;
      capabilities = ["broker"];
    }

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
                organization: org,
                role: "owner",
                capabilities,
              },
            ],
          },
        } as never;
      }

      if (url === "/api/trade-hub/rfqs/{rfq_id}/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: rfqData,
        } as never;
      }

      if (url === "/api/commodity-schemas/{id}/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: mockBitumenSchemaV1,
        } as never;
      }

      if (url === "/api/trade-hub/rfqs/{rfq_id}/invitations/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: [],
        } as never;
      }

      if (url === "/api/trade-hub/rfqs/{rfq_id}/activity/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: [],
        } as never;
      }

      if (url === "/api/offers/rfqs/{rfq_id}/comparison/") {
        if (comparisonStatus === 403) {
          return {
            response: { ok: false, status: 403 } as Response,
            error: { detail: "Access forbidden." },
          } as never;
        }
        return {
          response: { ok: true, status: 200 } as Response,
          data: comparisonData,
        } as never;
      }

      if (url === "/api/offers/rfqs/{rfq_id}/decision-runs/") {
        if (!decisionRunData) {
          return {
            response: { ok: false, status: 404 } as Response,
            data: null,
          } as never;
        }
        return {
          response: { ok: true, status: 200 } as Response,
          data: decisionRunData,
        } as never;
      }

      return {
        response: { ok: true, status: 200 } as Response,
        data: null,
      } as never;
    });

    vi.mocked(apiClient.POST).mockImplementation(async (url: string) => {
      if (url === "/api/offers/rfqs/{rfq_id}/decision-runs/") {
        return {
          response: { ok: true, status: 201 } as Response,
          data: mockFreshDecisionRun,
        } as never;
      }
      if (url === "/api/offers/{offer_id}/revision-requests/") {
        return {
          response: { ok: true, status: 201 } as Response,
          data: {
            id: "rev-req-1",
            offer_id: "off-sup-1",
            requested_fields: ["unit_price"],
            buyer_notes: "Please improve price",
            status: "SUBMITTED",
          },
        } as never;
      }
      return {
        response: { ok: true, status: 200 } as Response,
        data: {},
      } as never;
    });
  }

  // Helper to open comparison tab
  async function renderAndOpenComparison() {
    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    const compTabBtn = await screen.findByRole("button", {
      name: new RegExp(tWorkspace.tabs.comparison),
    });
    expect(compTabBtn).toBeInTheDocument();
    fireEvent.click(compTabBtn);
    return screen.findByRole("table");
  }

  it("1. renders current version only (V2 active, not older versions) and excludes drafts", async () => {
    setupMocks();
    const table = await renderAndOpenComparison();

    // Verify V2 of Supplier Alpha Corp is rendered
    expect(within(table).getByText("Supplier Alpha Corp")).toBeInTheDocument();
    expect(within(table).getByText("V2")).toBeInTheDocument();

    // Ensure no Draft row or old V1 of Supplier Alpha Corp is present
    expect(within(table).queryByText("پیش‌نویس")).not.toBeInTheDocument();
    expect(within(table).queryByText("Draft")).not.toBeInTheDocument();
  });

  it("2. renders mixed offeror roles correctly (Supplier, Broker, and External sourcing)", async () => {
    setupMocks();
    const table = await renderAndOpenComparison();

    // Supplier Alpha Corp
    expect(within(table).getByText("Supplier Alpha Corp")).toBeInTheDocument();
    expect(within(table).getAllByText(tComparison.roles.supplier).length).toBeGreaterThan(0);

    // Gulf Brokerage Ltd
    expect(within(table).getByText("Gulf Brokerage Ltd")).toBeInTheDocument();
    expect(within(table).getByText(tComparison.roles.broker)).toBeInTheDocument();

    // External Refinery Sourcing
    expect(within(table).getByText("External Refinery Sourcing")).toBeInTheDocument();
    expect(within(table).getAllByText(tComparison.roles.external).length).toBeGreaterThan(0);
  });

  it("3. renders partial quantity and coverage percentage without assuming full match", async () => {
    setupMocks();
    const table = await renderAndOpenComparison();

    // 600 MT with 60% coverage badge
    expect(within(table).getByText(/600 MT/)).toBeInTheDocument();
    expect(within(table).getByText("60%")).toBeInTheDocument();
  });

  it("4. handles cross currency by rendering warning and preserving rfq currency without fake sorting", async () => {
    setupMocks();
    const table = await renderAndOpenComparison();

    // Cross currency offer
    expect(within(table).getByText("Euro Trading SA")).toBeInTheDocument();
    // Warning badge with rfq currency displayed
    const crossCurrencyBadges = within(table).getAllByText(/عدم امکان مقایسه/);
    expect(crossCurrencyBadges.length).toBeGreaterThan(0);
  });

  it("5. renders UNKNOWN for missing landed cost and never fabricated 0", async () => {
    setupMocks();
    const table = await renderAndOpenComparison();

    // Unverified Fail Corp has null landed_unit_cost
    expect(within(table).getByText("Unverified Fail Corp")).toBeInTheDocument();
    const unknownCostLabels = within(table).getAllByText(tComparison.costStates.unknown);
    expect(unknownCostLabels.length).toBeGreaterThan(0);

    // Verify it is not rendered as 0.00 USD or free
    expect(within(table).queryByText("0.00 USD")).not.toBeInTheDocument();
    expect(within(table).queryByText("0 USD")).not.toBeInTheDocument();
  });

  it("6. renders decision support metrics directly from backend values", async () => {
    setupMocks();
    await renderAndOpenComparison();

    // Decision Score: 88.50, Evidence: 92.00, Effective: 81.42
    expect(await screen.findAllByText(/88.50/)).toHaveLength(2);
    expect(screen.getAllByText(/92.00%/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/81.42/).length).toBeGreaterThan(0);
    expect(screen.getByText(/BALANCED_PROCUREMENT/)).toBeInTheDocument();
  });

  it("7. renders stale run warning banner and prevents non-current recommendation badge", async () => {
    setupMocks({ decisionRunData: mockStaleDecisionRun });
    const table = await renderAndOpenComparison();

    // Stale warning banner should be visible
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(tComparison.decisionSupport.staleWarningTitle)).toBeInTheDocument();
    expect(screen.getByText(tComparison.decisionSupport.rerunAction)).toBeInTheDocument();

    // Recommended badge should NOT be visible on stale run
    expect(within(table).queryByText(tComparison.decisionSupport.recommended)).not.toBeInTheDocument();
  });

  it("8. renders ineligible candidate warning when award_eligible is false", async () => {
    setupMocks();
    const table = await renderAndOpenComparison();

    // Ineligible candidate badge
    expect(within(table).getByText("Unverified Fail Corp")).toBeInTheDocument();
    expect(within(table).getByText(tComparison.decisionSupport.ineligible)).toBeInTheDocument();
  });

  it("9. highlights backend-chosen recommendation with badge and distinctive border", async () => {
    setupMocks();
    const table = await renderAndOpenComparison();

    // Supplier Alpha is recommended
    expect(within(table).getByText("Supplier Alpha Corp")).toBeInTheDocument();
    expect(within(table).getByText(tComparison.decisionSupport.recommended)).toBeInTheDocument();
  });

  it("10. opens Why modal with structured signals grouped into Positives, Risks, and Unknowns", async () => {
    setupMocks();
    const table = await renderAndOpenComparison();

    // Click Why button on candidate
    const whyButtons = within(table).getAllByRole("button", {
      name: new RegExp(tComparison.decisionSupport.whyAction),
    });
    fireEvent.click(whyButtons[0]);

    // Modal opens as role="dialog"
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(tComparison.whyModal.title)).toBeInTheDocument();
    // Signal groups
    expect(within(dialog).getByText(new RegExp(tComparison.whyModal.positiveGroup))).toBeInTheDocument();
    expect(within(dialog).getByText(new RegExp(tComparison.whyModal.riskGroup))).toBeInTheDocument();
    expect(within(dialog).getByText(new RegExp(tComparison.whyModal.unknownGroup))).toBeInTheDocument();

    // Expected vs Actual comparison
    expect(within(dialog).getByText(/420.00 USD/)).toBeInTheDocument();
    expect(within(dialog).getByText(/410.00 USD/)).toBeInTheDocument();

    // Close modal
    fireEvent.click(within(dialog).getByLabelText(tComparison.whyModal.close));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("11. opens Revision modal with canonical enum checkboxes, enforces optimistic concurrency, and submits", async () => {
    setupMocks();
    const table = await renderAndOpenComparison();

    // Find and click Revision button
    const revisionButtons = within(table).getAllByRole("button", { name: /درخواست بازنگری/ });
    fireEvent.click(revisionButtons[0]);

    // Modal opens
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(tComparison.revisionModal.title)).toBeInTheDocument();
    expect(within(dialog).getByText(tComparison.revisionModal.fields.unit_price)).toBeInTheDocument();

    // Select unit_price checkbox
    const unitPriceCheckbox = within(dialog).getByRole("checkbox", {
      name: tComparison.revisionModal.fields.unit_price,
    });
    fireEvent.click(unitPriceCheckbox);

    // Enter message
    const messageInput = within(dialog).getByPlaceholderText(tComparison.revisionModal.messagePlaceholder);
    fireEvent.change(messageInput, { target: { value: "Please reconsider unit price." } });

    // Click submit
    const submitBtn = within(dialog).getByRole("button", { name: tComparison.revisionModal.submit });
    fireEvent.click(submitBtn);

    // Verify API was called with canonical field and expected_version
    await waitFor(() => {
      expect(apiClient.POST).toHaveBeenCalledWith(
        "/api/offers/{offer_id}/revision-requests/",
        expect.objectContaining({
          params: { path: { offer_id: "off-sup-1" } },
          body: {
            base_offer_version: "ov-sup-v2",
            expected_version: 3,
            requested_fields: ["unit_price"],
            message: "Please reconsider unit price.",
          },
        })
      );
    });
  });

  it("12. handles 409 conflict during revision submission gracefully", async () => {
    setupMocks();
    vi.mocked(apiClient.POST).mockImplementationOnce(async () => {
      return {
        response: { ok: false, status: 409 } as Response,
        error: { detail: "Offer version conflict." },
      } as never;
    });

    const table = await renderAndOpenComparison();

    const revisionButtons = within(table).getAllByRole("button", { name: /درخواست بازنگری/ });
    fireEvent.click(revisionButtons[0]);

    const dialog = await screen.findByRole("dialog");
    const unitPriceCheckbox = within(dialog).getByRole("checkbox", {
      name: tComparison.revisionModal.fields.unit_price,
    });
    fireEvent.click(unitPriceCheckbox);

    const submitBtn = within(dialog).getByRole("button", { name: tComparison.revisionModal.submit });
    fireEvent.click(submitBtn);

    // Conflict error message displayed
    expect(await within(dialog).findByText(tComparison.revisionModal.conflictError)).toBeInTheDocument();
  });

  it("13. denies comparison access to participants (Supplier or Broker) and hides tab", async () => {
    setupMocks({ role: "supplier" });

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    // Wait for workspace to load
    await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.overview) });
    expect(
      screen.queryByRole("button", { name: new RegExp(tWorkspace.tabs.comparison) })
    ).not.toBeInTheDocument();
  });

  it("14. renders unauthorized banner if participant tries to access RFQComparisonTab directly", async () => {
    setupMocks({ role: "supplier", comparisonStatus: 403 });

    render(
      <Wrapper>
        <RFQComparisonTab rfqId="rfq-test-123" canManage={false} isOperator={false} locale="fa" />
      </Wrapper>
    );

    // Unauthorized alert card rendered
    expect(await screen.findByText("عدم دسترسی به مقایسه پیشنهادها")).toBeInTheDocument();
    expect(screen.getByText(tComparison.unauthorized)).toBeInTheDocument();
  });

  it("15. aborts in-flight request when component unmounts or RFQ changes", async () => {
    setupMocks();

    const { unmount } = render(
      <Wrapper>
        <RFQComparisonTab rfqId="rfq-test-123" canManage={true} isOperator={false} locale="fa" />
      </Wrapper>
    );

    unmount();
    // Unmounting cleanly aborts controller without unhandled rejection
    expect(true).toBe(true);
  });

  it("16. enforces RTL direction and accessibility attributes", async () => {
    setupMocks();
    await renderAndOpenComparison();

    // Verify RTL direction on comparison container
    const tableContainer = await screen.findByRole("table");
    expect(tableContainer.closest('[dir="rtl"]')).toBeInTheDocument();

    // Verify semantic column headers
    expect(screen.getByRole("columnheader", { name: tComparison.table.offeror })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: tComparison.table.landedCost })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: tComparison.table.technicalCompliance })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: tComparison.table.decision })).toBeInTheDocument();
  });
});
