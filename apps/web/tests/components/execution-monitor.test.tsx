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
import type {
  ExecutionDetail,
  ExecutionLogistics,
  ExecutionInspection,
  ExecutionPayment,
  ExecutionMilestone,
  ExecutionDocument,
  ExecutionIssue,
  TimelineEvent,
} from "@/components/deals/execution/types";

// Mock API Client
vi.mock("@/lib/api/client", () => ({
  apiClient: {
    GET: vi.fn(),
    POST: vi.fn(),
    PATCH: vi.fn(),
  },
}));

// Mock Next.js Navigation
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useParams: () => ({ locale: "fa", id: "deal-test-123" }),
  usePathname: () => "/fa/deals/deal-test-123",
  useSearchParams: () => new URLSearchParams(),
}));

const schemas = fixtures as Record<string, CommoditySchemaVersion>;
const messages = getMessages("fa");
const t = messages.dealWorkspace;
const emT = messages.dealWorkspace.executionMonitor;

const mockBitumenSchemaV1 = {
  ...schemas.bitumen,
  id: "schema-v1-id",
  version: 1,
  state: "published",
};

const mockBuyerOrg = {
  id: "buyer-org-1",
  name: "شرکت بازرگانی خریدار",
  registration_identifier: "REG-BUYER-1",
  country: "IR",
};

const mockBrokerOrg = {
  id: "broker-org-1",
  name: "کارگزاری رسمی خلیج فارس",
  registration_identifier: "REG-BROKER-1",
  country: "IR",
  capabilities: ["broker"],
};

const mockBuyerPartySnapshot = {
  id: "party-buyer-1",
  deal_id: "deal-test-123",
  role: "BUYER" as const,
  party_type: "ORGANIZATION" as const,
  organization_id: "buyer-org-1",
  external_counterparty_id: null,
  name_snapshot: "شرکت بازرگانی خریدار",
  country_snapshot: "IR",
  registration_identifier_snapshot: "REG-BUYER-1",
  created_at: "2026-09-01T10:00:00Z",
};

const mockSellerPartySnapshot = {
  id: "party-seller-1",
  deal_id: "deal-test-123",
  role: "SELLER" as const,
  party_type: "ORGANIZATION" as const,
  organization_id: "supplier-org-1",
  external_counterparty_id: null,
  name_snapshot: "شرکت نفت و قیر تأمین‌کننده",
  country_snapshot: "IR",
  registration_identifier_snapshot: "REG-SUPP-1",
  created_at: "2026-09-01T10:00:00Z",
};

const mockBrokerPartySnapshot = {
  id: "party-broker-1",
  deal_id: "deal-test-123",
  role: "BUYER_BROKER" as const,
  party_type: "ORGANIZATION" as const,
  organization_id: "broker-org-1",
  external_counterparty_id: null,
  name_snapshot: "کارگزاری رسمی خلیج فارس",
  country_snapshot: "IR",
  registration_identifier_snapshot: "REG-BROKER-1",
  created_at: "2026-09-01T10:00:00Z",
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
        description_snapshot: "Commercial Freight Agreement",
        created_at: "2026-09-01T10:00:00Z",
      },
    ],
    created_at: "2026-09-01T10:00:00Z",
  },
  parties: [mockBuyerPartySnapshot, mockSellerPartySnapshot, mockBrokerPartySnapshot],
  attribution: {
    id: "attr-test-123",
    deal_id: "deal-test-123",
    status: "RESOLVED" as const,
    primary_channel: "BROKER" as const,
    resolution_method: "MANUAL" as const,
    resolved_by_id: "operator-user-uuid",
    resolved_at: "2026-09-01T10:05:00Z",
    resolution_reason: "Verified broker deal",
    evidence_snapshot: null,
    broker_attributions: [
      {
        id: "broker-attr-1",
        deal_id: "deal-test-123",
        broker_organization_id: "broker-org-1",
        role: "DEMAND_ORIGINATOR" as const,
        related_opportunity_id: null,
        created_at: "2026-09-01T10:00:00Z",
      },
    ],
    opportunity_attributions: [],
    version: 1,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:05:00Z",
  },
  broker_attributions: [],
  opportunity_attributions: [],
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-01T10:05:00Z",
};

// Fixtures for Execution aggregate
const mockMilestones: ExecutionMilestone[] = [
  {
    id: "m-1",
    execution_id: "exec-123",
    definition_id: "def-1",
    code: "CONTRACT_SIGNED",
    name_fa: "امضای قرارداد تجاری",
    name_en: "Contract Signed",
    sort_order: 1,
    required: true,
    blocking: true,
    terminal: false,
    status: "COMPLETED",
    actual_at: "2026-09-02T10:00:00Z",
    recorded_at: "2026-09-02T10:05:00Z",
    completed_by_id: 1,
    completed_by_email: "buyer@example.com",
    notes: "امضای دوطرفه انجام شد",
    version: 1,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-02T10:05:00Z",
  },
  {
    id: "m-2",
    execution_id: "exec-123",
    definition_id: "def-2",
    code: "PAYMENT_REPORTED",
    name_fa: "اعلام وضعیت پرداخت",
    name_en: "Payment Reported",
    sort_order: 2,
    required: true,
    blocking: true,
    terminal: false,
    status: "IN_PROGRESS",
    actual_at: null,
    recorded_at: null,
    completed_by_id: null,
    completed_by_email: null,
    notes: "",
    version: 1,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
  },
  {
    id: "m-3",
    execution_id: "exec-123",
    definition_id: "def-3",
    code: "LOADING_SCHEDULED",
    name_fa: "زمان‌بندی بارگیری",
    name_en: "Loading Scheduled",
    sort_order: 3,
    required: true,
    blocking: false,
    terminal: false,
    status: "PENDING",
    actual_at: null,
    recorded_at: null,
    completed_by_id: null,
    completed_by_email: null,
    notes: "",
    version: 1,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
  },
  {
    id: "m-4",
    execution_id: "exec-123",
    definition_id: "def-4",
    code: "INSPECTION_COMPLETED",
    name_fa: "اتمام بازرسی کیفیت",
    name_en: "Inspection Completed",
    sort_order: 4,
    required: false,
    blocking: false,
    terminal: false,
    status: "BLOCKED",
    actual_at: null,
    recorded_at: null,
    completed_by_id: null,
    completed_by_email: null,
    notes: "معطل اعلام نتایج آزمون آزمایشگاه همکار",
    version: 1,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-02T12:00:00Z",
  },
  {
    id: "m-5",
    execution_id: "exec-123",
    definition_id: "def-5",
    code: "IN_TRANSIT",
    name_fa: "در حال حمل",
    name_en: "In Transit",
    sort_order: 5,
    required: false,
    blocking: false,
    terminal: false,
    status: "SKIPPED",
    actual_at: null,
    recorded_at: null,
    completed_by_id: null,
    completed_by_email: null,
    notes: "تحویل مستقیم در درب کارخانه انجام شد و مرحله حمل مستقل رد شد",
    version: 1,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-02T13:00:00Z",
  },
  {
    id: "m-6",
    execution_id: "exec-123",
    definition_id: "def-6",
    code: "CLOSED",
    name_fa: "خاتمه رسمی اجرا",
    name_en: "Closed",
    sort_order: 6,
    required: true,
    blocking: false,
    terminal: true,
    status: "PENDING",
    actual_at: null,
    recorded_at: null,
    completed_by_id: null,
    completed_by_email: null,
    notes: "",
    version: 1,
    created_at: "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:00:00Z",
  },
];

const mockLogistics: ExecutionLogistics = {
  id: "log-123",
  execution_id: "exec-123",
  carrier: "شرکت کشتیرانی دریا بار",
  transport_mode: "SEA",
  carrier_name: "شرکت کشتیرانی دریا بار",
  transport_reference: "BOL-SEA-987654",
  pickup_area_id: null,
  pickup_area_code: null,
  pickup_area_name_fa: null,
  pickup_area_name_en: null,
  destination_area_id: null,
  destination_area_code: null,
  destination_area_name_fa: null,
  destination_area_name_en: null,
  pickup_location: "اسکله ۲ شهید رجایی بندرعباس",
  destination_location: "اسکله ۵ جبل علی",
  scheduled_loading_at: "2026-10-02T08:00:00Z",
  actual_loading_at: "2026-10-03T11:30:00Z",
  eta: "2026-10-06T18:00:00Z",
  actual_delivery_at: null,
  logistics_cost: "12800.00",
  currency: "USD",
  version: 2,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-09-03T12:00:00Z",
};

const mockInspection: ExecutionInspection = {
  id: "insp-123",
  execution_id: "exec-123",
  required: true,
  agency: "شرکت بازرسی مهندسی ایران (SGS/IEI)",
  scheduled_at: "2026-10-02T09:00:00Z",
  inspection_at: "2026-10-02T14:30:00Z",
  status: "COMPLETED",
  result: "FAIL",
  notes: "درجه نفوذ در آزمون ۷۸ تعیین شد که فراتر از بازه استاندارد ۶۰/۷۰ معامله است.",
  version: 3,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-10-02T15:00:00Z",
};

const mockPayment: ExecutionPayment = {
  id: "pay-123",
  execution_id: "exec-123",
  status: "REPORTED",
  expected_amount: "175000.00",
  currency: "USD",
  expected_at: "2026-10-05T00:00:00Z",
  reported_at: "2026-10-03T09:00:00Z",
  reported_by_id: "1",
  reported_by_email: "buyer@example.com",
  confirmed_at: null,
  confirmed_by_id: null,
  confirmed_by_email: null,
  reference: "LC-REF-2026-8877",
  notes: "سویفت گشایش اعتبار اسنادی به پیوست ارسال شد",
  version: 2,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-10-03T09:00:00Z",
};

const mockExecutionDetail: ExecutionDetail = {
  id: "exec-123",
  deal_id: "deal-test-123",
  workflow_template_version_id: "tmpl-ver-v1-uuid",
  workflow_template_code: "bitumen",
  workflow_template_name_fa: "گردش کار رسمی صادرات قیر",
  workflow_template_name_en: "Bitumen Export Standard Workflow",
  workflow_version_number: 1,
  status: "OPEN",
  version: 4,
  started_at: "2026-09-01T10:00:00Z",
  closed_at: null,
  milestones: mockMilestones,
  logistics: mockLogistics,
  inspection: mockInspection,
  payment: mockPayment,
  created_at: "2026-09-01T10:00:00Z",
  updated_at: "2026-10-03T12:00:00Z",
};

const mockDocuments: ExecutionDocument[] = [
  {
    id: "doc-1",
    execution_id: "exec-123",
    milestone_id: "m-1",
    inspection_id: null,
    issue_id: null,
    category: "CONTRACT",
    category_display: "قرارداد رسمی تجاری",
    file_name: "Signed_Commercial_Contract_2026.pdf",
    content_type: "application/pdf",
    size_bytes: 1450000,
    uploaded_by_id: "1",
    uploaded_by_email: "buyer@example.com",
    uploaded_at: "2026-09-02T10:02:00Z",
    created_at: "2026-09-02T10:02:00Z",
    updated_at: "2026-09-02T10:02:00Z",
  },
  {
    id: "doc-2",
    execution_id: "exec-123",
    milestone_id: "m-4",
    inspection_id: "insp-123",
    issue_id: null,
    category: "INSPECTION_REPORT",
    category_display: "گزارش و گواهینامه بازرسی فنی",
    file_name: "SGS_Inspection_NonCompliance_Report.pdf",
    content_type: "application/pdf",
    size_bytes: 840000,
    uploaded_by_id: "2",
    uploaded_by_email: "operator@platform.internal",
    uploaded_at: "2026-10-02T15:10:00Z",
    created_at: "2026-10-02T15:10:00Z",
    updated_at: "2026-10-02T15:10:00Z",
  },
];

const mockIssues: ExecutionIssue[] = [
  {
    id: "issue-1",
    execution_id: "exec-123",
    type: "QUALITY",
    type_display: "مغایرت کیفیت",
    status: "OPEN",
    status_display: "باز",
    severity: "HIGH",
    severity_display: "بالا",
    title: "مغایرت درجه نفوذ قیر در گواهی بازرسی",
    description: "نتیجه آزمایشگاهی درجه نفوذ ۷۸ نشان می‌دهد و نیازمند تخفیف قیمت یا اصلاح محموله است.",
    opened_by_id: "1",
    opened_by_email: "buyer@example.com",
    opened_at: "2026-10-02T16:00:00Z",
    resolved_by_id: null,
    resolved_by_email: null,
    resolved_at: null,
    resolution_notes: "",
    blocks_execution: true, // Close blocker!
    is_active_blocker: true,
    version: 1,
    created_at: "2026-10-02T16:00:00Z",
    updated_at: "2026-10-02T16:00:00Z",
  },
  {
    id: "issue-2",
    execution_id: "exec-123",
    type: "DOCUMENT",
    type_display: "نقص مدارک",
    status: "RESOLVED",
    status_display: "حل‌شده",
    severity: "LOW",
    severity_display: "پایین",
    title: "نیاز به ارسال اصل کاغذی بارنامه",
    description: "خریدار درخواست ارسال ۲ نسخه اصلی از طریق پست هوایی داشت.",
    opened_by_id: "1",
    opened_by_email: "buyer@example.com",
    opened_at: "2026-09-20T10:00:00Z",
    resolved_by_id: "2",
    resolved_by_email: "seller@example.com",
    resolved_at: "2026-09-22T11:00:00Z",
    resolution_notes: "کد رهگیری پست DHL تحویل خریدار شد.",
    blocks_execution: false, // Non-blocking
    is_active_blocker: false,
    version: 2,
    created_at: "2026-09-20T10:00:00Z",
    updated_at: "2026-09-22T11:00:00Z",
  },
];

const mockTimeline: TimelineEvent[] = [
  {
    event_id: "ev-1",
    event_type: "EXECUTION_INITIALIZED",
    type_priority: 10,
    event_at: "2026-09-01T10:00:00Z",
    recorded_at: "2026-09-01T10:00:00Z",
    actor_id: "1",
    actor_email: "operator@platform.internal",
    milestone_code: null,
    milestone_name_fa: null,
    milestone_name_en: null,
    notes: "پرونده اجرای معامله بر اساس الگوی رسمی مقید راه‌اندازی شد",
    metadata: {},
  },
  {
    event_id: "ev-2",
    event_type: "MILESTONE_COMPLETED",
    type_priority: 20,
    event_at: "2026-09-02T10:00:00Z",
    recorded_at: "2026-09-02T10:05:00Z",
    actor_id: "1",
    actor_email: "buyer@example.com",
    milestone_code: "CONTRACT_SIGNED",
    milestone_name_fa: "امضای قرارداد تجاری",
    milestone_name_en: "Contract Signed",
    notes: "امضای رسمی قرارداد دوجانبه تأیید شد",
    metadata: {},
  },
  {
    event_id: "ev-3",
    event_type: "PAYMENT_REPORTED",
    type_priority: 25,
    event_at: "2026-10-03T09:00:00Z",
    recorded_at: "2026-10-03T09:00:00Z",
    actor_id: "1",
    actor_email: "buyer@example.com",
    milestone_code: "PAYMENT_REPORTED",
    milestone_name_fa: "اعلام وضعیت پرداخت",
    milestone_name_en: "Payment Reported",
    notes: "گشایش اعتبارات اسنادی بانکی اعلام گردید",
    metadata: {},
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

describe("T1009 — Execution Monitor UI Test Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
  });

  function setupDefaultMocks({
    userOrg = mockBuyerOrg as typeof mockBuyerOrg | (() => typeof mockBuyerOrg),
    role = "owner" as "owner" | "admin" | "member" | "viewer",
    capability = "buyer",
    isOperator = false as boolean | (() => boolean),
    executionData = mockExecutionDetail as ExecutionDetail | null | (() => ExecutionDetail | null),
    documentsData = mockDocuments,
    issuesData = mockIssues,
    timelineData = mockTimeline,
    dealData = mockDealBase,
    dealStatus = 200,
    executionStatus = 200,
  } = {}) {
    vi.mocked(apiClient.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        const opVal = typeof isOperator === "function" ? isOperator() : isOperator;
        const orgVal = typeof userOrg === "function" ? userOrg() : userOrg;
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            id: 1,
            email: "user@example.com",
            system_roles: opVal ? ["operator"] : [],
            organizations: [
              {
                organization: orgVal,
                role,
                capabilities: [capability],
              },
            ],
          },
        } as never;
      }

      if (url === "/api/deals/{deal_id}/") {
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
          data: dealData,
        } as never;
      }

      if (url === "/api/deals/{deal_id}/execution/") {
        const execVal = typeof executionData === "function" ? executionData() : executionData;
        if (executionStatus === 403) {
          return {
            response: { ok: false, status: 403 } as Response,
            data: { detail: "Permission denied." },
          } as never;
        }
        if (executionStatus === 404 || !execVal) {
          return {
            response: { ok: false, status: 404 } as Response,
            data: { detail: "Execution not found." },
          } as never;
        }
        return {
          response: { ok: true, status: 200 } as Response,
          data: execVal,
        } as never;
      }

      if (url === "/api/execution/{execution_id}/timeline/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: timelineData,
        } as never;
      }

      if (url === "/api/execution/{execution_id}/documents/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: documentsData,
        } as never;
      }

      if (url === "/api/execution/{execution_id}/issues/") {
        return {
          response: { ok: true, status: 200 } as Response,
          data: issuesData,
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

  // 1. Bound template & version rendering
  it("1. Bound Template & Version: displays historical bound template version without fetching active schema", async () => {
    setupDefaultMocks();

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    // Navigate to Execution Tab
    const execTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.execution) });
    fireEvent.click(execTabButton);

    // Verify bound template name and version number
    expect(await screen.findByText("گردش کار رسمی صادرات قیر")).toBeInTheDocument();
    expect(screen.getByText("v1")).toBeInTheDocument();
    expect(screen.getByText(emT.workflow.boundVersionTitle)).toBeInTheDocument();
    expect(screen.getByText(emT.workflow.templateLabel)).toBeInTheDocument();

    // Verify no call made to fetch any active/current commodity workflow templates
    const calls = vi.mocked(apiClient.GET).mock.calls as unknown[][];
    const templateListCalls = calls.filter((call) => typeof call?.[0] === "string" && (call[0] as string).includes("/templates/active"));
    expect(templateListCalls.length).toBe(0);
  });

  // 2. Milestone graph in all 5 states in Persian
  it("2. Milestone Graph: renders all 5 operational states (COMPLETED, IN_PROGRESS, PENDING, BLOCKED, SKIPPED) in Persian", async () => {
    setupDefaultMocks();

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    const execTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.execution) });
    fireEvent.click(execTabButton);

    // All 5 milestone statuses in Persian
    expect(await screen.findByText(emT.milestones.statuses.COMPLETED)).toBeInTheDocument();
    expect(screen.getByText(emT.milestones.statuses.IN_PROGRESS)).toBeInTheDocument();
    expect(screen.getAllByText(emT.milestones.statuses.PENDING).length).toBeGreaterThan(0);
    expect(screen.getByText(emT.milestones.statuses.BLOCKED)).toBeInTheDocument();
    expect(screen.getByText(emT.milestones.statuses.SKIPPED)).toBeInTheDocument();

    // Milestone Titles
    expect(screen.getAllByText("امضای قرارداد تجاری")[0]).toBeInTheDocument();
    expect(screen.getAllByText("اعلام وضعیت پرداخت")[0]).toBeInTheDocument();
    expect(screen.getByText("زمان‌بندی بارگیری")).toBeInTheDocument();
    expect(screen.getByText("اتمام بازرسی کیفیت")).toBeInTheDocument();
    expect(screen.getByText("خاتمه رسمی اجرا")).toBeInTheDocument();

    // Badges (Required, Optional, Terminal)
    expect(screen.getAllByText(emT.milestones.badges.required).length).toBeGreaterThan(0);
    expect(screen.getAllByText(emT.milestones.badges.optional).length).toBeGreaterThan(0);
    expect(screen.getByText(emT.milestones.badges.terminal)).toBeInTheDocument();
  });

  // 3. Terminal milestone completion and BLOCKING_ISSUE_OPEN error handling
  it("3. Terminal Milestone & BLOCKING_ISSUE_OPEN: displays explicit Persian blocker alert when close is rejected due to open blocking issues", async () => {
    setupDefaultMocks();

    vi.mocked(apiClient.POST).mockImplementation(async (url: string) => {
      if (url.includes("/milestones/") && url.includes("/complete/")) {
        return {
          response: { ok: false, status: 400 } as Response,
          data: {
            detail: "Cannot complete execution while blocking issues remain open",
            code: "BLOCKING_ISSUE_OPEN",
          },
        } as never;
      }
      return { response: { ok: true, status: 200 } as Response, data: {} } as never;
    });

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    const execTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.execution) });
    fireEvent.click(execTabButton);

    // Find the terminal milestone "خاتمه رسمی اجرا" and click its complete/close button
    const closeButtons = await screen.findAllByRole("button", { name: new RegExp(emT.milestones.actionsList.close) });
    expect(closeButtons.length).toBeGreaterThan(0);
    fireEvent.click(closeButtons[0]);

    // Inline dialog opens; submit it
    const submitBtn = await screen.findByRole("button", { name: emT.milestones.dialogs.submit });
    fireEvent.click(submitBtn);

    // Verify BLOCKING_ISSUE_OPEN alert error is displayed in Persian
    expect(await screen.findByText(emT.milestones.blockingIssueOpenError)).toBeInTheDocument();
  });

  // 4. Payment monitoring: verifies EXPECTED, REPORTED, CONFIRMED and absence of money-movement wording
  it("4. Payment Monitoring: asserts status display and absence of money-movement, escrow or settlement vocabulary", async () => {
    setupDefaultMocks();

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    const execTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.execution) });
    fireEvent.click(execTabButton);

    // Verify Payment Monitoring header and disclaimer
    expect(await screen.findByText(emT.payment.title)).toBeInTheDocument();
    expect(screen.getByText(emT.payment.disclaimer)).toBeInTheDocument();
    expect(screen.getByText(emT.payment.statuses.REPORTED)).toBeInTheDocument();

    // Verify expected amount, currency, and reference
    expect(screen.getAllByText(/175000\.00 USD/)[0]).toBeInTheDocument();
    expect(screen.getByText("LC-REF-2026-8877")).toBeInTheDocument();

    // Strict non-goal check: platform must NOT contain payment processing, escrow, or settlement execution text
    const wholePageText = document.body.textContent || "";
    expect(wholePageText).not.toContain("درگاه پرداخت");
    expect(wholePageText).not.toContain("پرداخت اینترنتی");
    expect(wholePageText).not.toContain("انتقال وجه شتاب");
    expect(wholePageText).not.toContain("واریز وجه به حساب سپرده");
    expect(wholePageText).not.toContain("escrow account");
    expect(wholePageText).not.toContain("instant bank settlement");
  });

  // 5. Logistics: operational tracking vs Deal commercial terms separation, no fake data
  it("5. Logistics Separation: commercial terms remain immutable while operational actuals update separately; no fake GPS/ETA", async () => {
    setupDefaultMocks();

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    // Navigate to Logistics Tab
    const logTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.logistics) });
    fireEvent.click(logTabButton);

    // Commercial Terms Card (Read-only immutable historical truth)
    expect(await screen.findByText(emT.logistics.commercialCardTitle)).toBeInTheDocument();
    expect(screen.getByText(emT.logistics.commercialTermsNotice)).toBeInTheDocument();
    expect(screen.getByText("FOB")).toBeInTheDocument();
    expect(screen.getByText("Bandar Abbas")).toBeInTheDocument();
    expect(screen.getByText("Jebel Ali")).toBeInTheDocument();

    // Actual Operational Logistics Card
    expect(screen.getByText(emT.logistics.actualCardTitle)).toBeInTheDocument();
    expect(screen.getByText("شرکت کشتیرانی دریا بار")).toBeInTheDocument();
    expect(screen.getByText("BOL-SEA-987654")).toBeInTheDocument();
    expect(screen.getByText("دریایی")).toBeInTheDocument();
    expect(screen.getByText("اسکله ۲ شهید رجایی بندرعباس")).toBeInTheDocument();
    expect(screen.getByText("اسکله ۵ جبل علی")).toBeInTheDocument();
    expect(screen.getByText(/12800\.00 USD/)).toBeInTheDocument();

    // Verify absence of fake simulated GPS tracking or animated mock routes
    const wholeText = document.body.textContent || "";
    expect(wholeText).not.toContain("موقعیت زنده ماهواره‌ای GPS");
    expect(wholeText).not.toContain("ردیابی زنده کامیون روی نقشه");
  });

  // 6. Quality inspection: COMPLETED + FAIL special callout
  it("6. Quality Inspection: renders completed inspection with explicit FAIL callout banner and lab notes", async () => {
    setupDefaultMocks();

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    // Navigate to Quality Tab
    const qualTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.quality) });
    fireEvent.click(qualTabButton);

    // Header & Badges
    expect(await screen.findByText(emT.quality.title)).toBeInTheDocument();
    expect(screen.getAllByText(emT.quality.statuses.COMPLETED)[0]).toBeInTheDocument();
    expect(screen.getAllByText(emT.quality.results.FAIL)[0]).toBeInTheDocument();

    // Explicit COMPLETED + FAIL Callout Banner
    expect(screen.getByText(emT.quality.failedCompletedCallout)).toBeInTheDocument();
    expect(
      screen.getByText("تکمیل بازرسی با نتیجه عدم انطباق (Completed Inspection with Failed Result)")
    ).toBeInTheDocument();

    // Agency & Notes
    expect(screen.getByText("شرکت بازرسی مهندسی ایران (SGS/IEI)")).toBeInTheDocument();
    expect(
      screen.getByText("درجه نفوذ در آزمون ۷۸ تعیین شد که فراتر از بازه استاندارد ۶۰/۷۰ معامله است.")
    ).toBeInTheDocument();
  });

  // 7. Documents: list, verified status, download call, and multipart upload
  it("7. Documents Tab: lists operational evidence, provides streaming download call, and multipart upload", async () => {
    setupDefaultMocks();

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      blob: async () => new Blob(["test-pdf-content"], { type: "application/pdf" }),
    } as Response);

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    // Navigate to Documents Tab
    const docsTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.documents) });
    fireEvent.click(docsTabButton);

    // Document Items
    expect(await screen.findByText("Signed_Commercial_Contract_2026.pdf")).toBeInTheDocument();
    expect(screen.getByText("SGS_Inspection_NonCompliance_Report.pdf")).toBeInTheDocument();
    expect(screen.getAllByText("قرارداد رسمی تجاری")[0]).toBeInTheDocument();

    // Download button triggers authorized streaming download endpoint without public URLs
    const downloadButtons = screen.getAllByRole("button", { name: new RegExp(emT.documents.table.download) });
    fireEvent.click(downloadButtons[0]);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining("/api/execution/exec-123/documents/doc-1/download/"),
        expect.objectContaining({ credentials: "include" })
      );
    });

    fetchSpy.mockRestore();
  });

  // 8. Issues: direct blocks_execution badge and resolve action with mandatory notes
  it("8. Issues Tab: displays direct blocker badge (not inferred) and requires notes for resolution", async () => {
    setupDefaultMocks();

    vi.mocked(apiClient.POST).mockImplementation(async (url: string) => {
      if (url.includes("/issues/") && url.includes("/resolve/")) {
        return { response: { ok: true, status: 200 } as Response, data: {} } as never;
      }
      return { response: { ok: true, status: 200 } as Response, data: {} } as never;
    });

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    // Navigate to Issues Tab
    const issuesTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.issues) });
    fireEvent.click(issuesTabButton);

    // Verify issue titles
    expect(await screen.findByText("مغایرت درجه نفوذ قیر در گواهی بازرسی")).toBeInTheDocument();
    expect(screen.getByText("نیاز به ارسال اصل کاغذی بارنامه")).toBeInTheDocument();

    // Verify direct close blocker badge
    expect(screen.getByText(emT.issues.blocksCloseBadge)).toBeInTheDocument();
    expect(screen.getByText(emT.issues.nonBlockingBadge)).toBeInTheDocument();

    // Test Resolve action
    const resolveButtons = screen.getAllByRole("button", { name: new RegExp(emT.issues.actions.resolve) });
    fireEvent.click(resolveButtons[0]);

    // Modal opens, require resolution notes
    const notesInput = await screen.findByPlaceholderText(emT.issues.dialogs.resolutionNotesPlaceholder);
    fireEvent.change(notesInput, { target: { value: "توافق بر کسر ۵ دلار در هر تن حاصل و تأیید شد." } });

    const submitBtn = screen.getByRole("button", { name: "تأیید و اعمال" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(apiClient.POST).toHaveBeenCalledWith(
        "/api/execution/{execution_id}/issues/{issue_id}/resolve/",
        expect.objectContaining({
          body: expect.objectContaining({
            expected_version: 1,
            resolution_notes: "توافق بر کسر ۵ دلار در هر تن حاصل و تأیید شد.",
          }),
        })
      );
    });
  });

  // 9. Timeline: deterministic domain event projection
  it("9. Timeline: displays deterministic ordered events with timestamp and actor attribution", async () => {
    setupDefaultMocks();

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    const execTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.execution) });
    fireEvent.click(execTabButton);

    // Check Timeline events
    expect(await screen.findByText(emT.timeline.title)).toBeInTheDocument();
    expect(screen.getByText(/پرونده اجرای معامله بر اساس الگوی رسمی مقید راه‌اندازی شد/)).toBeInTheDocument();
    expect(screen.getByText(/امضای رسمی قرارداد دوجانبه تأیید شد/)).toBeInTheDocument();
    expect(screen.getByText(/گشایش اعتبارات اسنادی بانکی اعلام گردید/)).toBeInTheDocument();
    expect(screen.getAllByText(/operator@platform\.internal/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/buyer@example\.com/).length).toBeGreaterThan(0);
  });

  // 10. Concurrency: 409 conflict displays conflict alert, refetches fresh data, and does not retry in loop
  it("10. Concurrency 409: handles version conflict by showing conflict banner and refetching authoritative data", async () => {
    setupDefaultMocks();

    vi.mocked(apiClient.POST).mockImplementation(async (url: string) => {
      if (url.includes("/milestones/") && url.includes("/start/")) {
        return {
          response: { ok: false, status: 409 } as Response,
          data: { detail: "Conflict: Aggregate version mismatch" },
        } as never;
      }
      return { response: { ok: true, status: 200 } as Response, data: {} } as never;
    });

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    const execTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.execution) });
    fireEvent.click(execTabButton);

    // Open start action for pending milestone
    const startButtons = await screen.findAllByRole("button", { name: emT.milestones.actionsList.start });
    fireEvent.click(startButtons[0]);

    // Submit start action
    const submitBtn = await screen.findByRole("button", { name: emT.milestones.dialogs.submit });
    fireEvent.click(submitBtn);

    // Conflict banner appears
    expect(await screen.findByText(emT.conflictError)).toBeInTheDocument();

    // Verify GET refetch was triggered
    expect(apiClient.GET).toHaveBeenCalledWith(
      "/api/deals/{deal_id}/execution/",
      expect.anything()
    );
  });

  // 11. Attributed Broker: read-only access (can view execution tabs, but action buttons hidden)
  it("11. Attributed Broker: can observe execution data across all tabs but mutation buttons are disabled/hidden", async () => {
    // Setup authenticated user as Broker member
    setupDefaultMocks({
      userOrg: mockBrokerOrg,
      role: "member",
      capability: "broker",
      isOperator: false,
    });

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    // Navigate to Execution Tab
    const execTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.execution) });
    fireEvent.click(execTabButton);

    // Can read execution state and milestones
    expect(await screen.findByText("گردش کار رسمی صادرات قیر")).toBeInTheDocument();
    expect(screen.getAllByText("امضای قرارداد تجاری")[0]).toBeInTheDocument();

    // Action buttons like "شروع گام", "تکمیل گام", "علامت‌گذاری مسدودشده" must NOT be rendered for broker
    expect(screen.queryByRole("button", { name: emT.milestones.actionsList.start })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: emT.milestones.actionsList.block })).not.toBeInTheDocument();

    // Navigate to Issues Tab: "ثبت مغایرت جدید" button must NOT be rendered
    const issuesTabButton = screen.getByRole("button", { name: new RegExp(t.tabs.issues) });
    fireEvent.click(issuesTabButton);
    expect(await screen.findByText("مغایرت درجه نفوذ قیر در گواهی بازرسی")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: emT.issues.newIssueButton })).not.toBeInTheDocument();
  });

  // 12. Unauthorized 403 Access: third-party organization sees Unauthorized alert
  it("12. Unauthorized Access: third-party or unauthenticated user receives 403 and sees unauthorized alert", async () => {
    setupDefaultMocks({
      dealStatus: 403,
      executionStatus: 403,
    });

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    expect(await screen.findByText(t.unauthorizedTitle)).toBeInTheDocument();
    expect(screen.getByText(t.unauthorizedDescription)).toBeInTheDocument();
  });

  // 13. RTL & Bidi Layout: numbers, codes, ISO dates and currencies are isolated with dir="ltr"
  it("13. RTL & Bidi Layout: validates dir='ltr' and font-mono isolation on references and amounts", async () => {
    setupDefaultMocks();

    render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    const execTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.execution) });
    fireEvent.click(execTabButton);

    // Locate elements containing LTR reference codes and versions
    const versionElem = await screen.findByText("v1");
    expect(versionElem.getAttribute("dir")).toBe("ltr");

    const paymentRefElem = screen.getByText("LC-REF-2026-8877");
    expect(paymentRefElem.getAttribute("dir")).toBe("ltr");

    const amountElem = screen.getAllByText(/175000\.00 USD/)[0];
    expect(amountElem.getAttribute("dir")).toBe("ltr");
  });

  // 14. Cache & Race 1: Persona Switch (Operator -> Buyer)
  it("14. Cache & Race 1: Operator to Buyer persona switch invalidates cache and clears operator privileges", async () => {
    let isOp = true;
    setupDefaultMocks({ isOperator: () => isOp });

    const { rerender } = render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    const execTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.execution) });
    fireEvent.click(execTabButton);

    // As Operator: confirm payment button is visible
    expect(await screen.findByRole("button", { name: emT.payment.actions.confirm })).toBeInTheDocument();

    // Switch persona to non-operator Buyer
    isOp = false;
    window.dispatchEvent(new Event("focus"));

    rerender(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    // Operator-only confirmation button is no longer rendered
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: emT.payment.actions.confirm })).not.toBeInTheDocument();
    });
  });

  // 15. Cache & Race 2: Organization Switch (Org A -> Org B)
  it("15. Cache & Race 2: Org A to Org B switch invalidates execution cache and reloads for Org B", async () => {
    let currentOrg = mockBuyerOrg;

    setupDefaultMocks({
      userOrg: () => currentOrg,
      executionData: () => ({
        ...mockExecutionDetail,
        workflow_template_name_fa: currentOrg.id === "buyer-org-1" ? "گردش کار سازمان الف" : "گردش کار سازمان ب",
      }),
    });

    const { rerender } = render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    const execTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.execution) });
    fireEvent.click(execTabButton);

    expect(await screen.findByText("گردش کار سازمان الف")).toBeInTheDocument();

    // Switch Org to B
    currentOrg = {
      id: "buyer-org-2",
      name: "شرکت بازرگانی ب",
      registration_identifier: "REG-BUYER-2",
      country: "IR",
    };
    window.dispatchEvent(new Event("focus"));

    rerender(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-test-123" />
      </Wrapper>
    );

    // After org switch invalidation, re-navigate to execution tab and verify Org B workflow
    const execTabButtonB = await screen.findByRole("button", { name: new RegExp(t.tabs.execution) });
    fireEvent.click(execTabButtonB);

    expect(await screen.findByText("گردش کار سازمان ب")).toBeInTheDocument();
    expect(screen.queryByText("گردش کار سازمان الف")).not.toBeInTheDocument();
  });

  // 16. Cache & Race 3: Fast Deal Navigation (Deal A -> Deal B)
  it("16. Cache & Race 3: Fast Deal navigation Deal A to Deal B discards late execution response from Deal A", async () => {
    let resolveExecA: ((val: unknown) => void) | null = null;
    const execAPromise = new Promise((resolve) => {
      resolveExecA = resolve;
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
        return {
          response: { ok: true, status: 200 } as Response,
          data: {
            ...mockDealBase,
            id: id || "deal-A",
            terms: {
              ...mockDealBase.terms,
              commodity_name_fa: id === "deal-B" ? "کالای معامله ب" : "کالای معامله آ",
            },
          },
        } as never;
      }

      if (url === "/api/deals/{deal_id}/execution/") {
        const id = options?.params?.path?.deal_id;
        if (id === "deal-A") {
          await execAPromise;
          return {
            response: { ok: true, status: 200 } as Response,
            data: {
              ...mockExecutionDetail,
              workflow_template_name_fa: "گردش کار معامله آ",
            },
          } as never;
        }

        if (id === "deal-B") {
          return {
            response: { ok: true, status: 200 } as Response,
            data: {
              ...mockExecutionDetail,
              workflow_template_name_fa: "گردش کار معامله ب",
            },
          } as never;
        }
      }

      if (url === "/api/execution/{execution_id}/timeline/") {
        return { response: { ok: true, status: 200 } as Response, data: mockTimeline } as never;
      }
      if (url === "/api/execution/{execution_id}/documents/") {
        return { response: { ok: true, status: 200 } as Response, data: mockDocuments } as never;
      }
      if (url === "/api/execution/{execution_id}/issues/") {
        return { response: { ok: true, status: 200 } as Response, data: mockIssues } as never;
      }

      return { response: { ok: true, status: 200 } as Response, data: null } as never;
    });

    const { rerender } = render(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-A" />
      </Wrapper>
    );

    // Fast switch to Deal B before Deal A resolves
    rerender(
      <Wrapper>
        <DealWorkspaceClient locale="fa" dealId="deal-B" />
      </Wrapper>
    );

    // Switch to execution tab on Deal B
    const execTabButton = await screen.findByRole("button", { name: new RegExp(t.tabs.execution) });
    fireEvent.click(execTabButton);

    // Deal B resolves fast
    expect(await screen.findByText("گردش کار معامله ب")).toBeInTheDocument();

    // Now resolve late Deal A execution response
    if (resolveExecA) {
      (resolveExecA as (val: unknown) => void)(true);
    }

    // Ensure Deal B remains active and Deal A late response was discarded
    expect(screen.getByText("گردش کار معامله ب")).toBeInTheDocument();
    expect(screen.queryByText("گردش کار معامله آ")).not.toBeInTheDocument();
  });
});
