import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { ConfigPage } from "../components/ConfigPage";
import * as api from "../api";

vi.mock("../api");

const CATEGORIES = [
  { id: "emerging-malware", name: "Malware", description: "Malware C2 traffic", enabled: true },
  { id: "emerging-p2p", name: "P2P", description: "Peer-to-peer traffic", enabled: false },
  { id: "emerging-scan", name: "Scanning", description: "Port scans", enabled: true },
];

const HA_CONFIGURED: api.HaSettings = { enabled: true, configured: true };
const HA_NOT_CONFIGURED: api.HaSettings = { enabled: false, configured: false };

beforeEach(() => {
  vi.mocked(api.fetchRuleCategories).mockResolvedValue(CATEGORIES);
  vi.mocked(api.updateRuleCategories).mockResolvedValue(CATEGORIES);
  vi.mocked(api.reloadSuricata).mockResolvedValue("Rules updated.");
  vi.mocked(api.fetchHaSettings).mockResolvedValue(HA_CONFIGURED);
  vi.mocked(api.updateHaSettings).mockResolvedValue({ enabled: false, configured: true });
  vi.mocked(api.testHaSend).mockResolvedValue(undefined);
});

// ── Rule Categories ───────────────────────────────────────────────────────────

describe("ConfigPage — Rule Categories", () => {
  it("renders category list after loading", async () => {
    render(<ConfigPage />);
    await screen.findByText("Malware");
    expect(screen.getByText("P2P")).toBeInTheDocument();
    expect(screen.getByText("Scanning")).toBeInTheDocument();
  });

  it("shows enabled toggle for enabled categories and disabled for disabled ones", async () => {
    render(<ConfigPage />);
    await screen.findByText("Malware");

    const switches = screen.getAllByRole("switch");
    // First 3 are rule category toggles (order matches CATEGORIES array)
    expect(switches[0]).toHaveAttribute("aria-checked", "true");
    expect(switches[1]).toHaveAttribute("aria-checked", "false");
    expect(switches[2]).toHaveAttribute("aria-checked", "true");
  });

  it("calls updateRuleCategories when a toggle is clicked", async () => {
    render(<ConfigPage />);
    await screen.findByText("Malware");

    fireEvent.click(screen.getAllByRole("switch")[0]);

    await waitFor(() => {
      expect(api.updateRuleCategories).toHaveBeenCalled();
    });
  });

  it("calls reloadSuricata when Reload button is clicked", async () => {
    render(<ConfigPage />);
    await screen.findByText("Malware");

    fireEvent.click(screen.getByRole("button", { name: /reload suricata/i }));

    await waitFor(() => {
      expect(api.reloadSuricata).toHaveBeenCalled();
    });
  });

  it("shows success message after successful reload", async () => {
    render(<ConfigPage />);
    await screen.findByText("Malware");

    fireEvent.click(screen.getByRole("button", { name: /reload suricata/i }));

    await screen.findByText("Rules updated.");
  });

  it("shows error message when reload fails", async () => {
    vi.mocked(api.reloadSuricata).mockRejectedValue(new Error("Container not found"));
    render(<ConfigPage />);
    await screen.findByText("Malware");

    fireEvent.click(screen.getByRole("button", { name: /reload suricata/i }));

    await screen.findByText("Container not found");
  });
});

// ── Home Assistant ────────────────────────────────────────────────────────────

describe("ConfigPage — Home Assistant", () => {
  it("renders HA section with toggle and Send test button when configured", async () => {
    render(<ConfigPage />);
    await screen.findByText("Home Assistant");
    expect(screen.getByRole("button", { name: /send test/i })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /home assistant notifications/i })).toBeInTheDocument();
  });

  it("shows HA toggle as enabled when configured and enabled", async () => {
    render(<ConfigPage />);
    await screen.findByText("Home Assistant");
    const haSwitch = screen.getByRole("switch", { name: /home assistant notifications/i });
    expect(haSwitch).toHaveAttribute("aria-checked", "true");
  });

  it("calls updateHaSettings when HA toggle is clicked", async () => {
    render(<ConfigPage />);
    await screen.findByText("Home Assistant");

    fireEvent.click(screen.getByRole("switch", { name: /home assistant notifications/i }));

    await waitFor(() => {
      expect(api.updateHaSettings).toHaveBeenCalledWith(false);
    });
  });

  it("hides Send test button when HA is not configured", async () => {
    vi.mocked(api.fetchHaSettings).mockResolvedValue(HA_NOT_CONFIGURED);
    render(<ConfigPage />);
    await screen.findByText("Home Assistant");
    expect(screen.queryByRole("button", { name: /send test/i })).not.toBeInTheDocument();
  });

  it("calls testHaSend when Send test is clicked", async () => {
    render(<ConfigPage />);
    await screen.findByText("Home Assistant");

    fireEvent.click(screen.getByRole("button", { name: /send test/i }));

    await waitFor(() => {
      expect(api.testHaSend).toHaveBeenCalled();
    });
  });

  it("shows success message after successful test send", async () => {
    render(<ConfigPage />);
    await screen.findByText("Home Assistant");

    fireEvent.click(screen.getByRole("button", { name: /send test/i }));

    await screen.findByText("Test notification sent.");
  });

  it("shows error message when test send fails", async () => {
    vi.mocked(api.testHaSend).mockRejectedValue(new Error("Connection refused"));
    render(<ConfigPage />);
    await screen.findByText("Home Assistant");

    fireEvent.click(screen.getByRole("button", { name: /send test/i }));

    await screen.findByText("Connection refused");
  });
});
