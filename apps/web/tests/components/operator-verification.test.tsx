import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import VerificationQueuePage from "../../src/app/[locale]/operator/verification/page";
import VerificationCaseDetailPage from "../../src/app/[locale]/operator/verification/[id]/page";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
    vi.mocked(client.GET).mockResolvedValue({
      data: {
        results: [
          {
            id: "v-1",
            organization_id: "org-1",
            organization_name: "Test Org",
            status: "documents_submitted",
            updated_at: "2024-01-01T00:00:00Z",
          },
        ],
      },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <VerificationQueuePage />
      </QueryClientProvider>
    );

    expect(screen.getByText("Loading queue...")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Test Org")).toBeInTheDocument();
      expect(screen.getByText("documents submitted")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /Review/i })).toHaveAttribute(
        "href",
        "/fa/operator/verification/org-1"
      );
    });
  });

  it("handles case detail rendering and Start Review action", async () => {
    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url.includes("/verification/")) {
        return {
          data: {
            id: "v-1",
            status: "documents_submitted",
            version: 1,
            decisions: [],
            notes: [],
          },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      return { data: { results: [] } } as any; // documents
    });

// eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(client.POST).mockResolvedValue({ data: {} } as any);

    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <VerificationCaseDetailPage />
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("documents submitted")).toBeInTheDocument();
    });

    const startReviewBtn = await screen.findByRole("button", { name: /Start Review/i });
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
      if (url.includes("/verification/")) {
        return {
          data: {
            id: "v-1",
            status: "under_review",
            version: 2,
            decisions: [],
            notes: [],
          },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      return { data: { results: [] } } as any; // documents
    });

    // Mock 409 conflict
    vi.mocked(client.POST).mockResolvedValue({
      error: { detail: "Stale object error: another transaction modified this verification" },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <VerificationCaseDetailPage />
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("under review")).toBeInTheDocument();
    });

    const rejectBtn = await screen.findByRole("button", { name: /Reject/i });
    expect(rejectBtn).toBeDisabled();

    const input = screen.getByPlaceholderText("Rejection Reason");
    fireEvent.change(input, { target: { value: "Docs fake" } });

    expect(rejectBtn).not.toBeDisabled();
    fireEvent.click(rejectBtn);

    await waitFor(() => {
      expect(screen.getByText(/Stale object error/)).toBeInTheDocument();
      // Should have triggered a refetch on error to handle stale state
      expect(client.GET).toHaveBeenCalledTimes(4); // initial 2 + refetch 2
    });
  });

  it("handles auth failure by properly rejecting rendering", async () => {
    // If the operator has an invalid session, GET will fail.
    vi.mocked(client.GET).mockResolvedValue({
      error: { detail: "Authentication failed" },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(
      <QueryClientProvider client={createTestQueryClient()}>
        <VerificationQueuePage />
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/Error loading verification queue/i)).toBeInTheDocument();
      // No queue items should render
      expect(screen.queryByText("Review")).not.toBeInTheDocument();
    });
  });
});
