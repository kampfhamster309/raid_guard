import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { StatusPage } from "../components/StatusPage";
import * as api from "../api";

vi.mock("../api");

const ALL_OK = {
  db: { ok: true },
  redis: { ok: true },
  ingestor: { ok: true },
  enricher: { ok: true },
  capture_agent: {
    ok: true,
    reachable: true,
    capture_state: "streaming",
    reconnect_count: 0,
    message: "",
  },
  suricata: { ok: true, running: true, health: "healthy" },
  detection: { ok: true, last_alert_hours_ago: 0.5, stall_threshold_hours: 6 },
};

const CAPTURE_DOWN = {
  ...ALL_OK,
  capture_agent: {
    ok: false,
    reachable: false,
    capture_state: "reconnecting",
    reconnect_count: 3,
    message: "Connection refused",
  },
};

const DB_DOWN = { ...ALL_OK, db: { ok: false } };
const INGESTOR_DOWN = { ...ALL_OK, ingestor: { ok: false } };

beforeEach(() => {
  vi.mocked(api.fetchStatus).mockResolvedValue(ALL_OK);
});

describe("StatusPage — all ok", () => {
  it("shows the all-systems-operational banner", async () => {
    render(<StatusPage />);
    await screen.findByText("All systems operational");
  });

  it("renders a card for each pipeline component", async () => {
    render(<StatusPage />);
    await screen.findByText("All systems operational");
    expect(screen.getByText("Fritzbox Capture")).toBeInTheDocument();
    expect(screen.getByText("Suricata IDS")).toBeInTheDocument();
    expect(screen.getByText("TimescaleDB")).toBeInTheDocument();
    expect(screen.getByText("Redis")).toBeInTheDocument();
    expect(screen.getByText("Alert Ingestor")).toBeInTheDocument();
    expect(screen.getByText("AI Enricher")).toBeInTheDocument();
    expect(screen.getByText("Alert Detection")).toBeInTheDocument();
  });

  it("shows the capture state label", async () => {
    render(<StatusPage />);
    await screen.findByText("Streaming");
  });

  it("shows Suricata health status", async () => {
    render(<StatusPage />);
    await screen.findByText("Healthy");
  });
});

describe("StatusPage — degraded components", () => {
  it("shows degraded banner when capture agent is down", async () => {
    vi.mocked(api.fetchStatus).mockResolvedValue(CAPTURE_DOWN);
    render(<StatusPage />);
    await screen.findByText("One or more components are not healthy");
  });

  it("shows 'Container not found' instead of 'Stopped' when Suricata can't be located", async () => {
    vi.mocked(api.fetchStatus).mockResolvedValue({
      ...ALL_OK,
      suricata: {
        ok: false,
        running: false,
        state: "not_found",
        message: "No Suricata container found",
      },
    });
    render(<StatusPage />);
    await screen.findByText("Container not found");
    expect(screen.getByText("No Suricata container found")).toBeInTheDocument();
  });

  it("shows 'Stopped' for a stopped Suricata container", async () => {
    vi.mocked(api.fetchStatus).mockResolvedValue({
      ...ALL_OK,
      suricata: { ok: false, running: false, state: "stopped", health: "unhealthy" },
    });
    render(<StatusPage />);
    await screen.findByText("Unhealthy");
    expect(screen.getAllByText("Stopped").length).toBeGreaterThan(0);
  });

  it("shows reconnect count when capture agent has retried", async () => {
    vi.mocked(api.fetchStatus).mockResolvedValue(CAPTURE_DOWN);
    render(<StatusPage />);
    await screen.findByText("3");
  });

  it("shows 'Agent unreachable' when capture agent is not reachable", async () => {
    vi.mocked(api.fetchStatus).mockResolvedValue(CAPTURE_DOWN);
    render(<StatusPage />);
    await screen.findByText("Agent unreachable");
  });

  it("shows degraded banner when DB is down", async () => {
    vi.mocked(api.fetchStatus).mockResolvedValue(DB_DOWN);
    render(<StatusPage />);
    await screen.findByText("One or more components are not healthy");
  });

  it("shows Stopped for a dead ingestor", async () => {
    vi.mocked(api.fetchStatus).mockResolvedValue(INGESTOR_DOWN);
    render(<StatusPage />);
    await screen.findByText("Stopped");
  });
});

describe("StatusPage — error state", () => {
  it("shows error message when fetch fails", async () => {
    vi.mocked(api.fetchStatus).mockRejectedValue(new Error("Network error"));
    render(<StatusPage />);
    await screen.findByText(/Could not reach the backend/);
  });
});

describe("StatusPage — refresh", () => {
  it("re-fetches status when the Refresh button is clicked", async () => {
    render(<StatusPage />);
    await screen.findByText("All systems operational");
    const callsBefore = vi.mocked(api.fetchStatus).mock.calls.length;
    fireEvent.click(screen.getByText("Refresh"));
    await waitFor(() =>
      expect(vi.mocked(api.fetchStatus).mock.calls.length).toBeGreaterThan(callsBefore),
    );
  });

  it("shows last updated time after load", async () => {
    render(<StatusPage />);
    await screen.findByText(/Last updated/);
  });
});

describe("StatusPage — silent pipeline (2026-11-24)", () => {
  it("flags no-traffic even though capture and Suricata report healthy", async () => {
    vi.mocked(api.fetchStatus).mockResolvedValue({
      ...ALL_OK,
      detection: {
        ok: false,
        reason: "eve_json_stale",
        eve_json_minutes_ago: 510,
        eve_json_stall_threshold_minutes: 15,
      },
    });
    render(<StatusPage />);
    await screen.findByText("One or more components are not healthy");
    expect(screen.getByText("No traffic reaching Suricata")).toBeInTheDocument();
    expect(screen.getByText(/hasn't logged any event for 8\.5 h/)).toBeInTheDocument();
  });

  it("shows detection stalled when alerts stop but traffic flows", async () => {
    vi.mocked(api.fetchStatus).mockResolvedValue({
      ...ALL_OK,
      detection: { ok: false, last_alert_hours_ago: 30, stall_threshold_hours: 6 },
    });
    render(<StatusPage />);
    await screen.findByText("Detection stalled");
  });

  it("shows last packet age and stale message on the capture card", async () => {
    vi.mocked(api.fetchStatus).mockResolvedValue({
      ...ALL_OK,
      capture_agent: {
        ...ALL_OK.capture_agent,
        ok: false,
        last_data_age_seconds: 600,
        data_stale: true,
        message: "No packets received for over 300s — stream stalled",
      },
    });
    render(<StatusPage />);
    await screen.findByText("10 min ago");
    expect(screen.getByText(/stream stalled/)).toBeInTheDocument();
  });

  it("still renders when the backend omits the detection key", async () => {
    const { detection: _omit, ...legacy } = ALL_OK;
    vi.mocked(api.fetchStatus).mockResolvedValue(legacy);
    render(<StatusPage />);
    await screen.findByText("All systems operational");
  });
});
