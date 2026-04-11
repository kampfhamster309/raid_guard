import { render, screen, fireEvent } from "@testing-library/react";
import { AlertTable } from "../components/AlertTable";
import type { Alert } from "../types";

const ALERT: Alert = {
  id: "a1b2c3d4-0000-0000-0000-000000000001",
  timestamp: "2026-04-10T12:00:00Z",
  src_ip: "192.168.1.5",
  dst_ip: "1.1.1.1",
  src_port: 12345,
  dst_port: 53,
  proto: "UDP",
  signature: "ET DNS Query",
  signature_id: 100001,
  category: "DNS",
  severity: "info",
  raw_json: null,
};

describe("AlertTable", () => {
  it("shows empty state message when no alerts", () => {
    render(<AlertTable alerts={[]} onSelect={vi.fn()} />);
    expect(screen.getByText(/no alerts match/i)).toBeInTheDocument();
  });

  it("renders alert rows", () => {
    render(<AlertTable alerts={[ALERT]} onSelect={vi.fn()} />);
    expect(screen.getByText("192.168.1.5")).toBeInTheDocument();
    expect(screen.getByText("ET DNS Query")).toBeInTheDocument();
  });

  it("calls onSelect when a row is clicked", () => {
    const onSelect = vi.fn();
    render(<AlertTable alerts={[ALERT]} onSelect={onSelect} />);
    fireEvent.click(screen.getByText("192.168.1.5"));
    expect(onSelect).toHaveBeenCalledWith(ALERT);
  });
});
