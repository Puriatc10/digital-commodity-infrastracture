import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { ProfileClient } from "@/app/[locale]/directory/[id]/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";

// Mock openapi-fetch
vi.mock("@/lib/api/client", () => ({
  apiClient: {
    GET: vi.fn(),
  },
}));

describe("ProfileClient Component", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    vi.clearAllMocks();
  });

  const renderComponent = (id = "test-id") =>
    render(
      <QueryClientProvider client={queryClient}>
        <ProfileClient id={id} />
      </QueryClientProvider>
    );

  it("renders loading state initially", () => {
    vi.mocked(apiClient.GET).mockImplementation(() => new Promise(() => {}));

    renderComponent();
    expect(document.querySelector('.animate-spin')).toBeInTheDocument();
  });

  it("renders profile when data is fetched successfully", async () => {
    const mockProfile = {
      id: "test-id",
      name: "Test Org 1",
      country: "IR",
      website: "https://example.com",
      capabilities: ["buyer", "supplier"],
      commodities: ["bitumen"],
      verification_status: "verified",
      activity_summary: {},
    };

    vi.mocked(apiClient.GET).mockResolvedValue({
      data: mockProfile,
      response: { ok: true, status: 200 } as Response,
    } as unknown as Promise<unknown>);

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Test Org 1")).toBeInTheDocument();
    });

    expect(screen.getByText("IR")).toBeInTheDocument();
    expect(screen.getByText("https://example.com")).toBeInTheDocument();
    expect(screen.getByText("تایید شده")).toBeInTheDocument();
    expect(screen.getByText("خریدار")).toBeInTheDocument();
    expect(screen.getByText("تامین‌کننده")).toBeInTheDocument();
    expect(screen.getByText("bitumen")).toBeInTheDocument();
    expect(screen.getByText("اطلاعات فعالیت در حال حاضر در دسترس نیست.")).toBeInTheDocument();
  });

  it("renders missing states for null fields correctly", async () => {
    const mockProfile = {
      id: "test-id",
      name: "Test Org 1",
      country: "",
      website: "",
      capabilities: [],
      commodities: [],
      verification_status: "unverified",
      activity_summary: {},
    };

    vi.mocked(apiClient.GET).mockResolvedValue({
      data: mockProfile,
      response: { ok: true, status: 200 } as Response,
    } as unknown as Promise<unknown>);

    const { container } = renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Test Org 1")).toBeInTheDocument();
    });

    // Check directly within the text nodes
    expect(container.innerHTML).toContain("-");

    const unverifiedEl = await screen.findAllByText((content) => {
        return content.includes("تایید نشده");
    });
    expect(unverifiedEl.length).toBeGreaterThanOrEqual(1);
  });

  it("renders error state on API failure", async () => {
    vi.mocked(apiClient.GET).mockRejectedValue(new Error("API Failed"));

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("شرکت یافت نشد یا دسترسی مجاز نیست.")).toBeInTheDocument();
    });
  });

  it("renders error state when profile is not found", async () => {
    vi.mocked(apiClient.GET).mockResolvedValue({
      error: { detail: "Not found" },
      response: { ok: false, status: 404 } as Response,
    } as unknown as Promise<unknown>);

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("شرکت یافت نشد یا دسترسی مجاز نیست.")).toBeInTheDocument();
    });
  });
});
