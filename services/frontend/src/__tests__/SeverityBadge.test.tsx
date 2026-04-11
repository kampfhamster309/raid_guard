import { render, screen } from "@testing-library/react";
import { SeverityBadge } from "../components/SeverityBadge";

describe("SeverityBadge", () => {
  it("renders 'critical' label", () => {
    render(<SeverityBadge severity="critical" />);
    expect(screen.getByText("critical")).toBeInTheDocument();
  });

  it("renders 'warning' label", () => {
    render(<SeverityBadge severity="warning" />);
    expect(screen.getByText("warning")).toBeInTheDocument();
  });

  it("renders 'info' label", () => {
    render(<SeverityBadge severity="info" />);
    expect(screen.getByText("info")).toBeInTheDocument();
  });
});
