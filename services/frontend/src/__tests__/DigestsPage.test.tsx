import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { DigestsPage } from "../components/DigestsPage";
import * as api from "../api";

vi.mock("../api");

const DIGEST_A = {
  id: "eeeeeeee-0000-0000-0000-000000000005",
  created_at: "2026-04-12T10:00:00+00:00",
  period_start: "2026-04-11T10:00:00+00:00",
  period_end: "2026-04-12T10:00:00+00:00",
  risk_level: "medium",
  content: JSON.stringify({
    overall_risk: "medium",
    summary: "Moderate activity with a few notable signatures.",
    notable_incidents: ["Repeated SSH scan from 192.168.1.5."],
    emerging_trends: [],
    recommended_actions: ["Review 192.168.1.5 access logs."],
  }),
};

const DIGEST_B = {
  id: "ffffffff-0000-0000-0000-000000000006",
  created_at: "2026-04-11T10:00:00+00:00",
  period_start: "2026-04-10T10:00:00+00:00",
  period_end: "2026-04-11T10:00:00+00:00",
  risk_level: "low",
  content: JSON.stringify({
    overall_risk: "low",
    summary: "Quiet period with minimal activity.",
    notable_incidents: [],
    emerging_trends: [],
    recommended_actions: [],
  }),
};

const EMPTY_RESPONSE = { items: [], total: 0, limit: 10, offset: 0 };
const LIST_RESPONSE = { items: [DIGEST_A, DIGEST_B], total: 2, limit: 10, offset: 0 };

beforeEach(() => {
  vi.mocked(api.fetchDigests).mockResolvedValue(LIST_RESPONSE);
  vi.mocked(api.fetchDigest).mockResolvedValue(DIGEST_A);
  vi.mocked(api.generateDigest).mockResolvedValue(DIGEST_A);
});

// ── DigestsPage list ──────────────────────────────────────────────────────────

describe("DigestsPage — list", () => {
  it("renders digest rows after loading", async () => {
    render(<DigestsPage />);
    await screen.findByText("medium");
    expect(screen.getByText("low")).toBeInTheDocument();
  });

  it("shows risk badges for each digest", async () => {
    render(<DigestsPage />);
    await screen.findByText("medium");
    const badges = screen.getAllByText(/^(low|medium|high|critical)$/);
    expect(badges.length).toBeGreaterThanOrEqual(2);
  });

  it("shows empty state when no digests", async () => {
    vi.mocked(api.fetchDigests).mockResolvedValue(EMPTY_RESPONSE);
    render(<DigestsPage />);
    await screen.findByText(/no digests generated yet/i);
  });

  it("shows error message on fetch failure", async () => {
    vi.mocked(api.fetchDigests).mockRejectedValue(new Error("Network error"));
    render(<DigestsPage />);
    await screen.findByText("Network error");
  });

  it("renders Generate Now button", async () => {
    render(<DigestsPage />);
    expect(screen.getByRole("button", { name: /generate now/i })).toBeInTheDocument();
  });
});

// ── DigestsPage — Generate Now ────────────────────────────────────────────────

describe("DigestsPage — Generate Now", () => {
  it("shows spinner while generating", async () => {
    vi.mocked(api.generateDigest).mockImplementation(
      () => new Promise(() => {}) // never resolves
    );
    render(<DigestsPage />);
    await screen.findByRole("button", { name: /generate now/i });

    fireEvent.click(screen.getByRole("button", { name: /generate now/i }));
    expect(screen.getByRole("button", { name: /generating/i })).toBeInTheDocument();
  });

  it("shows warning when generation returns null (too few alerts)", async () => {
    vi.mocked(api.generateDigest).mockResolvedValue(null);
    render(<DigestsPage />);
    await screen.findByRole("button", { name: /generate now/i });

    fireEvent.click(screen.getByRole("button", { name: /generate now/i }));
    await screen.findByText(/not enough alerts/i);
  });

  it("shows error message when generation throws", async () => {
    vi.mocked(api.generateDigest).mockRejectedValue(new Error("LLM not configured"));
    render(<DigestsPage />);
    await screen.findByRole("button", { name: /generate now/i });

    fireEvent.click(screen.getByRole("button", { name: /generate now/i }));
    await screen.findByText("LLM not configured");
  });

  it("refreshes list and opens drawer on success", async () => {
    render(<DigestsPage />);
    await screen.findByRole("button", { name: /generate now/i });

    fireEvent.click(screen.getByRole("button", { name: /generate now/i }));

    await screen.findByRole("dialog", { name: /digest detail/i });
  });
});

// ── DigestsPage — drawer ──────────────────────────────────────────────────────

describe("DigestsPage — drawer", () => {
  it("opens digest drawer when row is clicked", async () => {
    render(<DigestsPage />);
    await screen.findByText("medium");

    const rows = screen.getAllByRole("row").filter((r) => r.getAttribute("class")?.includes("cursor-pointer"));
    fireEvent.click(rows[0]);

    await waitFor(() => {
      expect(api.fetchDigest).toHaveBeenCalledWith(DIGEST_A.id);
    });
    await screen.findByRole("dialog", { name: /digest detail/i });
  });

  it("shows summary in drawer", async () => {
    render(<DigestsPage />);
    await screen.findByText("medium");

    const rows = screen.getAllByRole("row").filter((r) => r.getAttribute("class")?.includes("cursor-pointer"));
    fireEvent.click(rows[0]);

    await screen.findByText("Moderate activity with a few notable signatures.");
  });

  it("shows notable incidents in drawer", async () => {
    render(<DigestsPage />);
    await screen.findByText("medium");

    const rows = screen.getAllByRole("row").filter((r) => r.getAttribute("class")?.includes("cursor-pointer"));
    fireEvent.click(rows[0]);

    await screen.findByText("Repeated SSH scan from 192.168.1.5.");
  });

  it("shows recommended actions in drawer", async () => {
    render(<DigestsPage />);
    await screen.findByText("medium");

    const rows = screen.getAllByRole("row").filter((r) => r.getAttribute("class")?.includes("cursor-pointer"));
    fireEvent.click(rows[0]);

    await screen.findByText("Review 192.168.1.5 access logs.");
  });

  it("closes drawer on Escape key", async () => {
    render(<DigestsPage />);
    await screen.findByText("medium");

    const rows = screen.getAllByRole("row").filter((r) => r.getAttribute("class")?.includes("cursor-pointer"));
    fireEvent.click(rows[0]);
    await screen.findByRole("dialog", { name: /digest detail/i });

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /digest detail/i })).not.toBeInTheDocument();
    });
  });

  it("closes drawer when close button is clicked", async () => {
    render(<DigestsPage />);
    await screen.findByText("medium");

    const rows = screen.getAllByRole("row").filter((r) => r.getAttribute("class")?.includes("cursor-pointer"));
    fireEvent.click(rows[0]);
    await screen.findByRole("dialog", { name: /digest detail/i });

    fireEvent.click(screen.getByRole("button", { name: /close detail/i }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /digest detail/i })).not.toBeInTheDocument();
    });
  });
});
