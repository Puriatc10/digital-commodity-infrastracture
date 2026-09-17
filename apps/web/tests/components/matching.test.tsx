import React from "react";
import { render, screen, waitFor, cleanup, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/lib/auth-context";
import { apiClient } from "@/lib/api/client";
import { getMessages } from "@/i18n/messages";
import { RFQWorkspaceClient } from "@/app/[locale]/trade-hub/rfqs/[id]/rfq-workspace-client";
import fixtures from "../fixtures/commodity-schemas.json";
import type { CommoditySchemaVersion } from "@/components/commodity/commodity-specification-form";
import type { components } from "@/lib/api/generated/schema";

type MatchingRun = components["schemas"]["MatchingRunResponse"];
type MatchingCandidate = components["schemas"]["MatchingCandidateResponse"];

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
const tMatching = getMessages("fa").matching;

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
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T12:00:00Z",
  published_at: "2026-09-01T12:00:00Z",
  closed_at: null,
  cancelled_at: null,
};

const mockDraftRfq = {
  ...mockPublishedRfq,
  id: "rfq-draft-456",
  status: "draft",
};

const mockFreshRun: MatchingRun = {
  id: "run-fresh-1",
  rfq_id: "rfq-test-123",
  rfq_version: 2,
  audience: "BUYER",
  policy_version_id: "policy-v1-id",
  policy_version_number: 1,
  engine_version: "1.0.0",
  generated_at: "2026-09-18T10:00:00Z",
  is_stale: false,
  candidate_count: 3,
};

const mockStaleRun: MatchingRun = {
  id: "run-stale-2",
  rfq_id: "rfq-test-123",
  rfq_version: 1, // RFQ aggregate is at v2, so run at v1 is stale
  audience: "BUYER",
  policy_version_id: "policy-v1-id",
  policy_version_number: 1,
  engine_version: "1.0.0",
  generated_at: "2026-09-17T10:00:00Z",
  is_stale: true,
  candidate_count: 3,
};

const mockOperatorRun: MatchingRun = {
  id: "run-op-3",
  rfq_id: "rfq-test-123",
  rfq_version: 2,
  audience: "OPERATOR",
  policy_version_id: "policy-v1-id",
  policy_version_number: 1,
  engine_version: "1.0.0",
  generated_at: "2026-09-18T11:00:00Z",
  is_stale: false,
  candidate_count: 4,
};

const mockDirectSupplyCandidate: MatchingCandidate = {
  id: "cand-ds-1",
  run_id: "run-fresh-1",
  lane: "DIRECT_SUPPLY",
  candidate_kind: "SUPPLY_LISTING",
  eligible: true,
  fit_score: "92.50",
  evidence_coverage: "45.00", // Limited evidence test
  ranking_score: "85.20",
  rank: 1,
  source: {
    listing_id: "listing-abc-1",
    organization_id: "org-supplier-1",
    organization_name: "Pasargad Oil Co",
    verification_status: "verified",
    quantity: "6000",
    unit: "MT",
    origin_area_code: "IR-BA",
    availability_window_start: "2026-10-01",
    availability_window_end: "2026-10-20",
  },
  signals: [
    {
      id: "sig-1",
      dimension: "SPECIFICATION",
      code: "spec.penetration_grade",
      outcome: "PASS",
      is_hard: true,
      weight: "20.00",
      raw_score: "1.0000",
      contribution: "20.00",
      reason_code: "spec_exact_match",
      expected_value: "60/70",
      actual_value: "60/70",
    },
    {
      id: "sig-2",
      dimension: "QUANTITY",
      code: "quantity",
      outcome: "PARTIAL",
      is_hard: false,
      weight: "10.00",
      raw_score: "0.8000",
      contribution: "8.00",
      reason_code: "QUANTITY_PARTIAL_MATCH",
      expected_value: "5000 MT",
      actual_value: "4000 MT",
    },
    {
      id: "sig-3",
      dimension: "GEOGRAPHY",
      code: "geography",
      outcome: "UNKNOWN",
      is_hard: false,
      weight: "10.00",
      raw_score: null,
      contribution: null,
      reason_code: "GEOGRAPHY_UNKNOWN_EVIDENCE",
      expected_value: "IR-BA",
      actual_value: null,
    },
    {
      id: "sig-4",
      dimension: "TRUST",
      code: "trust",
      outcome: "PASS",
      is_hard: false,
      weight: "15.00",
      raw_score: "1.0000",
      contribution: "15.00",
      reason_code: "TRUST_VERIFIED",
    },
    {
      id: "sig-5",
      dimension: "HISTORY",
      code: "history",
      outcome: "NOT_APPLICABLE",
      is_hard: false,
      weight: "5.00",
      raw_score: null,
      contribution: null,
      reason_code: "HISTORICAL_DATA_NOT_APPLICABLE",
    },
  ],
};

const mockPotentialSupplierCandidate: MatchingCandidate = {
  id: "cand-ps-1",
  run_id: "run-fresh-1",
  lane: "POTENTIAL_SUPPLIER",
  candidate_kind: "SUPPLIER_ORGANIZATION",
  eligible: true,
  fit_score: "78.00",
  evidence_coverage: "80.00",
  ranking_score: "78.00",
  rank: 1, // Independent lane rank #1
  source: {
    organization_id: "org-supplier-pot-1",
    organization_name: "Tehran Bitumen Refinery",
    verification_status: "basic_verified",
    operating_areas: ["IR-TEH", "IR-ALZ"],
  },
  signals: [
    {
      id: "sig-ps-1",
      dimension: "TRUST",
      code: "trust",
      outcome: "PASS",
      is_hard: false,
      weight: "15.00",
      raw_score: "0.7000",
      contribution: "10.50",
      reason_code: "TRUST_BASIC_VERIFIED",
    },
  ],
};

const mockBrokerCandidate: MatchingCandidate = {
  id: "cand-br-1",
  run_id: "run-fresh-1",
  lane: "BROKER_PATH",
  candidate_kind: "BROKER_ORGANIZATION",
  eligible: true,
  fit_score: null,
  evidence_coverage: null,
  ranking_score: "65.00",
  rank: 1, // Independent lane rank #1
  source: {
    organization_id: "org-broker-1",
    organization_name: "Persian Gulf Brokerage",
    verification_status: "verified",
    operating_areas: ["IR-HOR"],
  },
  signals: [
    {
      id: "sig-br-1",
      dimension: "TRUST",
      code: "trust",
      outcome: "PASS",
      is_hard: false,
      weight: "20.00",
      raw_score: "1.0000",
      contribution: "20.00",
      reason_code: "TRUST_VERIFIED",
    },
  ],
};

const mockOpportunityCandidate: MatchingCandidate = {
  id: "cand-opp-1",
  run_id: "run-op-3",
  lane: "DIRECT_SUPPLY",
  candidate_kind: "SUPPLY_OPPORTUNITY",
  eligible: true,
  fit_score: "89.00",
  evidence_coverage: "60.00",
  ranking_score: "81.00",
  rank: 2,
  source: {
    opportunity_id: "opp-internal-999",
    is_external: true,
    counterparty_name: "Global Petroleum Lead",
    origin_area_code: "IR-ESF",
  },
  signals: [],
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

describe("T0708 — Matching UI Component Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPush.mockClear();
  });

  afterEach(() => {
    cleanup();
  });

  function setupMocks({
    isOperator = false,
    runs = [mockFreshRun],
    candidates = [
      mockDirectSupplyCandidate,
      mockPotentialSupplierCandidate,
      mockBrokerCandidate,
    ],
    rfqData = mockPublishedRfq,
    invitations = [] as components["schemas"]["RFQInvitationResponse"][],
  } = {}) {
    vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            id: 1,
            email: "user@example.com",
            system_roles: isOperator ? ["operator"] : [],
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
          data: invitations,
        } as never;
      }

      if (url === "/api/trade-hub/rfqs/{rfq_id}/activity/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: [],
        } as never;
      }

      if (url === "/api/matching/rfqs/{rfq_id}/runs/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: runs,
        } as never;
      }

      if (url === "/api/matching/runs/{run_id}/candidates/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: candidates,
        } as never;
      }

      return {
        response: { ok: true, status: 200 } as Response,
        data: null,
      } as never;
    });

    vi.mocked(apiClient.POST).mockImplementation(async (url: string) => {
      if (url === "/api/matching/rfqs/{rfq_id}/runs/") {
        return {
          response: { ok: true, status: 201 } as Response,
          data: mockFreshRun,
        } as never;
      }
      if (url === "/api/trade-hub/rfqs/{rfq_id}/invitations/") {
        return {
          response: { ok: true, status: 201 } as Response,
          data: { id: "inv-new-1" },
        } as never;
      }
      return {
        response: { ok: true, status: 200 } as Response,
        data: {},
      } as never;
    });
  }

  it("renders the Matches navigation tab for authorized Buyer and opens matching view", async () => {
    setupMocks();

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    // Matches tab button should be visible in navigation
    const matchesTabBtn = await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.matches) });
    expect(matchesTabBtn).toBeInTheDocument();

    // Click Matches tab
    fireEvent.click(matchesTabBtn);

    // Header and description should appear
    expect(await screen.findByText(tMatching.tabTitle)).toBeInTheDocument();
    expect(screen.getByText(tMatching.tabSubtitle)).toBeInTheDocument();
  });

  it("renders all three lanes visually separate with independent ranking", async () => {
    setupMocks();

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.matches) }));

    // 1. Direct Supply lane
    expect(await screen.findByText(tMatching.lanes.DIRECT_SUPPLY.title)).toBeInTheDocument();
    expect(await screen.findByText("Pasargad Oil Co")).toBeInTheDocument();

    // 2. Potential Supplier lane
    expect(screen.getByText(tMatching.lanes.POTENTIAL_SUPPLIER.title)).toBeInTheDocument();
    expect(screen.getByText("Tehran Bitumen Refinery")).toBeInTheDocument();

    // 3. Broker Path lane
    expect(screen.getByText(tMatching.lanes.BROKER_PATH.title)).toBeInTheDocument();
    expect(screen.getByText("Persian Gulf Brokerage")).toBeInTheDocument();

    // All three candidates have rank #1 in their respective lanes (independent ranking)
    const rankBadges = screen.getAllByText("#1");
    expect(rankBadges.length).toBe(3);
  });

  it("renders Direct Supply card with separate Fit, Coverage, and Ranking score, highlighting limited evidence", async () => {
    setupMocks();

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.matches) }));

    await screen.findByText("Pasargad Oil Co");

    // Fit score: 92.50%
    expect(screen.getByText("92.50٪")).toBeInTheDocument();
    // Coverage: 45.00%
    expect(screen.getByText("45.00٪")).toBeInTheDocument();
    // Ranking score: 85.20%
    expect(screen.getByText("85.20٪")).toBeInTheDocument();

    // Limited evidence badge because coverage (45) < 50
    expect(screen.getByText(tMatching.scores.limitedEvidence)).toBeInTheDocument();

    // Quantity and availability
    expect(screen.getByText("6000 MT")).toBeInTheDocument();
    expect(screen.getByText(/2026-10-01.*2026-10-20/)).toBeInTheDocument();

    // Geography origin code
    expect(screen.getByText("IR-BA")).toBeInTheDocument();
  });

  it("displays mandatory availability disclaimer on Potential Supplier card without invented supply data", async () => {
    setupMocks();

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.matches) }));

    await screen.findByText("Tehran Bitumen Refinery");

    // Clear disclaimer that availability is not confirmed
    expect(screen.getByText(tMatching.lanes.POTENTIAL_SUPPLIER.disclaimer)).toBeInTheDocument();

    // Operating areas
    expect(screen.getByText("IR-TEH")).toBeInTheDocument();
    expect(screen.getByText("IR-ALZ")).toBeInTheDocument();
  });

  it("displays Broker card with Broker Relevance terminology and sourcing path disclaimer", async () => {
    setupMocks();

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.matches) }));

    await screen.findByText("Persian Gulf Brokerage");

    // Relevance terminology
    expect(screen.getByText(tMatching.scores.brokerRelevance)).toBeInTheDocument();
    expect(screen.getByText("65.00٪")).toBeInTheDocument();

    // Sourcing path disclaimer
    expect(screen.getByText(tMatching.lanes.BROKER_PATH.disclaimer)).toBeInTheDocument();
  });

  it("opens explanation dialog ('Why this match?') showing dimensions, outcomes, and localized reason codes", async () => {
    setupMocks();

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.matches) }));

    // Click 'Why this match?' on Direct Supply candidate
    const whyMatchBtns = await screen.findAllByRole("button", { name: new RegExp(tMatching.actions.whyMatch) });
    fireEvent.click(whyMatchBtns[0]);

    // Dialog title
    expect(await screen.findByText(tMatching.explanation.title)).toBeInTheDocument();

    // Dimension headers
    expect(screen.getByText(tMatching.explanation.dimensions.SPECIFICATION)).toBeInTheDocument();
    expect(screen.getByText(tMatching.explanation.dimensions.QUANTITY)).toBeInTheDocument();
    expect(screen.getByText(tMatching.explanation.dimensions.GEOGRAPHY)).toBeInTheDocument();
    expect(screen.getByText(tMatching.explanation.dimensions.TRUST)).toBeInTheDocument();
    expect(screen.getByText(tMatching.explanation.dimensions.HISTORY)).toBeInTheDocument();

    // Outcomes: PASS, PARTIAL, UNKNOWN, NOT_APPLICABLE
    expect(screen.getAllByText(tMatching.explanation.outcomes.PASS).length).toBeGreaterThan(0);
    expect(screen.getByText(tMatching.explanation.outcomes.PARTIAL)).toBeInTheDocument();
    expect(screen.getByText(tMatching.explanation.outcomes.UNKNOWN)).toBeInTheDocument();
    expect(screen.getByText(tMatching.explanation.outcomes.NOT_APPLICABLE)).toBeInTheDocument();

    // Localized reason codes
    expect(screen.getByText(tMatching.reasonCodes.spec_exact_match)).toBeInTheDocument();
    expect(screen.getByText(tMatching.reasonCodes.QUANTITY_PARTIAL_MATCH)).toBeInTheDocument();
    expect(screen.getByText(tMatching.reasonCodes.GEOGRAPHY_UNKNOWN_EVIDENCE)).toBeInTheDocument();

    // Close dialog
    fireEvent.click(screen.getAllByRole("button", { name: tMatching.explanation.close })[0]);
    await waitFor(() => {
      expect(screen.queryByText(tMatching.explanation.title)).not.toBeInTheDocument();
    });
  });

  it("enforces Buyer privacy boundary: Buyer cannot see Supply Opportunity candidate", async () => {
    // Both Direct Supply listing and Opportunity candidate returned in candidates list
    setupMocks({
      isOperator: false, // Buyer persona
      candidates: [mockDirectSupplyCandidate, mockOpportunityCandidate],
    });

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.matches) }));

    // Direct Supply Listing is visible
    expect(await screen.findByText("Pasargad Oil Co")).toBeInTheDocument();

    // Opportunity candidate must NOT be rendered for Buyer
    expect(screen.queryByText("Global Petroleum Lead")).not.toBeInTheDocument();
    expect(screen.queryByText(tMatching.candidateKinds.SUPPLY_OPPORTUNITY)).not.toBeInTheDocument();
  });

  it("renders Qualified Supply Opportunity candidate with Opportunity Desk link for Operator persona", async () => {
    setupMocks({
      isOperator: true, // Operator persona
      runs: [mockOperatorRun],
      candidates: [mockDirectSupplyCandidate, mockOpportunityCandidate],
    });

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.matches) }));

    // Opportunity candidate is visible for Operator
    expect(await screen.findByText("Global Petroleum Lead")).toBeInTheDocument();
    expect(screen.getByText(tMatching.candidateKinds.SUPPLY_OPPORTUNITY)).toBeInTheDocument();

    // Action button to open opportunity in Opportunity Desk
    const openOppBtn = screen.getByRole("button", { name: new RegExp(tMatching.actions.openOpportunity) });
    expect(openOppBtn).toBeInTheDocument();

    fireEvent.click(openOppBtn);
    expect(mockPush).toHaveBeenCalledWith("/fa/opportunities/opp-internal-999");
  });

  it("displays explicit stale warning when is_stale is true and offers explicit rerun", async () => {
    setupMocks({
      runs: [mockStaleRun],
    });

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.matches) }));

    // Stale warning title and description
    expect(await screen.findByText(tMatching.stale.title)).toBeInTheDocument();
    expect(screen.getByText(tMatching.stale.warning)).toBeInTheDocument();
    expect(screen.getByText(tMatching.stale.badge)).toBeInTheDocument();

    // Explicit rerun button exists
    const rerunBtns = screen.getAllByRole("button", { name: new RegExp(tMatching.actions.rerun) });
    expect(rerunBtns.length).toBeGreaterThan(0);

    // Clicking rerun triggers POST /api/matching/rfqs/{rfq_id}/runs/
    fireEvent.click(rerunBtns[0]);
    await waitFor(() => {
      expect(apiClient.POST).toHaveBeenCalledWith(
        "/api/matching/rfqs/{rfq_id}/runs/",
        expect.objectContaining({
          params: { path: { rfq_id: "rfq-test-123" } },
          body: { audience: "BUYER" },
        })
      );
    });
  });

  it("supports safe domain action: invites supplier using RFQ invitation API", async () => {
    setupMocks();

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.matches) }));

    // Click 'Invite Supplier'
    const inviteBtns = await screen.findAllByRole("button", { name: new RegExp(tMatching.actions.inviteSupplier) });
    fireEvent.click(inviteBtns[0]);

    await waitFor(() => {
      expect(apiClient.POST).toHaveBeenCalledWith(
        "/api/trade-hub/rfqs/{rfq_id}/invitations/",
        expect.objectContaining({
          params: { path: { rfq_id: "rfq-test-123" } },
          body: { organization_id: "org-supplier-1" },
        })
      );
    });

    // Success feedback rendered
    expect(await screen.findByText(tMatching.states.inviteSuccess)).toBeInTheDocument();
  });

  it("shows disabled 'already invited' state if organization is already in invitations", async () => {
    setupMocks({
      invitations: [
        {
          id: "inv-already-1",
          rfq_id: "rfq-test-123",
          organization: {
            id: "org-supplier-1",
            name: "Pasargad Oil Co",
            country: "IR",
            capabilities: ["supplier"],
            commodities: ["bitumen"],
            verification_status: "verified",
          },
          status: "invited",
          invited_by_operator: false,
          created_at: "2026-09-02T10:00:00Z",
          viewed_at: null,
          responded_at: null,
          declined_at: null,
          expires_at: null,
          decline_reason: "",
        },
      ],
    });

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.matches) }));

    // Pasargad Oil Co should show already invited button
    expect(await screen.findByText(tMatching.actions.alreadyInvited)).toBeInTheDocument();
  });

  it("clears privileged Operator data when switching persona to Buyer", async () => {
    let isOp = true;
    vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            id: isOp ? 99 : 1,
            email: isOp ? "operator@platform.ir" : "buyer@example.com",
            system_roles: isOp ? ["operator"] : [],
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
      if (url === "/api/trade-hub/rfqs/{rfq_id}/") {
        return { response: { ok: true, status: 200 }, data: mockPublishedRfq } as never;
      }
      if (url === "/api/commodity-schemas/{id}/") {
        return { response: { ok: true, status: 200 }, data: mockBitumenSchemaV1 } as never;
      }
      if (url === "/api/matching/rfqs/{rfq_id}/runs/") {
        return {
          response: { ok: true, status: 200 },
          data: isOp ? [mockOperatorRun] : [mockFreshRun],
        } as never;
      }
      if (url === "/api/matching/runs/{run_id}/candidates/") {
        return {
          response: { ok: true, status: 200 },
          data: isOp
            ? [mockOpportunityCandidate]
            : [mockDirectSupplyCandidate],
        } as never;
      }
      return { response: { ok: true, status: 200 }, data: [] } as never;
    });

    const { unmount } = render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.matches) }));

    // Privileged Opportunity candidate is displayed for Operator
    expect(await screen.findByText("Global Petroleum Lead")).toBeInTheDocument();

    // Now switch persona to Buyer (privilege loss)
    isOp = false;
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });

    // Opportunity lead MUST disappear immediately
    await waitFor(() => {
      expect(screen.queryByText("Global Petroleum Lead")).not.toBeInTheDocument();
    });

    unmount();
  });

  it("prevents in-flight delayed Operator response from repopulating UI after persona switch", async () => {
    let isOp = true;
    let resolveDelayedCandidates: ((val: unknown) => void) | null = null;

    vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            id: isOp ? 99 : 1,
            email: isOp ? "operator@platform.ir" : "buyer@example.com",
            system_roles: isOp ? ["operator"] : [],
            organizations: [{ organization: mockBuyerOrg, role: "owner", capabilities: ["buyer"] }],
          },
        } as never;
      }
      if (url === "/api/trade-hub/rfqs/{rfq_id}/") {
        return { response: { ok: true, status: 200 }, data: mockPublishedRfq } as never;
      }
      if (url === "/api/commodity-schemas/{id}/") {
        return { response: { ok: true, status: 200 }, data: mockBitumenSchemaV1 } as never;
      }
      if (url === "/api/matching/rfqs/{rfq_id}/runs/") {
        return {
          response: { ok: true, status: 200 },
          data: [mockOperatorRun],
        } as never;
      }
      if (url === "/api/matching/runs/{run_id}/candidates/") {
        // Return a delayed promise simulating in-flight network latency
        return new Promise((resolve) => {
          resolveDelayedCandidates = resolve;
        }) as never;
      }
      return { response: { ok: true, status: 200 }, data: [] } as never;
    });

    const { unmount } = render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.matches) }));

    // Operator run is selected, candidates are loading in background
    await waitFor(() => {
      expect(resolveDelayedCandidates).not.toBeNull();
    });

    // Switch persona to Buyer BEFORE the delayed Operator response finishes
    isOp = false;
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });

    // Now complete the delayed Operator candidate response
    await act(async () => {
      if (resolveDelayedCandidates) {
        resolveDelayedCandidates({
          response: { ok: true, status: 200 },
          data: [mockOpportunityCandidate],
        });
      }
    });

    // The delayed Operator Opportunity candidate must NOT be rendered
    expect(screen.queryByText("Global Petroleum Lead")).not.toBeInTheDocument();

    unmount();
  });

  it("handles empty runs state with prompt and CTA to generate matches", async () => {
    setupMocks({ runs: [] });

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-test-123" />
      </Wrapper>
    );

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.matches) }));

    // Empty state message and CTA
    expect(await screen.findByText(tMatching.states.noRuns)).toBeInTheDocument();
    expect(screen.getByText(tMatching.states.noRunsPrompt)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: new RegExp(tMatching.actions.generate) })).toBeInTheDocument();
  });

  it("handles unmatchable Draft RFQ notice", async () => {
    setupMocks({ rfqData: mockDraftRfq });

    render(
      <Wrapper>
        <RFQWorkspaceClient locale="fa" rfqId="rfq-draft-456" />
      </Wrapper>
    );

    fireEvent.click(await screen.findByRole("button", { name: new RegExp(tWorkspace.tabs.matches) }));

    // Warning about draft RFQ
    expect(await screen.findByText(tMatching.states.rfqNotPublished)).toBeInTheDocument();
  });
});
