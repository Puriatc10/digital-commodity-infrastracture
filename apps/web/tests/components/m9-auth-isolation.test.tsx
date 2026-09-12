import { render, screen, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import VerificationCaseDetailPage from "../../src/app/[locale]/operator/verification/[id]/page";
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
}));

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

const renderWithProviders = () => {
  const queryClient = createTestQueryClient();
  const utils = render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <VerificationCaseDetailPage />
        </AuthProvider>
      </QueryClientProvider>
  );
  return { queryClient, ...utils };
};

const triggerCrossTabEvent = () => {
  const channel = new BroadcastChannel("auth_channel");
  channel.postMessage("auth_changed");
  channel.close();
};

describe("M9 Session Cache Isolation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
  });

  it("same-tab privilege loss clears private Operator data and shows Unauthorized", async () => {
    // 1. Initial GET calls to auth/me and verification returns Operator state
    let authCallCount = 0;
    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        authCallCount++;
        if (authCallCount === 1) {
          return { response: { ok: true, status: 200 }, data: { id: 1, system_roles: ["operator"], organizations: [] } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
        } else {
          return { response: { ok: true, status: 200 }, data: { id: 1, system_roles: [], organizations: [] } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
        }
      }
      if (url.includes("/verification/")) {
        return { data: { id: "v-1", status: "under_review", version: 1, decisions: [], notes: [{ id: "n-1", note: "Secret Operator Note" }] } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
      }
      return { data: { results: [] } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
    });

    const { unmount } = renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText("Secret Operator Note")).toBeInTheDocument();
    });

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });

    await waitFor(() => {
      expect(screen.getByText("Unauthorized")).toBeInTheDocument();
      expect(screen.queryByText("Secret Operator Note")).not.toBeInTheDocument();
    });

    unmount();
  });

  it("cross-tab privilege loss clears cache and shows Unauthorized", async () => {
    let isOperator = true;
    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return { response: { ok: true, status: 200 }, data: { id: 1, system_roles: isOperator ? ["operator"] : [], organizations: [] } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
      }
      if (url.includes("/verification/")) {
        return { data: { id: "v-1", status: "under_review", version: 1, decisions: [], notes: [{ id: "n-1", note: "Secret Operator Note" }] } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
      }
      return { data: { results: [] } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
    });

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText("Secret Operator Note")).toBeInTheDocument();
    });

    isOperator = false;
    await act(async () => {
      triggerCrossTabEvent();
    });

    await waitFor(() => {
      expect(screen.getByText("Unauthorized")).toBeInTheDocument();
      expect(screen.queryByText("Secret Operator Note")).not.toBeInTheDocument();
    });
  });

  it("in-flight privileged request cannot repopulate private data after privilege loss", async () => {
    let resolveVerificationReq: (value: any /* eslint-disable-line @typescript-eslint/no-explicit-any */) => void;
    const verificationPromise = new Promise((resolve) => { resolveVerificationReq = resolve; });

    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return { response: { ok: true, status: 200 }, data: { id: 1, system_roles: ["operator"], organizations: [] } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
      }
      if (url.includes("/verification/")) {
        return verificationPromise as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
      }
      return { data: { results: [] } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
    });

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText("Loading case details...")).toBeInTheDocument();
    });

    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return { response: { ok: false, status: 401 }, data: null } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
      }
      return { error: { detail: "Unauthorized" }, response: { status: 401 } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
    });

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });

    await waitFor(() => {
        expect(screen.queryByText("Unauthorized")).toBeInTheDocument();
    });

    await act(async () => {
      resolveVerificationReq({ data: { id: "v-1", status: "under_review", version: 1, decisions: [], notes: [{ id: "n-2", note: "Delayed Secret" }] } });
    });

    await waitFor(() => {
      expect(screen.getByText("Unauthorized")).toBeInTheDocument();
      expect(screen.queryByText("Delayed Secret")).not.toBeInTheDocument();
    });
  });

  it("direct route as non-operator must not render cached data and shows Unauthorized", async () => {
    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return { response: { ok: true, status: 200 }, data: { id: 1, system_roles: [], organizations: [] } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
      }
      if (url.includes("/verification/")) {
        return { data: { id: "v-1", status: "under_review", version: 1, decisions: [], notes: [{ id: "n-1", note: "Secret Operator Note" }] } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
      }
      return { data: { results: [] } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
    });

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText("Unauthorized")).toBeInTheDocument();
    }, { timeout: 2000 });
    expect(screen.queryByText("Secret Operator Note")).not.toBeInTheDocument();
  });

  it("error semantics: 403 yields error state, not empty successful state", async () => {
    vi.mocked(client.GET).mockImplementation(async (url: string) => {
      if (url === "/api/auth/me") {
        return { response: { ok: true, status: 200 }, data: { id: 1, system_roles: ["operator"], organizations: [] } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
      }
      if (url.includes("/verification/")) {
        return { error: { detail: "You do not have permission to perform this action." }, response: { status: 403 } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
      }
      return { data: { results: [] } } as any /* eslint-disable-line @typescript-eslint/no-explicit-any */;
    });

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText("Error loading case details.")).toBeInTheDocument();
    });
  });
});
