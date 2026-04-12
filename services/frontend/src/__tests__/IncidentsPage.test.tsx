import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { IncidentsPage } from "../components/IncidentsPage";
import * as api from "../api";

vi.mock("../api");

const INCIDENT_A = {
  id: "aaaaaaaa-0000-0000-0000-000000000001",
  created_at: "2026-04-11T10:00:00+00:00",
  period_start: "2026-04-11T09:30:00+00:00",
  period_end: "2026-04-11T10:00:00+00:00",
  alert_ids: ["bbbbbbbb-0000-0000-0000-000000000002", "cccccccc-0000-0000-0000-000000000003"],
  narrative: "Host scanned network then established C2.",
  risk_level: "critical" as const,
  name: "SSH scan followed by C2",
};

const INCIDENT_B = {
  id: "dddddddd-0000-0000-0000-000000000004",
  created_at: "2026-04-11T09:00:00+00:00",
  period_start: "2026-04-11T08:30:00+00:00",
  period_end: "2026-04-11T09:00:00+00:00",
  alert_ids: ["eeeeeeee-0000-0000-0000-000000000005"],
  narrative: null,
  risk_level: "low" as const,
  name: null,
};

const INCIDENT_DETAIL = {
  ...INCIDENT_A,
  alerts: [
    {
      id: "bbbbbbbb-0000-0000-0000-000000000002",
      timestamp: "2026-04-11T09:30:00+00:00",
      src_ip: "192.168.1.5",
      dst_ip: "10.0.0.1",
      src_port: 54321,
      dst_port: 22,
      proto: "TCP",
      signature: "ET SCAN Potential SSH Scan",
      signature_id: 2001219,
      category: "Attempted Information Leak",
      severity: "warning" as const,
      enrichment_json: null,
      raw_json: null,
    },
  ],
};

const EMPTY_RESPONSE = { items: [], total: 0, limit: 20, offset: 0 };
const LIST_RESPONSE = { items: [INCIDENT_A, INCIDENT_B], total: 2, limit: 20, offset: 0 };

beforeEach(() => {
  vi.mocked(api.fetchIncidents).mockResolvedValue(LIST_RESPONSE);
  vi.mocked(api.fetchIncident).mockResolvedValue(INCIDENT_DETAIL);
});

// ── IncidentsPage list ────────────────────────────────────────────────────────

describe("IncidentsPage — list", () => {
  it("renders incident names after loading", async () => {
    render(<IncidentsPage />);
    await screen.findByText("SSH scan followed by C2");
    expect(screen.getByText("Unnamed incident")).toBeInTheDocument();
  });

  it("renders risk badges for each incident", async () => {
    render(<IncidentsPage />);
    await screen.findByText("SSH scan followed by C2");
    expect(screen.getByText("critical")).toBeInTheDocument();
    expect(screen.getByText("low")).toBeInTheDocument();
  });

  it("shows alert count per incident", async () => {
    render(<IncidentsPage />);
    await screen.findByText("SSH scan followed by C2");
    // INCIDENT_A has 2 alerts, INCIDENT_B has 1
    const counts = screen.getAllByRole("cell").filter((c) => ["2", "1"].includes(c.textContent ?? ""));
    expect(counts.length).toBeGreaterThan(0);
  });

  it("shows empty state when no incidents", async () => {
    vi.mocked(api.fetchIncidents).mockResolvedValue(EMPTY_RESPONSE);
    render(<IncidentsPage />);
    await screen.findByText(/no incidents detected yet/i);
  });

  it("shows error message on fetch failure", async () => {
    vi.mocked(api.fetchIncidents).mockRejectedValue(new Error("Network error"));
    render(<IncidentsPage />);
    await screen.findByText("Network error");
  });
});

// ── IncidentsPage drawer ──────────────────────────────────────────────────────

describe("IncidentsPage — drawer", () => {
  it("opens incident drawer when row is clicked", async () => {
    render(<IncidentsPage />);
    await screen.findByText("SSH scan followed by C2");

    fireEvent.click(screen.getByText("SSH scan followed by C2"));

    await waitFor(() => {
      expect(api.fetchIncident).toHaveBeenCalledWith(INCIDENT_A.id);
    });
    await screen.findByRole("dialog", { name: /incident detail/i });
  });

  it("shows incident narrative in drawer", async () => {
    render(<IncidentsPage />);
    await screen.findByText("SSH scan followed by C2");

    fireEvent.click(screen.getByText("SSH scan followed by C2"));

    await screen.findByText("Host scanned network then established C2.");
  });

  it("shows related alerts in drawer", async () => {
    render(<IncidentsPage />);
    await screen.findByText("SSH scan followed by C2");

    fireEvent.click(screen.getByText("SSH scan followed by C2"));

    await screen.findByText("ET SCAN Potential SSH Scan");
  });

  it("closes drawer on Escape key", async () => {
    render(<IncidentsPage />);
    await screen.findByText("SSH scan followed by C2");

    fireEvent.click(screen.getByText("SSH scan followed by C2"));
    await screen.findByRole("dialog", { name: /incident detail/i });

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /incident detail/i })).not.toBeInTheDocument();
    });
  });

  it("closes drawer when close button is clicked", async () => {
    render(<IncidentsPage />);
    await screen.findByText("SSH scan followed by C2");

    fireEvent.click(screen.getByText("SSH scan followed by C2"));
    await screen.findByRole("dialog", { name: /incident detail/i });

    fireEvent.click(screen.getByRole("button", { name: /close detail/i }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /incident detail/i })).not.toBeInTheDocument();
    });
  });
});

// ── RiskBadge ─────────────────────────────────────────────────────────────────

describe("RiskBadge", () => {
  it("renders all four risk levels", async () => {
    const { RiskBadge } = await import("../components/RiskBadge");
    const { render: r, screen: s } = await import("@testing-library/react");

    r(<>
      <RiskBadge level="low" />
      <RiskBadge level="medium" />
      <RiskBadge level="high" />
      <RiskBadge level="critical" />
    </>);

    expect(s.getByText("low")).toBeInTheDocument();
    expect(s.getByText("medium")).toBeInTheDocument();
    expect(s.getByText("high")).toBeInTheDocument();
    expect(s.getByText("critical")).toBeInTheDocument();
  });
});
