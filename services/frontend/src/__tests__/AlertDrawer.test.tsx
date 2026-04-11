import { render, screen, fireEvent } from "@testing-library/react";
import { AlertDrawer } from "../components/AlertDrawer";
import type { Alert } from "../types";

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

  it("does not render AI Analysis section when enrichment_json is null", () => {
    render(<AlertDrawer alert={ALERT} onClose={vi.fn()} />);
    expect(screen.queryByText("AI Analysis")).not.toBeInTheDocument();
  });
});
