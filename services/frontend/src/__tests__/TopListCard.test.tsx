import { render, screen } from "@testing-library/react";
import { TopListCard } from "../components/TopListCard";
import type { TopItem } from "../types";

const ITEMS: TopItem[] = [
  { name: "192.168.1.1", count: 50 },
  { name: "10.0.0.5", count: 20 },
];

describe("TopListCard", () => {
  it("renders the title", () => {
    render(<TopListCard title="Top source IPs" items={ITEMS} />);
    expect(screen.getByText("Top source IPs")).toBeInTheDocument();
  });

  it("renders item names and counts", () => {
    render(<TopListCard title="Top source IPs" items={ITEMS} />);
    expect(screen.getByText("192.168.1.1")).toBeInTheDocument();
    expect(screen.getByText("50")).toBeInTheDocument();
    expect(screen.getByText("10.0.0.5")).toBeInTheDocument();
    expect(screen.getByText("20")).toBeInTheDocument();
  });

  it("shows empty message when no items", () => {
    render(<TopListCard title="Top IPs" items={[]} emptyMessage="No data yet" />);
    expect(screen.getByText("No data yet")).toBeInTheDocument();
  });
});
