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

beforeEach(() => {
  vi.mocked(api.fetchRuleCategories).mockResolvedValue(CATEGORIES);
  vi.mocked(api.updateRuleCategories).mockResolvedValue(CATEGORIES);
  vi.mocked(api.reloadSuricata).mockResolvedValue("Rules updated.");
});

describe("ConfigPage", () => {
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
    // Order matches CATEGORIES array: Malware(enabled), P2P(disabled), Scanning(enabled)
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
