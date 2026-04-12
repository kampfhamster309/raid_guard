import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { SinkholePage } from "../components/SinkholePage";
import * as api from "../api";

vi.mock("../api");

const SETTINGS_CONFIGURED: api.PiholeSettings = {
  url: "http://pihole:80",
  enabled: true,
  configured: true,
};

const SETTINGS_NOT_CONFIGURED: api.PiholeSettings = {
  url: "",
  enabled: false,
  configured: false,
};

const SETTINGS_DISABLED: api.PiholeSettings = {
  url: "http://pihole:80",
  enabled: false,
  configured: true,
};

const DOMAIN_A: api.BlockedDomain = {
  domain: "malware.example.com",
  comment: "Blocked by raid_guard",
  added_at: 1712325600,
  enabled: true,
};

const DOMAIN_B: api.BlockedDomain = {
  domain: "tracker.evil.org",
  comment: "Blocked by raid_guard",
  added_at: 1712325700,
  enabled: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.fetchPiholeSettings).mockResolvedValue(SETTINGS_CONFIGURED);
  vi.mocked(api.fetchBlocklist).mockResolvedValue([DOMAIN_A, DOMAIN_B]);
  vi.mocked(api.blockDomain).mockResolvedValue({ ...DOMAIN_A });
  vi.mocked(api.unblockDomain).mockResolvedValue(undefined);
});

// ── Not configured ────────────────────────────────────────────────────────────

describe("SinkholePage — not configured", () => {
  it("shows not-configured message when Pi-hole is not configured", async () => {
    vi.mocked(api.fetchPiholeSettings).mockResolvedValue(SETTINGS_NOT_CONFIGURED);
    render(<SinkholePage />);
    await screen.findByText(/not configured or disabled/i);
  });

  it("shows not-configured message when Pi-hole is disabled", async () => {
    vi.mocked(api.fetchPiholeSettings).mockResolvedValue(SETTINGS_DISABLED);
    render(<SinkholePage />);
    await screen.findByText(/not configured or disabled/i);
  });

  it("does not load blocklist when not configured", async () => {
    vi.mocked(api.fetchPiholeSettings).mockResolvedValue(SETTINGS_NOT_CONFIGURED);
    render(<SinkholePage />);
    await screen.findByText(/not configured or disabled/i);
    expect(api.fetchBlocklist).not.toHaveBeenCalled();
  });
});

// ── Blocklist ─────────────────────────────────────────────────────────────────

describe("SinkholePage — blocklist", () => {
  it("renders blocked domain names after loading", async () => {
    render(<SinkholePage />);
    await screen.findByText("malware.example.com");
    expect(screen.getByText("tracker.evil.org")).toBeInTheDocument();
  });

  it("shows empty state when no domains blocked", async () => {
    vi.mocked(api.fetchBlocklist).mockResolvedValue([]);
    render(<SinkholePage />);
    await screen.findByText(/no domains blocked yet/i);
  });

  it("shows error when blocklist fetch fails", async () => {
    vi.mocked(api.fetchBlocklist).mockRejectedValue(new Error("Connection refused"));
    render(<SinkholePage />);
    await screen.findByText("Connection refused");
  });
});

// ── Manual block ──────────────────────────────────────────────────────────────

describe("SinkholePage — manual block", () => {
  it("renders the block domain input", async () => {
    render(<SinkholePage />);
    await screen.findByText("malware.example.com");
    expect(screen.getByRole("textbox", { name: /domain to block/i })).toBeInTheDocument();
  });

  it("calls blockDomain and refreshes list on submit", async () => {
    render(<SinkholePage />);
    await screen.findByText("malware.example.com");

    const input = screen.getByRole("textbox", { name: /domain to block/i });
    fireEvent.change(input, { target: { value: "new.evil.com" } });
    fireEvent.click(screen.getByRole("button", { name: /^block$/i }));

    await waitFor(() => {
      expect(api.blockDomain).toHaveBeenCalledWith("new.evil.com");
    });
    expect(api.fetchBlocklist).toHaveBeenCalledTimes(2); // initial load + after block
  });

  it("shows error when block fails", async () => {
    vi.mocked(api.blockDomain).mockRejectedValue(new Error("Pi-hole unreachable"));
    render(<SinkholePage />);
    await screen.findByText("malware.example.com");

    const input = screen.getByRole("textbox", { name: /domain to block/i });
    fireEvent.change(input, { target: { value: "evil.com" } });
    fireEvent.click(screen.getByRole("button", { name: /^block$/i }));

    await screen.findByText("Pi-hole unreachable");
  });

  it("Block button is disabled when input is empty", async () => {
    render(<SinkholePage />);
    await screen.findByText("malware.example.com");

    const btn = screen.getByRole("button", { name: /^block$/i });
    expect(btn).toBeDisabled();
  });
});

// ── Unblock ───────────────────────────────────────────────────────────────────

describe("SinkholePage — unblock", () => {
  it("renders Unblock buttons for each domain", async () => {
    render(<SinkholePage />);
    await screen.findByText("malware.example.com");

    const btns = screen.getAllByRole("button", { name: /unblock/i });
    expect(btns.length).toBe(2);
  });

  it("removes domain from list after unblock", async () => {
    render(<SinkholePage />);
    await screen.findByText("malware.example.com");

    fireEvent.click(screen.getByRole("button", { name: /unblock malware.example.com/i }));

    await waitFor(() => {
      expect(screen.queryByText("malware.example.com")).not.toBeInTheDocument();
    });
    expect(api.unblockDomain).toHaveBeenCalledWith("malware.example.com");
  });
});
