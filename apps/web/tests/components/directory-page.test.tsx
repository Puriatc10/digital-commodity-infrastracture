import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { DirectoryClient } from "@/app/[locale]/directory/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { apiClient } from "@/lib/api/client";

// Mock Next.js navigation
vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ push: vi.fn() })),
  usePathname: vi.fn(() => "/fa/directory"),
  useSearchParams: vi.fn(() => new URLSearchParams()),
}));

// Mock openapi-fetch
vi.mock("@/lib/api/client", () => ({
  apiClient: {
    GET: vi.fn(),
  },
}));

describe("DirectoryClient Component", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    vi.clearAllMocks();
  });

  const renderComponent = () =>
    render(
      <QueryClientProvider client={queryClient}>
        <DirectoryClient />
      </QueryClientProvider>
    );

  it("renders the table and loading state initially", () => {
    vi.mocked(apiClient.GET).mockImplementation(() => new Promise(() => {}));

    renderComponent();

    expect(screen.getByText("نام شرکت")).toBeInTheDocument();
    expect(screen.getAllByText("کشور")[0]).toBeInTheDocument();
    expect(screen.getByText("نقش‌ها")).toBeInTheDocument();

    expect(screen.getByText("تاییدیه")).toBeInTheDocument();
  });

  it("renders organizations when data is fetched successfully", async () => {
    const mockData = [
      {
        id: "1",
        name: "Test Org 1",
        country: "IR",
        capabilities: ["buyer", "supplier"],
        commodities: ["bitumen"],
        verification_status: "verified",
      },
    ];

    vi.mocked(apiClient.GET).mockResolvedValue({
      data: mockData,
      response: { ok: true, status: 200 } as Response,
    } as unknown as Promise<unknown>);

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("Test Org 1")).toBeInTheDocument();
    });

    expect(screen.getByText("IR")).toBeInTheDocument();
    expect(screen.getAllByText("تایید شده")[0]).toBeInTheDocument();
    expect(screen.getAllByText("خریدار")[0]).toBeInTheDocument();
    expect(screen.getAllByText("تامین‌کننده")[0]).toBeInTheDocument();
  });

  it("renders empty state when no organizations exist", async () => {
    vi.mocked(apiClient.GET).mockResolvedValue({
      data: [],
      response: { ok: true, status: 200 } as Response,
    } as unknown as Promise<unknown>);

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("شرکتی یافت نشد.")).toBeInTheDocument();
    });
  });

  it("renders error state on API failure", async () => {
    vi.mocked(apiClient.GET).mockRejectedValue(new Error("API Failed"));

    renderComponent();

    await waitFor(() => {
      expect(screen.getByText("خطا در دریافت اطلاعات")).toBeInTheDocument();
    });
  });
});
