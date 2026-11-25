import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterBar } from "../components/FilterBar";
import type { Severity } from "../types";

const noop = () => undefined;

function renderBar(props: Partial<Parameters<typeof FilterBar>[0]> = {}) {
  return render(
    <FilterBar
      severityFilter="all"
      onSeverityChange={noop}
      shownSeverities={["critical", "warning"] as Severity[]}
      onShownSeveritiesChange={noop}
      searchText=""
      onSearchChange={noop}
      {...props}
    />
  );
}

describe("FilterBar", () => {
  it("renders severity buttons", () => {
    renderBar();
    for (const name of ["All", "Critical", "Warning", "Info"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("calls onSeverityChange when a button is clicked", async () => {
    const user = userEvent.setup();
    const handler = vi.fn();
    renderBar({ onSeverityChange: handler });
    await user.click(screen.getByRole("button", { name: "Critical" }));
    expect(handler).toHaveBeenCalledWith("critical");
  });

  it("calls onSearchChange when text is typed", async () => {
    const user = userEvent.setup();
    const handler = vi.fn();
    renderBar({ onSearchChange: handler });
    await user.type(screen.getByRole("searchbox"), "1.2.3");
    expect(handler).toHaveBeenCalled();
  });

  it("shows level checkboxes on the All view reflecting shownSeverities", () => {
    renderBar();
    expect(screen.getByRole("checkbox", { name: "Critical" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Warning" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Info" })).not.toBeChecked();
  });

  it("toggles a level on and off", async () => {
    const user = userEvent.setup();
    const handler = vi.fn();
    renderBar({ onShownSeveritiesChange: handler });
    await user.click(screen.getByRole("checkbox", { name: "Info" }));
    expect(handler).toHaveBeenLastCalledWith(["critical", "warning", "info"]);
    await user.click(screen.getByRole("checkbox", { name: "Warning" }));
    expect(handler).toHaveBeenLastCalledWith(["critical"]);
  });

  it("hides the checkboxes on a single-level view", () => {
    renderBar({ severityFilter: "critical" });
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});
