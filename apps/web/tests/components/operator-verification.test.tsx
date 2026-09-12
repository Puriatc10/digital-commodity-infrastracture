import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import VerificationQueuePage from "../../src/app/[locale]/operator/verification/page";
import VerificationCaseDetailPage from "../../src/app/[locale]/operator/verification/[id]/page";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AuthProvider } from "../../src/lib/auth-context";

const Wrapper = ({ children }: { children: React.ReactNode }) => {
  const queryClient = createTestQueryClient();
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        {children}
      </AuthProvider>
    </QueryClientProvider>
  );
};

import { apiClient as client } from "../../src/lib/api/client";

vi.mock("../../src/lib/api/client", () => ({
  apiClient: {
    GET: vi.fn(),
    POST: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "test-org-id", locale: "fa" }),
}));

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

describe("Verification Operator UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders the verification queue with pending cases", async () => {
    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 },
          data: { id: 1, system_roles: ["operator"], organizations: [] }
        } as unknown as { data?: unknown, error?: unknown, response: Response };
      }
      return {
      data: [
          {
            id: "v-1",
            organization_id: "org-1",
            organization_name: "Test Org",
            status: "documents_submitted",
            updated_at: "2024-01-01T00:00:00Z",
          },
      ],
    } as unknown as { data?: unknown, error?: unknown, response: Response };
    });

    render(
      (() => { const WrapperInst = Wrapper; return <WrapperInst><VerificationQueuePage /></WrapperInst>; })()
    );



    await waitFor(() => {


      expect(screen.getByRole("link", { name: /Review/i })).toHaveAttribute(
        "href",
        "/fa/operator/verification/org-1"
      );
    });
  });

  it("handles case detail rendering and Start Review action", async () => {
    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 },
          data: { id: 1, system_roles: ["operator"], organizations: [] }
        } as unknown as { data?: unknown, error?: unknown, response: Response };
      }
      if (url.includes("/verification/")) {
        return {
          data: {
            id: "v-1",
            status: "documents_submitted",
            version: 1,
            decisions: [],
            notes: [],
          },
        } as unknown as { data?: unknown, error?: unknown, response: Response };
      }
      return { data: { results: [] } } as unknown as { data?: unknown, error?: unknown, response: Response }; // documents
    });

    vi.mocked(client.POST).mockResolvedValue({ data: { id: "v-1", status: "under_review", version: 1, updated_at: "2024-01-01T00:00:00Z", decisions: [], notes: [] } } as unknown as { data?: unknown, error?: unknown, response: Response });


    render(
      (() => { const WrapperInst = Wrapper; return <WrapperInst><VerificationCaseDetailPage /></WrapperInst>; })()
    );

    await waitFor(() => {

    });

    const startReviewBtn = await screen.findByText("Start Review");
    fireEvent.click(startReviewBtn);

    await waitFor(() => {
      expect(client.POST).toHaveBeenCalledWith(
        "/api/organizations/{org_id}/verification/start_review/",
        expect.objectContaining({
          body: { expected_version: 1 },
        })
      );
    });
  });

  it("requires a reason for rejection and handles 409 stale-state response", async () => {
    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 },
          data: { id: 1, system_roles: ["operator"], organizations: [] }
        } as unknown as { data?: unknown, error?: unknown, response: Response };
      }
      if (url.includes("/verification/")) {
        return {
          data: {
            id: "v-1",
            status: "under_review",
            version: 2,
            decisions: [],
            notes: [],
          },
        } as unknown as { data?: unknown, error?: unknown, response: Response };
      }
      return { data: { results: [] } } as unknown as { data?: unknown, error?: unknown, response: Response }; // documents
    });

    // Mock 409 conflict
    vi.mocked(client.POST).mockResolvedValue({
      error: { detail: "Stale object error: another transaction modified this verification" },
    } as unknown as { data?: unknown, error?: unknown, response: Response });

    render(
      (() => { const WrapperInst = Wrapper; return <WrapperInst><VerificationCaseDetailPage /></WrapperInst>; })()
    );

    await waitFor(() => {

    });

    const rejectBtn = await screen.findByText("Reject");
    expect(rejectBtn).toBeDisabled();

    const input = screen.getByPlaceholderText("دلیل رد");
    fireEvent.change(input, { target: { value: "Docs fake" } });

    expect(rejectBtn).not.toBeDisabled();
    fireEvent.click(rejectBtn);

    await waitFor(() => {
      expect(screen.getByText(/Stale object error/)).toBeInTheDocument();
      // Should have triggered a refetch on error to handle stale state
      expect(client.GET).toHaveBeenCalledTimes(5); // initial 2 + refetch 2
    });
  });

  it("handles auth failure by properly rejecting rendering", async () => {
    // If the operator has an invalid session, GET will fail.
    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 },
          data: { id: 1, system_roles: ["operator"], organizations: [] }
        } as unknown as { data?: unknown, error?: unknown, response: Response };
      }
      return {
      error: { detail: "Authentication failed" },
    } as unknown as { data?: unknown, error?: unknown, response: Response };
    });

    render(
      (() => { const WrapperInst = Wrapper; return <WrapperInst><VerificationQueuePage /></WrapperInst>; })()
    );

    await waitFor(() => {
      expect(screen.getByText(/خطا در بارگذاری صف بررسی/i)).toBeInTheDocument();
      // No queue items should render
      expect(screen.queryByText("Review")).not.toBeInTheDocument();
    });
  });
});
