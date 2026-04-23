import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AlertDrawer } from "../components/AlertDrawer";
import type { Alert } from "../types";
import * as api from "../api";

vi.mock("../api", () => ({
  fetchPiholeSettings: vi.fn().mockResolvedValue({ configured: false, enabled: false, url: "" }),
  fetchLlmSettings: vi.fn().mockResolvedValue({ url: "", model: "", timeout: 90, max_tokens: 512 }),
  fetchFritzStatus: vi.fn().mockResolvedValue({ configured: false, connected: false, host_filter_available: false, model: "", firmware: "" }),
  blockDomain: vi.fn(),
  blockFritzDevice: vi.fn(),
  reEnrichAlert: vi.fn(),
}));

const ALERT: Alert = {
  id: "a1b2c3d4-0000-0000-0000-000000000042",
  timestamp: "2026-04-10T12:00:00Z",
  src_ip: "10.0.0.1",
  dst_ip: "8.8.8.8",
  src_port: 54321,
  dst_port: 443,
  proto: "TCP",
  signature: "ET SCAN Potential SSH Scan",
  signature_id: 2001219,
  category: "Attempted Information Leak",
  severity: "warning",
  enrichment_json: null,
  raw_json: { event_type: "alert", src_ip: "10.0.0.1" },
};

const ENRICHMENT = {
  summary: "Port scan detected from internal host",
  severity_reasoning: "Warning is appropriate for an internal scan with no confirmed compromise.",
  recommended_action: "Verify whether this device runs a legitimate network scanner.",
};

describe("AlertDrawer", () => {
  beforeEach(() => {
    vi.mocked(api.fetchPiholeSettings).mockResolvedValue({ configured: false, enabled: false, url: "" });
    vi.mocked(api.fetchLlmSettings).mockResolvedValue({ url: "", model: "", timeout: 90, max_tokens: 512 });
    vi.mocked(api.fetchFritzStatus).mockResolvedValue({ configured: false, connected: false, host_filter_available: false, model: "", firmware: "" });
  });

  it("renders nothing when alert is null", () => {
    const { container } = render(<AlertDrawer alert={null} onClose={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders alert details", () => {
    render(<AlertDrawer alert={ALERT} onClose={vi.fn()} />);
    expect(screen.getByText(/Alert #/)).toBeInTheDocument();
    expect(screen.getByText("10.0.0.1")).toBeInTheDocument();
    expect(screen.getByText("ET SCAN Potential SSH Scan")).toBeInTheDocument();
  });

  it("renders raw EVE JSON", () => {
    render(<AlertDrawer alert={ALERT} onClose={vi.fn()} />);
    expect(screen.getByText(/Raw EVE JSON/i)).toBeInTheDocument();
    expect(screen.getByText(/"event_type"/)).toBeInTheDocument();
  });

  it("calls onClose when × button is clicked", () => {
    const onClose = vi.fn();
    render(<AlertDrawer alert={ALERT} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: /close detail/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onClose when backdrop is clicked", () => {
    const onClose = vi.fn();
    render(<AlertDrawer alert={ALERT} onClose={onClose} />);
    fireEvent.click(document.querySelector('[aria-hidden="true"]')!);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onClose when Escape key is pressed", () => {
    const onClose = vi.fn();
    render(<AlertDrawer alert={ALERT} onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("does not call onClose on Escape when no alert shown", () => {
    const onClose = vi.fn();
    render(<AlertDrawer alert={null} onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("renders AI Analysis section when enrichment_json is present", () => {
    const enrichedAlert = { ...ALERT, enrichment_json: ENRICHMENT };
    render(<AlertDrawer alert={enrichedAlert} onClose={vi.fn()} />);
    expect(screen.getByText("AI Analysis")).toBeInTheDocument();
    expect(screen.getByText(ENRICHMENT.summary)).toBeInTheDocument();
    expect(screen.getByText(ENRICHMENT.severity_reasoning)).toBeInTheDocument();
    expect(screen.getByText(ENRICHMENT.recommended_action)).toBeInTheDocument();
  });

  it("does not render AI Analysis section when enrichment_json is null and LLM not configured", () => {
    render(<AlertDrawer alert={ALERT} onClose={vi.fn()} />);
    expect(screen.queryByText("AI Analysis")).not.toBeInTheDocument();
  });

  it("shows Request AI Analysis button when unenriched and LLM is configured", async () => {
    vi.mocked(api.fetchLlmSettings).mockResolvedValue({ url: "http://lm:1234/v1", model: "gemma", timeout: 90, max_tokens: 512 });
    render(<AlertDrawer alert={ALERT} onClose={vi.fn()} />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /request ai analysis/i })).toBeInTheDocument()
    );
  });

  it("does not show Request AI Analysis button when alert already has enrichment", async () => {
    vi.mocked(api.fetchLlmSettings).mockResolvedValue({ url: "http://lm:1234/v1", model: "gemma", timeout: 90, max_tokens: 512 });
    const enrichedAlert = { ...ALERT, enrichment_json: ENRICHMENT };
    render(<AlertDrawer alert={enrichedAlert} onClose={vi.fn()} />);
    await waitFor(() => expect(vi.mocked(api.fetchLlmSettings)).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /request ai analysis/i })).not.toBeInTheDocument();
  });

  it("calls reEnrichAlert and shows AI Analysis on success", async () => {
    vi.mocked(api.fetchLlmSettings).mockResolvedValue({ url: "http://lm:1234/v1", model: "gemma", timeout: 90, max_tokens: 512 });
    vi.mocked(api.reEnrichAlert).mockResolvedValue(ENRICHMENT);

    render(<AlertDrawer alert={ALERT} onClose={vi.fn()} />);
    const btn = await screen.findByRole("button", { name: /request ai analysis/i });
    fireEvent.click(btn);

    await waitFor(() =>
      expect(screen.getByText(ENRICHMENT.summary)).toBeInTheDocument()
    );
    expect(api.reEnrichAlert).toHaveBeenCalledWith(ALERT.id);
    expect(screen.queryByRole("button", { name: /request ai analysis/i })).not.toBeInTheDocument();
  });

  it("shows error message when reEnrichAlert fails", async () => {
    vi.mocked(api.fetchLlmSettings).mockResolvedValue({ url: "http://lm:1234/v1", model: "gemma", timeout: 90, max_tokens: 512 });
    vi.mocked(api.reEnrichAlert).mockRejectedValue(new Error("LLM timed out — try again"));

    render(<AlertDrawer alert={ALERT} onClose={vi.fn()} />);
    const btn = await screen.findByRole("button", { name: /request ai analysis/i });
    fireEvent.click(btn);

    await waitFor(() =>
      expect(screen.getByText("LLM timed out — try again")).toBeInTheDocument()
    );
    expect(screen.getByRole("button", { name: /request ai analysis/i })).toBeInTheDocument();
  });

  it("does not show Quarantine section when Fritz not configured", () => {
    render(<AlertDrawer alert={ALERT} onClose={vi.fn()} />);
    expect(screen.queryByText(/quarantine device/i)).not.toBeInTheDocument();
  });

  it("shows Quarantine section with src_ip pre-filled when Fritz is available", async () => {
    vi.mocked(api.fetchFritzStatus).mockResolvedValue({ configured: true, connected: true, host_filter_available: true, model: "FRITZ!Box 6660", firmware: "7.57" });
    render(<AlertDrawer alert={ALERT} onClose={vi.fn()} />);
    await screen.findByText(/quarantine device/i);
    expect(screen.getByLabelText(/device ip to quarantine/i)).toHaveValue("10.0.0.1");
  });

  it("calls blockFritzDevice with src_ip and shows success", async () => {
    vi.mocked(api.fetchFritzStatus).mockResolvedValue({ configured: true, connected: true, host_filter_available: true, model: "FRITZ!Box 6660", firmware: "7.57" });
    vi.mocked(api.blockFritzDevice).mockResolvedValue({ id: "x", blocked_at: "", ip: "10.0.0.1", hostname: null, comment: null });

    render(<AlertDrawer alert={ALERT} onClose={vi.fn()} />);
    await screen.findByRole("button", { name: /^quarantine$/i });
    fireEvent.click(screen.getByRole("button", { name: /^quarantine$/i }));

    await waitFor(() =>
      expect(screen.getByText(/quarantined — wan access cut off/i)).toBeInTheDocument()
    );
    expect(api.blockFritzDevice).toHaveBeenCalledWith("10.0.0.1", expect.stringContaining("alert"));
  });

  it("shows error when blockFritzDevice fails", async () => {
    vi.mocked(api.fetchFritzStatus).mockResolvedValue({ configured: true, connected: true, host_filter_available: true, model: "FRITZ!Box 6660", firmware: "7.57" });
    vi.mocked(api.blockFritzDevice).mockRejectedValue(new Error("Device not found"));

    render(<AlertDrawer alert={ALERT} onClose={vi.fn()} />);
    await screen.findByRole("button", { name: /^quarantine$/i });
    fireEvent.click(screen.getByRole("button", { name: /^quarantine$/i }));

    await waitFor(() =>
      expect(screen.getByText("Device not found")).toBeInTheDocument()
    );
  });
});
