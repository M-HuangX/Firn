/**
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ─── Mock hooks ──────────────────────────────────────────────────────────────

const mockWatchlistData = {
  categories: {
    tech: { label: "Technology", tickers: ["AAPL", "MSFT", "GOOG"] },
    energy: { label: "Energy", tickers: ["XOM"] },
  },
};

const mockSourcesData = {
  sources: [
    { name: "Yahoo Finance", tier: 1, bias: null, last_updated: "2025-05-10T10:00:00Z", new_count: 5 },
    { name: "Seeking Alpha", tier: 2, bias: "bullish", last_updated: "2025-05-09T08:00:00Z", new_count: 3 },
    { name: "Reuters", tier: 3, bias: null, last_updated: null, new_count: 0 },
  ],
};

const mockUpdateWatchlist = { mutate: vi.fn(), isPending: false, isError: false, isSuccess: false, error: null };
const mockRefreshSources = { mutate: vi.fn(), isPending: false, isError: false, isSuccess: false, error: null, data: null };
const mockRunDigest = { mutate: vi.fn(), isPending: false, isError: false, isSuccess: false, error: null, data: null };
const mockRunAnalysis = { mutate: vi.fn(), isPending: false, isError: false, isSuccess: false, error: null, data: null };

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/hooks/use-api", () => ({
  useWatchlist: () => ({ data: mockWatchlistData, isLoading: false, error: null }),
  useUpdateWatchlist: () => mockUpdateWatchlist,
  useSources: () => ({ data: mockSourcesData, isLoading: false, error: null }),
  useRefreshSources: () => mockRefreshSources,
  useRunDigest: () => mockRunDigest,
  useRunAnalysis: () => mockRunAnalysis,
}));

// We need to dynamically import after mocking
let WatchlistEditor: () => ReturnType<typeof createElement>;
let SourceStatus: () => ReturnType<typeof createElement>;
let OperationsPanel: () => ReturnType<typeof createElement>;

beforeEach(async () => {
  vi.clearAllMocks();
  const wl = await import("./watchlist-editor");
  WatchlistEditor = wl.WatchlistEditor as unknown as typeof WatchlistEditor;
  const ss = await import("./source-status");
  SourceStatus = ss.SourceStatus as unknown as typeof SourceStatus;
  const op = await import("./operations-panel");
  OperationsPanel = op.OperationsPanel as unknown as typeof OperationsPanel;
});

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

// ─── WatchlistEditor ────────────────────────────────────────────────────────

describe("WatchlistEditor", () => {
  it("renders categories with labels", () => {
    render(createElement(WatchlistEditor), { wrapper: createWrapper() });
    expect(screen.getByText("Technology")).toBeDefined();
    expect(screen.getByText("Energy")).toBeDefined();
  });

  it("renders tickers as chips", () => {
    render(createElement(WatchlistEditor), { wrapper: createWrapper() });
    expect(screen.getByText("AAPL")).toBeDefined();
    expect(screen.getByText("MSFT")).toBeDefined();
    expect(screen.getByText("GOOG")).toBeDefined();
    expect(screen.getByText("XOM")).toBeDefined();
  });

  it("can add a ticker via input and button", async () => {
    render(createElement(WatchlistEditor), { wrapper: createWrapper() });
    const inputs = screen.getAllByPlaceholderText("Add ticker...");
    const addButtons = screen.getAllByText("Add");
    // Type into first category input (tech)
    fireEvent.change(inputs[0], { target: { value: "NVDA" } });
    fireEvent.click(addButtons[0]);
    await waitFor(() => {
      expect(screen.getByText("NVDA")).toBeDefined();
    });
  });

  it("can remove a ticker", async () => {
    render(createElement(WatchlistEditor), { wrapper: createWrapper() });
    const removeButtons = screen.getAllByLabelText(/^Remove /);
    const aaplRemove = removeButtons.find((btn) =>
      btn.getAttribute("aria-label") === "Remove AAPL"
    );
    expect(aaplRemove).toBeDefined();
    fireEvent.click(aaplRemove!);
    await waitFor(() => {
      expect(screen.queryByText("AAPL")).toBeNull();
    });
  });

  it("shows unsaved changes indicator after modification", async () => {
    render(createElement(WatchlistEditor), { wrapper: createWrapper() });
    // Initially no unsaved indicator
    expect(screen.queryByText("Unsaved changes")).toBeNull();
    // Remove a ticker to trigger change
    const removeBtn = screen.getAllByLabelText(/^Remove /)[0];
    fireEvent.click(removeBtn);
    await waitFor(() => {
      expect(screen.getByText("Unsaved changes")).toBeDefined();
    });
  });

  it("save button is disabled when no changes", () => {
    render(createElement(WatchlistEditor), { wrapper: createWrapper() });
    const saveBtn = screen.getByText("Save Changes");
    expect((saveBtn as HTMLButtonElement).disabled).toBe(true);
  });
});

// ─── SourceStatus ──────────────────────────────────────────────────────────

describe("SourceStatus", () => {
  it("renders source table with names", () => {
    render(createElement(SourceStatus), { wrapper: createWrapper() });
    expect(screen.getByText("Yahoo Finance")).toBeDefined();
    expect(screen.getByText("Seeking Alpha")).toBeDefined();
    expect(screen.getByText("Reuters")).toBeDefined();
  });

  it("renders tier badges", () => {
    render(createElement(SourceStatus), { wrapper: createWrapper() });
    expect(screen.getByText("T1")).toBeDefined();
    expect(screen.getByText("T2")).toBeDefined();
    expect(screen.getByText("T3")).toBeDefined();
  });

  it("renders bias when available", () => {
    render(createElement(SourceStatus), { wrapper: createWrapper() });
    expect(screen.getByText("bullish")).toBeDefined();
  });

  it("renders new article counts", () => {
    render(createElement(SourceStatus), { wrapper: createWrapper() });
    expect(screen.getByText("5")).toBeDefined();
    expect(screen.getByText("3")).toBeDefined();
    expect(screen.getByText("0")).toBeDefined();
  });

  it("has a Refresh Sources button", () => {
    render(createElement(SourceStatus), { wrapper: createWrapper() });
    expect(screen.getByText("Refresh Sources")).toBeDefined();
  });
});

// ─── OperationsPanel ──────────────────────────────────────────────────────

describe("OperationsPanel", () => {
  it("renders Run Digest button", () => {
    render(createElement(OperationsPanel), { wrapper: createWrapper() });
    expect(screen.getByText("Run Digest")).toBeDefined();
  });

  it("calls mutate on digest button click", () => {
    render(createElement(OperationsPanel), { wrapper: createWrapper() });
    const btn = screen.getByText("Run Digest");
    fireEvent.click(btn);
    expect(mockRunDigest.mutate).toHaveBeenCalled();
  });
});
