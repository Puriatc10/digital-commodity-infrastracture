import React from "react";
import { render, screen, waitFor, act, cleanup } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import VerificationCaseDetailPage from "../../src/app/[locale]/operator/verification/[id]/page";
import { OpportunityDeskClient } from "../../src/app/[locale]/opportunities/client";
import { DealWorkspaceClient } from "../../src/app/[locale]/deals/[id]/deal-workspace-client";
import { RFQWorkspaceClient } from "../../src/app/[locale]/trade-hub/rfqs/[id]/rfq-workspace-client";
import { AuthProvider } from "../../src/lib/auth-context";
import { apiClient as client } from "../../src/lib/api/client";
import { getMessages } from "../../src/i18n/messages";

const messages = getMessages("fa");
const tVerif = messages.verification.caseDetail;
const tDeal = messages.dealWorkspace;
const tRfq = messages.rfqWorkspace;
const tOpp = messages.opportunities;

// Mock API client
vi.mock("../../src/lib/api/client", () => ({
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
  useParams: () => ({ id: "test-target-id", locale: "fa" }),
  usePathname: () => "/fa/operator/verification/test-target-id",
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

interface TestWrapperProps {
  children: React.ReactNode;
  queryClient?: QueryClient;
}

function TestWrapper({ children, queryClient = createTestQueryClient() }: TestWrapperProps) {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

const triggerCrossTabAuthEvent = () => {
  const channel = new BroadcastChannel("auth_channel");
  channel.postMessage("auth_changed");
  channel.close();
};

const mockBuyerUser = {
  id: 101,
  username: "buyer_user",
  email: "buyer@buyer.ir",
  system_roles: [],
  organizations: [
    {
      organization: {
        id: "buyer-org-1",
        name: "شرکت بازرگانی خریدار",
        registration_identifier: "REG-BUYER-1",
        country: "IR",
      },
      role: "owner",
      capabilities: ["buyer"],
    },
  ],
};

const mockSupplierUser = {
  id: 102,
  username: "supplier_user",
  email: "supplier@supplier.ir",
  system_roles: [],
  organizations: [
    {
      organization: {
        id: "supplier-org-1",
        name: "پالایشگاه تأمین‌کننده",
        registration_identifier: "REG-SUPP-1",
        country: "IR",
      },
      role: "owner",
      capabilities: ["supplier"],
    },
  ],
};

const mockOperatorUser = {
  id: 103,
  username: "operator_user",
  email: "operator@platform.internal",
  system_roles: ["operator"],
  organizations: [],
};

describe("Frontend Permission E2E and Session Isolation Suite (T1306)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
  });

  describe("1. Direct Route Security & Role Access Enforcement", () => {
    it("Supplier attempting direct navigation to Operator Verification route renders Unauthorized card", async () => {
      vi.mocked(client.GET).mockImplementation(async (url: string) => {
        if (url === "/api/auth/me") {
          return { response: { ok: true, status: 200 }, data: mockSupplierUser } as never;
        }
        if (url.includes("/verification/")) {
          // Backend would deny or client prevents leak
          return { data: { id: "v-1", notes: [{ id: "n-1", note: "Operator Secret Notes" }] } } as never;
        }
        return { data: { results: [] } } as never;
      });

      render(
        <TestWrapper>
          <VerificationCaseDetailPage />
        </TestWrapper>
      );

      await waitFor(() => {
        expect(screen.getAllByText(tVerif.unauthorizedTitle)[0]).toBeInTheDocument();
      });
      expect(screen.queryByText("Operator Secret Notes")).not.toBeInTheDocument();
    });

    it("Buyer attempting direct navigation to Opportunity Desk renders Unauthorized shield", async () => {
      vi.mocked(client.GET).mockImplementation(async (url: string) => {
        if (url === "/api/auth/me") {
          return { response: { ok: true, status: 200 }, data: mockBuyerUser } as never;
        }
        if (url.includes("/opportunities/")) {
          return { error: { detail: "Forbidden" }, response: { status: 403 } } as never;
        }
        return { data: { results: [] } } as never;
      });

      render(
        <TestWrapper>
          <OpportunityDeskClient locale="fa" />
        </TestWrapper>
      );

      await waitFor(() => {
        expect(screen.getByText(messages.rfqBuilder.unauthorizedTitle)).toBeInTheDocument();
        expect(screen.getByText(tOpp.states.unauthorized)).toBeInTheDocument();
      });
    });
  });

  describe("2. Cross-Organization Direct-ID Horizontal Isolation", () => {
    it("Accessing foreign Deal ID with 403 response renders Unauthorized card, never private terms", async () => {
      vi.mocked(client.GET).mockImplementation(async (url: string) => {
        if (url === "/api/auth/me") {
          return { response: { ok: true, status: 200 }, data: mockBuyerUser } as never;
        }
        if (url.startsWith("/api/deals/")) {
          return {
            response: { ok: false, status: 403 },
            error: { detail: "Actor is not a commercial party to this Deal." },
          } as never;
        }
        return { data: null } as never;
      });

      render(
        <TestWrapper>
          <DealWorkspaceClient locale="fa" dealId="foreign-deal-uuid-999" />
        </TestWrapper>
      );

      await waitFor(() => {
        expect(screen.getByText(tDeal.unauthorizedTitle)).toBeInTheDocument();
        expect(screen.getByText(tDeal.unauthorizedDescription)).toBeInTheDocument();
      });
      // Verify no commercial data or tabs are displayed
      expect(screen.queryByText("شرایط تجاری")).not.toBeInTheDocument();
      expect(screen.queryByText("مراحل اجرا")).not.toBeInTheDocument();
    });

    it("Accessing foreign RFQ draft with 404 response renders RFQ Not Found card", async () => {
      vi.mocked(client.GET).mockImplementation(async (url: string) => {
        if (url === "/api/auth/me") {
          return { response: { ok: true, status: 200 }, data: mockSupplierUser } as never;
        }
        if (url.includes("/trade-hub/rfqs/")) {
          return {
            response: { ok: false, status: 404 },
            error: { detail: "RFQ does not exist or is hidden by visibility rules." },
          } as never;
        }
        return { data: null } as never;
      });

      render(
        <TestWrapper>
          <RFQWorkspaceClient locale="fa" rfqId="foreign-rfq-draft-uuid" />
        </TestWrapper>
      );

      await waitFor(() => {
        expect(screen.getByText(tRfq.rfqNotFoundTitle)).toBeInTheDocument();
        expect(screen.getByRole("button", { name: tRfq.backToHub })).toBeInTheDocument();
      });
    });
  });

  describe("3. Demo Persona Switcher Session Cache Isolation", () => {
    it("Switching from Operator to Supplier immediately purges Operator data and displays Unauthorized", async () => {
      let currentUser = mockOperatorUser;

      vi.mocked(client.GET).mockImplementation(async (url: string) => {
        if (url === "/api/auth/me") {
          return { response: { ok: true, status: 200 }, data: currentUser } as never;
        }
        if (url.includes("/verification/")) {
          return {
            data: {
              id: "v-1",
              status: "under_review",
              version: 1,
              decisions: [],
              notes: [{ id: "n-1", note: "Privileged Operator Verification Report" }],
            },
          } as never;
        }
        return { data: { results: [] } } as never;
      });

      render(
        <TestWrapper>
          <VerificationCaseDetailPage />
        </TestWrapper>
      );

      await waitFor(() => {
        expect(screen.getByText("Privileged Operator Verification Report")).toBeInTheDocument();
      });

      // User triggers persona switch to Supplier in switcher (cross-tab event)
      currentUser = mockSupplierUser as never;
      await act(async () => {
        triggerCrossTabAuthEvent();
      });

      await waitFor(() => {
        expect(screen.getAllByText(tVerif.unauthorizedTitle)[0]).toBeInTheDocument();
        expect(screen.queryByText("Privileged Operator Verification Report")).not.toBeInTheDocument();
      });
    });

    it("In-flight response from prior privileged persona cannot repopulate private data after switch", async () => {
      let resolveDelayedVerification: (val: unknown) => void = () => {};
      const delayedPromise = new Promise((res) => {
        resolveDelayedVerification = res;
      });

      vi.mocked(client.GET).mockImplementation(async (url: string) => {
        if (url === "/api/auth/me") {
          return { response: { ok: true, status: 200 }, data: mockOperatorUser } as never;
        }
        if (url.includes("/verification/")) {
          return delayedPromise as never;
        }
        return { data: { results: [] } } as never;
      });

      render(
        <TestWrapper>
          <VerificationCaseDetailPage />
        </TestWrapper>
      );

      await waitFor(() => {
        expect(screen.getByText(tVerif.loadingSr)).toBeInTheDocument();
      });

      // Switch persona to Buyer (unauthorized)
      vi.mocked(client.GET).mockImplementation(async (url: string) => {
        if (url === "/api/auth/me") {
          return { response: { ok: true, status: 200 }, data: mockBuyerUser } as never;
        }
        return { error: { detail: "Forbidden" }, response: { status: 403 } } as never;
      });

      await act(async () => {
        window.dispatchEvent(new Event("focus"));
      });

      await waitFor(() => {
        expect(screen.getAllByText(tVerif.unauthorizedTitle)[0]).toBeInTheDocument();
      });

      // Now late in-flight request finishes
      await act(async () => {
        resolveDelayedVerification({
          data: {
            id: "v-1",
            notes: [{ id: "n-delayed", note: "Late Leaked Secret Notes" }],
          },
        });
      });

      // Must remain unauthorized and leaked notes must NOT render
      await waitFor(() => {
        expect(screen.getAllByText(tVerif.unauthorizedTitle)[0]).toBeInTheDocument();
        expect(screen.queryByText("Late Leaked Secret Notes")).not.toBeInTheDocument();
      });
    });
  });

  describe("4. Error Semantics vs Empty Dataset Invariant", () => {
    it("403 Forbidden on verification case yields error state, NEVER empty state", async () => {
      vi.mocked(client.GET).mockImplementation(async (url: string) => {
        if (url === "/api/auth/me") {
          return { response: { ok: true, status: 200 }, data: mockOperatorUser } as never;
        }
        if (url.includes("/verification/")) {
          return {
            error: { detail: "Access Forbidden." },
            response: { status: 403 },
          } as never;
        }
        return { data: { results: [] } } as never;
      });

      render(
        <TestWrapper>
          <VerificationCaseDetailPage />
        </TestWrapper>
      );

      await waitFor(() => {
        expect(screen.getByText(tVerif.errorSr)).toBeInTheDocument();
        expect(screen.getByText(tVerif.loadError)).toBeInTheDocument();
      });
      // Should not render an empty state or empty checklist
      expect(screen.queryByText(tVerif.documents.empty)).not.toBeInTheDocument();
    });
  });
});
