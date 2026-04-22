import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { TuningSuggestionsSection } from "../components/TuningSuggestionsSection";
import * as api from "../api";

vi.mock("../api");

const SUG_SUPPRESS = {
  id: "aaaaaaaa-0000-0000-0000-000000000001",
  created_at: "2026-04-12T10:00:00+00:00",
  signature: "ET SCAN Potential SSH Scan",
  signature_id: 2001219,
  hit_count: 847,
  assessment: "Typical scanning noise on home networks.",
  action: "suppress" as const,
  status: "pending" as const,
  confirmed_at: null,
  threshold_count: null,
  threshold_seconds: null,
  threshold_track: null,
  threshold_type: null,
};

const SUG_THRESHOLD = {
  id: "bbbbbbbb-0000-0000-0000-000000000002",
  created_at: "2026-04-12T10:00:00+00:00",
  signature: "ET INFO Session Traversal Utls",
  signature_id: 2008581,
  hit_count: 312,
  assessment: "STUN traffic from VoIP or WebRTC; benign on home networks.",
  action: "threshold-adjust" as const,
  status: "pending" as const,
  confirmed_at: null,
  threshold_count: 5,
  threshold_seconds: 60,
  threshold_track: "by_src",
  threshold_type: "limit",
};

const SUG_KEEP = {
  id: "cccccccc-0000-0000-0000-000000000003",
  created_at: "2026-04-12T10:00:00+00:00",
  signature: "ET MALWARE Cobalt Strike Beacon",
  signature_id: 2019284,
  hit_count: 15,
  assessment: "Genuine C2 signature — keep this rule.",
  action: "keep" as const,
  status: "pending" as const,
  confirmed_at: null,
  threshold_count: null,
  threshold_seconds: null,
  threshold_track: null,
  threshold_type: null,
};

beforeEach(() => {
  vi.mocked(api.fetchTuningSuggestions).mockResolvedValue([SUG_SUPPRESS, SUG_THRESHOLD, SUG_KEEP]);
  vi.mocked(api.confirmSuggestion).mockResolvedValue({ ...SUG_SUPPRESS, status: "confirmed", confirmed_at: "2026-04-12T10:01:00+00:00" });
  vi.mocked(api.dismissSuggestion).mockResolvedValue({ ...SUG_SUPPRESS, status: "dismissed" });
  vi.mocked(api.runTuner).mockResolvedValue([]);
});

// ── List ──────────────────────────────────────────────────────────────────────

describe("TuningSuggestionsSection — list", () => {
  it("renders signature names after loading", async () => {
    render(<TuningSuggestionsSection />);
    await screen.findByText("ET SCAN Potential SSH Scan");
    expect(screen.getByText("ET INFO Session Traversal Utls")).toBeInTheDocument();
    expect(screen.getByText("ET MALWARE Cobalt Strike Beacon")).toBeInTheDocument();
  });

  it("renders action badges for each suggestion", async () => {
    render(<TuningSuggestionsSection />);
    await screen.findByText("ET SCAN Potential SSH Scan");
    expect(screen.getByText("Suppress")).toBeInTheDocument();
    expect(screen.getByText("Threshold Adjust")).toBeInTheDocument();
    expect(screen.getByText("Keep")).toBeInTheDocument();
  });

  it("renders hit counts for each suggestion", async () => {
    render(<TuningSuggestionsSection />);
    await screen.findByText(/847/);
    expect(screen.getByText(/312/)).toBeInTheDocument();
  });

  it("renders assessment text", async () => {
    render(<TuningSuggestionsSection />);
    await screen.findByText("Typical scanning noise on home networks.");
  });

  it("shows empty state when no suggestions", async () => {
    vi.mocked(api.fetchTuningSuggestions).mockResolvedValue([]);
    render(<TuningSuggestionsSection />);
    await screen.findByText(/no pending suggestions/i);
  });

  it("shows error message on fetch failure", async () => {
    vi.mocked(api.fetchTuningSuggestions).mockRejectedValue(new Error("Network error"));
    render(<TuningSuggestionsSection />);
    await screen.findByText("Network error");
  });

  it("shows Run Analysis button", async () => {
    render(<TuningSuggestionsSection />);
    expect(screen.getByRole("button", { name: /run analysis/i })).toBeInTheDocument();
  });
});

// ── Confirm ───────────────────────────────────────────────────────────────────

describe("TuningSuggestionsSection — confirm", () => {
  it("shows Apply Suppression button for suppress suggestions", async () => {
    render(<TuningSuggestionsSection />);
    await screen.findByText("ET SCAN Potential SSH Scan");
    expect(screen.getByRole("button", { name: /apply suppression/i })).toBeInTheDocument();
  });

  it("shows Apply Threshold button for threshold-adjust suggestions", async () => {
    render(<TuningSuggestionsSection />);
    await screen.findByText("ET INFO Session Traversal Utls");
    expect(screen.getByRole("button", { name: /apply threshold/i })).toBeInTheDocument();
  });

  it("pre-fills threshold form with LLM-suggested values", async () => {
    vi.mocked(api.fetchTuningSuggestions).mockResolvedValue([SUG_THRESHOLD]);
    render(<TuningSuggestionsSection />);
    await screen.findByText("ET INFO Session Traversal Utls");
    expect(screen.getByLabelText(/threshold count/i)).toHaveValue(5);
    expect(screen.getByLabelText(/threshold seconds/i)).toHaveValue(60);
  });

  it("does not show confirm button for keep suggestions", async () => {
    vi.mocked(api.fetchTuningSuggestions).mockResolvedValue([SUG_KEEP]);
    render(<TuningSuggestionsSection />);
    await screen.findByText("ET MALWARE Cobalt Strike Beacon");
    expect(screen.queryByRole("button", { name: /apply suppression/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /apply threshold/i })).not.toBeInTheDocument();
  });

  it("removes suggestion from list after confirm (suppress)", async () => {
    render(<TuningSuggestionsSection />);
    await screen.findByText("ET SCAN Potential SSH Scan");

    fireEvent.click(screen.getByRole("button", { name: /apply suppression/i }));

    await waitFor(() => {
      expect(screen.queryByText("ET SCAN Potential SSH Scan")).not.toBeInTheDocument();
    });
    expect(api.confirmSuggestion).toHaveBeenCalledWith(SUG_SUPPRESS.id, undefined);
  });

  it("calls confirmSuggestion with threshold params when Apply Threshold is clicked", async () => {
    vi.mocked(api.fetchTuningSuggestions).mockResolvedValue([SUG_THRESHOLD]);
    vi.mocked(api.confirmSuggestion).mockResolvedValue({
      ...SUG_THRESHOLD,
      status: "confirmed",
      confirmed_at: "2026-04-12T10:01:00+00:00",
    });
    render(<TuningSuggestionsSection />);
    await screen.findByText("ET INFO Session Traversal Utls");

    fireEvent.click(screen.getByRole("button", { name: /apply threshold/i }));

    await waitFor(() => {
      expect(api.confirmSuggestion).toHaveBeenCalledWith(SUG_THRESHOLD.id, {
        threshold_count: 5,
        threshold_seconds: 60,
        threshold_track: "by_src",
        threshold_type: "limit",
      });
    });
  });
});

// ── Dismiss ───────────────────────────────────────────────────────────────────

describe("TuningSuggestionsSection — dismiss", () => {
  it("shows Dismiss button for each suggestion", async () => {
    render(<TuningSuggestionsSection />);
    await screen.findByText("ET SCAN Potential SSH Scan");
    const dismissButtons = screen.getAllByRole("button", { name: /dismiss/i });
    expect(dismissButtons.length).toBe(3);
  });

  it("removes suggestion from list after dismiss", async () => {
    vi.mocked(api.fetchTuningSuggestions).mockResolvedValue([SUG_SUPPRESS]);
    render(<TuningSuggestionsSection />);
    await screen.findByText("ET SCAN Potential SSH Scan");

    fireEvent.click(screen.getByRole("button", { name: /dismiss/i }));

    await waitFor(() => {
      expect(screen.queryByText("ET SCAN Potential SSH Scan")).not.toBeInTheDocument();
    });
    expect(api.dismissSuggestion).toHaveBeenCalledWith(SUG_SUPPRESS.id);
  });
});

// ── Run Analysis ──────────────────────────────────────────────────────────────

describe("TuningSuggestionsSection — Run Analysis", () => {
  it("shows analysing spinner while running", async () => {
    vi.mocked(api.runTuner).mockImplementation(() => new Promise(() => {}));
    render(<TuningSuggestionsSection />);
    await screen.findByRole("button", { name: /run analysis/i });

    fireEvent.click(screen.getByRole("button", { name: /run analysis/i }));
    expect(screen.getByRole("button", { name: /analysing/i })).toBeInTheDocument();
  });

  it("shows success message when run returns empty list", async () => {
    vi.mocked(api.runTuner).mockResolvedValue([]);
    render(<TuningSuggestionsSection />);
    await screen.findByRole("button", { name: /run analysis/i });

    fireEvent.click(screen.getByRole("button", { name: /run analysis/i }));
    await screen.findByText(/analysis complete/i);
  });

  it("shows count message when new suggestions are created", async () => {
    vi.mocked(api.runTuner).mockResolvedValue([SUG_SUPPRESS]);
    vi.mocked(api.fetchTuningSuggestions).mockResolvedValue([SUG_SUPPRESS]);
    render(<TuningSuggestionsSection />);
    await screen.findByRole("button", { name: /run analysis/i });

    fireEvent.click(screen.getByRole("button", { name: /run analysis/i }));
    await screen.findByText(/1 new suggestion/i);
  });

  it("shows error when run fails (LLM not configured)", async () => {
    vi.mocked(api.runTuner).mockRejectedValue(new Error("LLM not configured"));
    render(<TuningSuggestionsSection />);
    await screen.findByRole("button", { name: /run analysis/i });

    fireEvent.click(screen.getByRole("button", { name: /run analysis/i }));
    await screen.findByText("LLM not configured");
  });
});
