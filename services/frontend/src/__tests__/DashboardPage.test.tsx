import { render, screen, waitFor } from "@testing-library/react";
import { DashboardPage } from "../components/DashboardPage";
import * as api from "../api";
import type { Stats } from "../types";

vi.mock("../api", () => ({
  fetchStats: vi.fn(),
  getToken: vi.fn(() => "tok"),
  clearToken: vi.fn(),
}));

// recharts ResizeObserver not available in jsdom
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

const STATS: Stats = {
  total_alerts_24h: 142,
  alerts_per_hour: [{ hour: "2026-04-10T12:00:00", count: 10 }],
  top_src_ips: [{ name: "192.168.1.1", count: 30 }],
  top_signatures: [{ name: "ET SCAN", count: 20 }],
};

describe("DashboardPage", () => {
  it("shows loading state initially", () => {
    vi.mocked(api.fetchStats).mockReturnValue(new Promise(() => undefined));
    render(<DashboardPage />);
    expect(screen.getByText(/loading stats/i)).toBeInTheDocument();
  });

  it("shows error state on failure", async () => {
    vi.mocked(api.fetchStats).mockRejectedValueOnce(new Error("Network error"));
    render(<DashboardPage />);
    await waitFor(() =>
      expect(screen.getByText("Network error")).toBeInTheDocument()
    );
  });

  it("renders total alerts count", async () => {
    vi.mocked(api.fetchStats).mockResolvedValueOnce(STATS);
    render(<DashboardPage />);
    await waitFor(() =>
      expect(screen.getByText("142")).toBeInTheDocument()
    );
  });

  it("renders top source IPs section", async () => {
    vi.mocked(api.fetchStats).mockResolvedValueOnce(STATS);
    render(<DashboardPage />);
    await waitFor(() =>
      expect(screen.getByText("Top source IPs")).toBeInTheDocument()
    );
    expect(screen.getByText("192.168.1.1")).toBeInTheDocument();
  });

  it("renders top signatures section", async () => {
    vi.mocked(api.fetchStats).mockResolvedValueOnce(STATS);
    render(<DashboardPage />);
    await waitFor(() =>
      expect(screen.getByText("Top signatures")).toBeInTheDocument()
    );
    expect(screen.getByText("ET SCAN")).toBeInTheDocument();
  });
});
