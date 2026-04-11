import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterBar } from "../components/FilterBar";

const noop = () => undefined;

describe("FilterBar", () => {
  it("renders severity buttons", () => {
    render(
      <FilterBar
        severityFilter="all"
        onSeverityChange={noop}
        searchText=""
        onSearchChange={noop}
      />
    );
    expect(screen.getByText("All")).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("Warning")).toBeInTheDocument();
    expect(screen.getByText("Info")).toBeInTheDocument();
  });

  it("calls onSeverityChange when a button is clicked", async () => {
    const user = userEvent.setup();
    const handler = vi.fn();
    render(
      <FilterBar
        severityFilter="all"
        onSeverityChange={handler}
        searchText=""
        onSearchChange={noop}
      />
    );
    await user.click(screen.getByText("Critical"));
    expect(handler).toHaveBeenCalledWith("critical");
  });

  it("calls onSearchChange when text is typed", async () => {
    const user = userEvent.setup();
    const handler = vi.fn();
    render(
      <FilterBar
        severityFilter="all"
        onSeverityChange={noop}
        searchText=""
        onSearchChange={handler}
      />
    );
    await user.type(screen.getByRole("searchbox"), "1.2.3");
    expect(handler).toHaveBeenCalled();
  });
});
