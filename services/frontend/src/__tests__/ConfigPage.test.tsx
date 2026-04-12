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

const LLM_SETTINGS = { url: "http://lmstudio:1234/v1", model: "gemma-4-27b", timeout: 90, max_tokens: 512 };

beforeEach(() => {
  vi.mocked(api.fetchRuleCategories).mockResolvedValue(CATEGORIES);
  vi.mocked(api.updateRuleCategories).mockResolvedValue(CATEGORIES);
  vi.mocked(api.reloadSuricata).mockResolvedValue("Rules updated.");
  vi.mocked(api.fetchHaSettings).mockResolvedValue(HA_CONFIGURED);
  vi.mocked(api.updateHaSettings).mockResolvedValue({ enabled: false, configured: true });
  vi.mocked(api.testHaSend).mockResolvedValue(undefined);
  vi.mocked(api.fetchLlmSettings).mockResolvedValue(LLM_SETTINGS);
  vi.mocked(api.updateLlmSettings).mockResolvedValue(LLM_SETTINGS);
  vi.mocked(api.testLlm).mockResolvedValue({ content: '{"summary":"test","severity_reasoning":"ok","recommended_action":"nothing"}' });
  vi.mocked(api.fetchTuningSuggestions).mockResolvedValue([]);
  vi.mocked(api.fetchPiholeSettings).mockResolvedValue({ url: "http://pihole:80", enabled: true, configured: true });
  vi.mocked(api.updatePiholeSettings).mockResolvedValue({ url: "http://pihole:80", enabled: true, configured: true });
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

// ── AI Enrichment ─────────────────────────────────────────────────────────────

describe("ConfigPage — AI Enrichment", () => {
  it("renders LLM settings fields with loaded values", async () => {
    render(<ConfigPage />);
    const urlInput = await screen.findByPlaceholderText(/192.168.1.x:1234/);
    expect(urlInput).toHaveValue("http://lmstudio:1234/v1");
    expect(screen.getByPlaceholderText("gemma-4-27b")).toHaveValue("gemma-4-27b");
  });

  it("calls updateLlmSettings when Save is clicked", async () => {
    render(<ConfigPage />);
    await screen.findByPlaceholderText(/192.168.1.x:1234/);

    // First Save button in DOM belongs to the LLM section (Pi-hole Save comes later)
    fireEvent.click(screen.getAllByRole("button", { name: /^save$/i })[0]);

    await waitFor(() => {
      expect(api.updateLlmSettings).toHaveBeenCalledWith(LLM_SETTINGS);
    });
  });

  it("shows success message after save", async () => {
    render(<ConfigPage />);
    await screen.findByPlaceholderText(/192.168.1.x:1234/);

    fireEvent.click(screen.getAllByRole("button", { name: /^save$/i })[0]);

    await screen.findByText(/settings saved/i);
  });

  it("shows error message when save fails", async () => {
    vi.mocked(api.updateLlmSettings).mockRejectedValue(new Error("DB error"));
    render(<ConfigPage />);
    await screen.findByPlaceholderText(/192.168.1.x:1234/);

    fireEvent.click(screen.getAllByRole("button", { name: /^save$/i })[0]);

    await screen.findByText("DB error");
  });

  it("calls testLlm when Send test prompt is clicked", async () => {
    render(<ConfigPage />);
    await screen.findByPlaceholderText(/192.168.1.x:1234/);

    fireEvent.click(screen.getByRole("button", { name: /send test prompt/i }));

    await waitFor(() => {
      expect(api.testLlm).toHaveBeenCalled();
    });
  });

  it("renders pretty-printed JSON response after successful test", async () => {
    render(<ConfigPage />);
    await screen.findByPlaceholderText(/192.168.1.x:1234/);

    fireEvent.click(screen.getByRole("button", { name: /send test prompt/i }));

    await screen.findByText(/LLM response/i);
    expect(screen.getByText(/"summary"/)).toBeInTheDocument();
  });

  it("renders error content when test fails", async () => {
    vi.mocked(api.testLlm).mockRejectedValue(new Error("Connection refused"));
    render(<ConfigPage />);
    await screen.findByPlaceholderText(/192.168.1.x:1234/);

    fireEvent.click(screen.getByRole("button", { name: /send test prompt/i }));

    await screen.findByText("Connection refused");
  });

  it("disables Send test prompt button when URL/model are empty", async () => {
    vi.mocked(api.fetchLlmSettings).mockResolvedValue({ url: "", model: "", timeout: 90, max_tokens: 512 });
    render(<ConfigPage />);
    await screen.findByPlaceholderText(/192.168.1.x:1234/);

    expect(screen.getByRole("button", { name: /send test prompt/i })).toBeDisabled();
  });
});

// ── Home Assistant ────────────────────────────────────────────────────────────

describe("ConfigPage — Home Assistant", () => {
  it("renders HA section with toggle and Send test button when configured", async () => {
    render(<ConfigPage />);
    await screen.findByText("Home Assistant");
    expect(screen.getByRole("button", { name: /^send test$/i })).toBeInTheDocument();
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
    expect(screen.queryByRole("button", { name: /^send test$/i })).not.toBeInTheDocument();
  });

  it("calls testHaSend when Send test is clicked", async () => {
    render(<ConfigPage />);
    await screen.findByText("Home Assistant");

    fireEvent.click(screen.getByRole("button", { name: /^send test$/i }));

    await waitFor(() => {
      expect(api.testHaSend).toHaveBeenCalled();
    });
  });

  it("shows success message after successful test send", async () => {
    render(<ConfigPage />);
    await screen.findByText("Home Assistant");

    fireEvent.click(screen.getByRole("button", { name: /^send test$/i }));

    await screen.findByText("Test notification sent.");
  });

  it("shows error message when test send fails", async () => {
    vi.mocked(api.testHaSend).mockRejectedValue(new Error("Connection refused"));
    render(<ConfigPage />);
    await screen.findByText("Home Assistant");

    fireEvent.click(screen.getByRole("button", { name: /^send test$/i }));

    await screen.findByText("Connection refused");
  });
});
