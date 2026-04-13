import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { BlocklistPage } from "../components/BlocklistPage";
import * as api from "../api";

vi.mock("../api");

const PIHOLE_CONFIGURED: api.PiholeSettings = { url: "http://pihole:80", enabled: true, configured: true };
const PIHOLE_NOT_CONFIGURED: api.PiholeSettings = { url: "", enabled: false, configured: false };
const PIHOLE_DISABLED: api.PiholeSettings = { url: "http://pihole:80", enabled: false, configured: true };

const FRITZ_READY: api.FritzStatus = {
  configured: true, connected: true, host_filter_available: true,
  model: "FRITZ!Box 6660 Cable", firmware: "8.00",
};
const FRITZ_NOT_CONFIGURED: api.FritzStatus = {
  configured: false, connected: false, host_filter_available: false, model: "", firmware: "",
};
const FRITZ_UNREACHABLE: api.FritzStatus = {
  configured: true, connected: false, host_filter_available: false, model: "", firmware: "",
};
const FRITZ_NO_HOSTFILTER: api.FritzStatus = {
  configured: true, connected: true, host_filter_available: false, model: "FRITZ!Box 7520", firmware: "7.00",
};

const DOMAIN_A: api.BlockedDomain = { domain: "malware.example.com", comment: "Blocked by raid_guard", added_at: 1712325600, enabled: true };
const DOMAIN_B: api.BlockedDomain = { domain: "tracker.evil.org", comment: null, added_at: 1712325700, enabled: true };

const DEVICE_A: api.FritzBlockedDevice = {
  id: "aaa-111", blocked_at: "2026-04-13T00:00:00+00:00",
  ip: "192.168.178.50", hostname: "evil-iot", comment: "C2 beacon",
};
const DEVICE_B: api.FritzBlockedDevice = {
  id: "bbb-222", blocked_at: "2026-04-13T01:00:00+00:00",
  ip: "192.168.178.77", hostname: null, comment: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.fetchPiholeSettings).mockResolvedValue(PIHOLE_CONFIGURED);
  vi.mocked(api.fetchBlocklist).mockResolvedValue([DOMAIN_A, DOMAIN_B]);
  vi.mocked(api.blockDomain).mockResolvedValue(DOMAIN_A);
  vi.mocked(api.unblockDomain).mockResolvedValue(undefined);
  vi.mocked(api.fetchFritzStatus).mockResolvedValue(FRITZ_READY);
  vi.mocked(api.fetchFritzBlocked).mockResolvedValue([DEVICE_A, DEVICE_B]);
  vi.mocked(api.blockFritzDevice).mockResolvedValue(DEVICE_A);
  vi.mocked(api.unblockFritzDevice).mockResolvedValue(undefined);
});

// ── DNS Sinkhole — not configured ─────────────────────────────────────────────

describe("BlocklistPage — DNS Sinkhole — not configured", () => {
  it("shows not-configured message when Pi-hole is not configured", async () => {
    vi.mocked(api.fetchPiholeSettings).mockResolvedValue(PIHOLE_NOT_CONFIGURED);
    render(<BlocklistPage />);
    await screen.findByText(/not configured or disabled/i);
  });

  it("shows not-configured message when Pi-hole is disabled", async () => {
    vi.mocked(api.fetchPiholeSettings).mockResolvedValue(PIHOLE_DISABLED);
    render(<BlocklistPage />);
    await screen.findByText(/not configured or disabled/i);
  });

  it("does not load blocklist when Pi-hole not configured", async () => {
    vi.mocked(api.fetchPiholeSettings).mockResolvedValue(PIHOLE_NOT_CONFIGURED);
    render(<BlocklistPage />);
    await screen.findByText(/not configured or disabled/i);
    expect(api.fetchBlocklist).not.toHaveBeenCalled();
  });
});

// ── DNS Sinkhole — blocklist ───────────────────────────────────────────────────

describe("BlocklistPage — DNS Sinkhole — blocklist", () => {
  it("renders blocked domain names", async () => {
    render(<BlocklistPage />);
    await screen.findByText("malware.example.com");
    expect(screen.getByText("tracker.evil.org")).toBeInTheDocument();
  });

  it("shows empty state when no domains blocked", async () => {
    vi.mocked(api.fetchBlocklist).mockResolvedValue([]);
    render(<BlocklistPage />);
    await screen.findByText(/no domains blocked yet/i);
  });

  it("shows error when blocklist fetch fails", async () => {
    vi.mocked(api.fetchBlocklist).mockRejectedValue(new Error("Connection refused"));
    render(<BlocklistPage />);
    await screen.findByText("Connection refused");
  });
});

// ── DNS Sinkhole — manual block ───────────────────────────────────────────────

describe("BlocklistPage — DNS Sinkhole — manual block", () => {
  it("renders domain block input", async () => {
    render(<BlocklistPage />);
    await screen.findByText("malware.example.com");
    expect(screen.getByRole("textbox", { name: /domain to block/i })).toBeInTheDocument();
  });

  it("calls blockDomain and refreshes list on submit", async () => {
    render(<BlocklistPage />);
    await screen.findByText("malware.example.com");

    const input = screen.getByRole("textbox", { name: /domain to block/i });
    fireEvent.change(input, { target: { value: "new.evil.com" } });
    fireEvent.click(screen.getByRole("button", { name: /^block$/i }));

    await waitFor(() => expect(api.blockDomain).toHaveBeenCalledWith("new.evil.com"));
    expect(api.fetchBlocklist).toHaveBeenCalledTimes(2);
  });

  it("shows error when domain block fails", async () => {
    vi.mocked(api.blockDomain).mockRejectedValue(new Error("Pi-hole unreachable"));
    render(<BlocklistPage />);
    await screen.findByText("malware.example.com");

    fireEvent.change(screen.getByRole("textbox", { name: /domain to block/i }), { target: { value: "evil.com" } });
    fireEvent.click(screen.getByRole("button", { name: /^block$/i }));

    await screen.findByText("Pi-hole unreachable");
  });

  it("domain Block button is disabled when input is empty", async () => {
    render(<BlocklistPage />);
    await screen.findByText("malware.example.com");
    expect(screen.getByRole("button", { name: /^block$/i })).toBeDisabled();
  });
});

// ── DNS Sinkhole — unblock ────────────────────────────────────────────────────

describe("BlocklistPage — DNS Sinkhole — unblock", () => {
  it("renders Unblock buttons for each domain", async () => {
    render(<BlocklistPage />);
    await screen.findByText("malware.example.com");
    expect(screen.getAllByRole("button", { name: /^unblock /i }).length).toBeGreaterThanOrEqual(2);
  });

  it("removes domain from list after unblock", async () => {
    render(<BlocklistPage />);
    await screen.findByText("malware.example.com");
    fireEvent.click(screen.getByRole("button", { name: /unblock malware.example.com/i }));
    await waitFor(() => expect(screen.queryByText("malware.example.com")).not.toBeInTheDocument());
    expect(api.unblockDomain).toHaveBeenCalledWith("malware.example.com");
  });
});

// ── Device Quarantine — not configured ───────────────────────────────────────

describe("BlocklistPage — Device Quarantine — not configured", () => {
  it("shows not-configured message when Fritzbox not configured", async () => {
    vi.mocked(api.fetchFritzStatus).mockResolvedValue(FRITZ_NOT_CONFIGURED);
    render(<BlocklistPage />);
    await screen.findByText(/fritzbox is not configured/i);
  });

  it("shows unreachable message when Fritzbox is configured but offline", async () => {
    vi.mocked(api.fetchFritzStatus).mockResolvedValue(FRITZ_UNREACHABLE);
    render(<BlocklistPage />);
    await screen.findByText(/cannot reach fritzbox/i);
  });

  it("shows service-unavailable message when HostFilter not supported", async () => {
    vi.mocked(api.fetchFritzStatus).mockResolvedValue(FRITZ_NO_HOSTFILTER);
    render(<BlocklistPage />);
    await screen.findByText(/x_avm-de_hostfilter service is not available/i);
  });

  it("does not load device list when Fritzbox not configured", async () => {
    vi.mocked(api.fetchFritzStatus).mockResolvedValue(FRITZ_NOT_CONFIGURED);
    render(<BlocklistPage />);
    await screen.findByText(/fritzbox is not configured/i);
    expect(api.fetchFritzBlocked).not.toHaveBeenCalled();
  });
});

// ── Device Quarantine — list ──────────────────────────────────────────────────

describe("BlocklistPage — Device Quarantine — list", () => {
  it("renders quarantined device IPs", async () => {
    render(<BlocklistPage />);
    await screen.findByText("192.168.178.50");
    expect(screen.getByText("192.168.178.77")).toBeInTheDocument();
  });

  it("shows hostname when available, dash when null", async () => {
    render(<BlocklistPage />);
    await screen.findByText("evil-iot");
  });

  it("shows empty state when no devices quarantined", async () => {
    vi.mocked(api.fetchFritzBlocked).mockResolvedValue([]);
    render(<BlocklistPage />);
    await screen.findByText(/no devices quarantined/i);
  });

  it("shows model name in section subtitle", async () => {
    render(<BlocklistPage />);
    await screen.findByText(/FRITZ!Box 6660 Cable/);
  });

  it("shows error when device list fetch fails", async () => {
    vi.mocked(api.fetchFritzBlocked).mockRejectedValue(new Error("Fritzbox timeout"));
    render(<BlocklistPage />);
    await screen.findByText("Fritzbox timeout");
  });
});

// ── Device Quarantine — quarantine ────────────────────────────────────────────

describe("BlocklistPage — Device Quarantine — quarantine", () => {
  it("renders IP quarantine input", async () => {
    render(<BlocklistPage />);
    await screen.findByText("192.168.178.50");
    expect(screen.getByRole("textbox", { name: /ip to quarantine/i })).toBeInTheDocument();
  });

  it("calls blockFritzDevice on submit", async () => {
    render(<BlocklistPage />);
    await screen.findByText("192.168.178.50");

    fireEvent.change(screen.getByRole("textbox", { name: /ip to quarantine/i }), { target: { value: "192.168.178.99" } });
    fireEvent.click(screen.getByRole("button", { name: /^quarantine$/i }));

    await waitFor(() => expect(api.blockFritzDevice).toHaveBeenCalledWith("192.168.178.99"));
  });

  it("shows error when quarantine fails", async () => {
    vi.mocked(api.blockFritzDevice).mockRejectedValue(new Error("Not in host table"));
    render(<BlocklistPage />);
    await screen.findByText("192.168.178.50");

    fireEvent.change(screen.getByRole("textbox", { name: /ip to quarantine/i }), { target: { value: "192.168.178.99" } });
    fireEvent.click(screen.getByRole("button", { name: /^quarantine$/i }));

    await screen.findByText("Not in host table");
  });

  it("Quarantine button is disabled when input is empty", async () => {
    render(<BlocklistPage />);
    await screen.findByText("192.168.178.50");
    expect(screen.getByRole("button", { name: /^quarantine$/i })).toBeDisabled();
  });
});

// ── Device Quarantine — unquarantine ─────────────────────────────────────────

describe("BlocklistPage — Device Quarantine — unquarantine", () => {
  it("renders Unquarantine buttons for each device", async () => {
    render(<BlocklistPage />);
    await screen.findByText("192.168.178.50");
    expect(screen.getAllByRole("button", { name: /^unquarantine /i }).length).toBe(2);
  });

  it("removes device from list after unquarantine", async () => {
    render(<BlocklistPage />);
    await screen.findByText("192.168.178.50");
    fireEvent.click(screen.getByRole("button", { name: /unquarantine 192.168.178.50/i }));
    await waitFor(() => expect(screen.queryByText("192.168.178.50")).not.toBeInTheDocument());
    expect(api.unblockFritzDevice).toHaveBeenCalledWith("192.168.178.50");
  });
});
