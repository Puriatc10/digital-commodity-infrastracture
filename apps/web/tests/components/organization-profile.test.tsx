import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { OrganizationProfileClient } from "@/app/[locale]/organizations/[id]/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";

// Mock Next.js navigation
vi.mock("next/navigation", () => ({
  notFound: vi.fn(),
}));

// Mock API client
vi.mock("@/lib/api/client", () => ({
  apiClient: {
    GET: vi.fn(),
  },
}));

describe("OrganizationProfileClient", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    });
    vi.clearAllMocks();
  });

  function renderComponent() {
    return render(
      <QueryClientProvider client={queryClient}>
        <OrganizationProfileClient id="test-org-123" />
      </QueryClientProvider>
    );
  }

  it("renders loading state initially", () => {
    // Setup pending promise to keep it loading
    (apiClient.GET as any).mockReturnValue(new Promise(() => {}));
    const { container } = renderComponent();
    expect(container.querySelector(".animate-spin")).toBeInTheDocument();
  });

  it("renders error/not-found state on API failure", async () => {
    (apiClient.GET as any).mockResolvedValue({
      error: { detail: "Not found" },
      data: null,
    });
    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("شرکت مورد نظر یافت نشد یا دسترسی به آن امکان‌پذیر نیست.")).toBeInTheDocument();
    });
  });

  it("renders organization data on successful fetch", async () => {
    (apiClient.GET as any).mockResolvedValue({
      data: {
        id: "test-org-123",
        name: "Test Organization",
        registration_identifier: "123456789",
        website: "https://test.com",
        country: "IR",
        is_active: true,
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
        capabilities: ["buyer", "supplier"],
        commodities: ["bitumen", "base-oil"],
        verification_status: "basic_verified"
      },
      error: null,
    });

    renderComponent();

    await waitFor(() => {
      // Company Info
      expect(screen.getByText("Test Organization")).toBeInTheDocument();
      expect(screen.getByText("123456789")).toBeInTheDocument();
      expect(screen.getByText("https://test.com")).toBeInTheDocument();

      // Geography
      expect(screen.getByText("IR")).toBeInTheDocument();

      // Capabilities
      expect(screen.getByText("خریدار")).toBeInTheDocument();
      expect(screen.getByText("تامین‌کننده")).toBeInTheDocument();

      // Commodities
      expect(screen.getByText("bitumen")).toBeInTheDocument();
      expect(screen.getByText("base-oil")).toBeInTheDocument();

      // Verification
      expect(screen.getByText("تاییدیه پایه")).toBeInTheDocument();

      // Activity Summary empty state
      expect(screen.getByText("داده‌های فعالیت در حال حاضر در دسترس نیست.")).toBeInTheDocument();
    });
  });

  it("renders safe defaults when optional fields are empty", async () => {
    (apiClient.GET as any).mockResolvedValue({
      data: {
        id: "test-org-123",
        name: "Minimal Org",
        country: "",
        is_active: true,
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
        capabilities: [],
        commodities: [],
        verification_status: "unverified"
      },
      error: null,
    });

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Minimal Org")).toBeInTheDocument();
      expect(screen.getByText("تایید نشده")).toBeInTheDocument();
      // Hyphens are used for empty optional text values in this UI
      const hyphens = screen.getAllByText("-");
      expect(hyphens.length).toBeGreaterThan(0);
    });
  });
});
