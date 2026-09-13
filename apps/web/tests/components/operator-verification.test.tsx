import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import { VerificationQueueClient } from "../../src/app/[locale]/operator/verification/client";
import { VerificationCaseDetailClient } from "../../src/app/[locale]/operator/verification/[id]/client";
import { ProfileClient } from "../../src/app/[locale]/directory/[id]/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../../src/lib/auth-context";
import { apiClient as client } from "../../src/lib/api/client";

vi.mock("../../src/lib/api/client", () => ({
  apiClient: {
    GET: vi.fn(),
    POST: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "test-org-id", locale: "fa" }),
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/fa/operator/verification",
  useSearchParams: () => new URLSearchParams(),
}));

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

describe("Verification Operator & Evidence UI (Pass C)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders the verification queue in Persian for authorized operator", async () => {
    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 },
          data: { id: 1, system_roles: ["operator"], organizations: [] },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      }
      return {
        response: { ok: true, status: 200 },
        data: {
          results: [
            {
              id: "v-1",
              organization_id: "org-1",
              organization_name: "Test Org",
              status: "documents_submitted",
              version: 1,
              updated_at: "2024-01-01T00:00:00Z",
            },
          ],
        },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
      } as any;
    });

    render(
      <Wrapper>
        <VerificationQueueClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("Test Org")).toBeInTheDocument();
      expect(screen.getByText("مدارک ارسال شده")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: /بررسی پرونده/i })).toHaveAttribute(
        "href",
        "/fa/operator/verification/org-1"
      );
    });
  });

  it("denies access to verification queue for non-operator users", async () => {
    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 },
          data: { id: 2, system_roles: [], organizations: [] },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      }
      return { response: { ok: true, status: 200 }, data: [] } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
    });

    render(
      <Wrapper>
        <VerificationQueueClient locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("دسترسی غیرمجاز")).toBeInTheDocument();
    });
  });

  it("handles case detail rendering and Start Review action in Persian", async () => {
    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 },
          data: { id: 1, system_roles: ["operator"], organizations: [] },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      }
      if (url.includes("/verification/")) {
        return {
          response: { ok: true, status: 200 },
          data: {
            id: "v-1",
            status: "documents_submitted",
            version: 1,
            updated_at: "2024-01-01T00:00:00Z",
            decisions: [],
            notes: [],
          },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      }
      if (url.includes("/profiles/")) {
        return {
          response: { ok: true, status: 200 },
          data: { id: "test-org-id", name: "Alpha Company", country: "IR" },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      }
      return { response: { ok: true, status: 200 }, data: [] } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
    });

// eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(client.POST).mockResolvedValue({ response: { ok: true, status: 200 }, data: {} } as any);

    render(
      <Wrapper>
        <VerificationCaseDetailClient id="test-org-id" locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("مدارک ارسال شده")).toBeInTheDocument();
      expect(screen.getByText("پرونده احراز هویت: Alpha Company")).toBeInTheDocument();
    });

    const startReviewBtn = await screen.findByRole("button", { name: /شروع بررسی پرونده/i });
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

  it("handles document checklist rendering and authorized download button", async () => {
    const originalFetch = global.fetch;
    const mockBlob = new Blob(["fake-pdf-content"], { type: "application/pdf" });
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: async () => mockBlob,
    });
    window.URL.createObjectURL = vi.fn(() => "blob:http://localhost/test");
    window.URL.revokeObjectURL = vi.fn();

    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 },
          data: { id: 1, system_roles: ["operator"], organizations: [] },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      }
      if (url.includes("/verification/")) {
        return {
          response: { ok: true, status: 200 },
          data: {
            id: "v-1",
            status: "under_review",
            version: 2,
            updated_at: "2024-01-01T00:00:00Z",
            decisions: [],
            notes: [],
          },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      }
      if (url.includes("/documents/")) {
        return {
          response: { ok: true, status: 200 },
          data: [
            {
              id: "doc-uuid-1",
              type: "commercial_registration",
              file_name: "registration.pdf",
              file_size: 204800,
              verification_status: "pending",
              is_current: true,
              created_at: "2024-01-01T00:00:00Z",
            },
          ],
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      }
      return { response: { ok: true, status: 200 }, data: null } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
    });

    render(
      <Wrapper>
        <VerificationCaseDetailClient id="test-org-id" locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("ثبت تجاری / روزنامه رسمی")).toBeInTheDocument();
      expect(screen.getByText("دانلود مدرک")).toBeInTheDocument();
    });

    const downloadBtn = screen.getByText("دانلود مدرک");
    fireEvent.click(downloadBtn);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        "/api/documents/doc-uuid-1/download/",
        expect.objectContaining({ credentials: "include" })
      );
    });

    global.fetch = originalFetch;
  });

  it("handles 409 stale conflict by displaying Persian conflict notice and refetching", async () => {
    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 },
          data: { id: 1, system_roles: ["operator"], organizations: [] },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      }
      if (url.includes("/verification/")) {
        return {
          response: { ok: true, status: 200 },
          data: {
            id: "v-1",
            status: "under_review",
            version: 2,
            updated_at: "2024-01-01T00:00:00Z",
            decisions: [],
            notes: [],
          },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      }
      return { response: { ok: true, status: 200 }, data: [] } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
    });

    vi.mocked(client.POST).mockResolvedValue({
      response: { ok: false, status: 409 },
      error: { detail: "Stale object error: another transaction modified this verification", status: 409 },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any);

    render(
      <Wrapper>
        <VerificationCaseDetailClient id="test-org-id" locale="fa" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("در حال بررسی")).toBeInTheDocument();
    });

    const rejectBtn = await screen.findByRole("button", { name: /رد پرونده/i });
    expect(rejectBtn).toBeDisabled();

    const input = screen.getByPlaceholderText("دلیل رد پرونده را بنویسید...");
    fireEvent.change(input, { target: { value: "مدارک ناقص است" } });

    expect(rejectBtn).not.toBeDisabled();
    fireEvent.click(rejectBtn);

    await waitFor(() => {
      expect(
        screen.getByText(/اطلاعات پرونده همگام نیست \(تغییر همزمان رخ داده است\)/)
      ).toBeInTheDocument();
    });
  });

  it("renders customer evidence upload form for Owner/Manager without leaking internal notes", async () => {
    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return {
          response: { ok: true, status: 200 },
          data: {
            id: 10,
            system_roles: [],
            organizations: [
              {
                organization: { id: "test-org-id", name: "My Own Org" },
                role: "owner",
                is_active: true,
              },
            ],
          },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      }
      if (url.includes("/profiles/")) {
        return {
          response: { ok: true, status: 200 },
          data: {
            id: "test-org-id",
            name: "My Own Org",
            country: "IR",
            verification_status: "unverified",
            capabilities: ["buyer"],
            commodities: ["bitumen"],
          },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      }
      if (url.includes("/documents/")) {
        return {
          response: { ok: true, status: 200 },
          data: [],
// eslint-disable-next-line @typescript-eslint/no-explicit-any
        } as any;
      }
      return { response: { ok: true, status: 200 }, data: null } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
    });

    render(
      <Wrapper>
        <ProfileClient id="test-org-id" />
      </Wrapper>
    );

    await waitFor(() => {
      expect(screen.getByText("مدارک و مستندات هویتی سازمان")).toBeInTheDocument();
      expect(screen.getByText("ارسال مدارک جهت بررسی و احراز هویت")).toBeInTheDocument();
      expect(screen.getByText("بارگذاری یا جایگزینی مدرک:")).toBeInTheDocument();
      // Internal operator notes must NEVER be visible to customer
      expect(screen.queryByText("یادداشت‌های داخلی اپراتور")).not.toBeInTheDocument();
    });
  });
});
