import { renderHook, waitFor } from "@testing-library/react";
import { useAlerts } from "../hooks/useAlerts";
import { fetchAlerts } from "../api";
import type { Severity } from "../types";

vi.mock("../api", () => ({ fetchAlerts: vi.fn() }));
vi.mock("../hooks/useWebSocket", () => ({ useWebSocket: () => "connected" }));

const mockFetch = vi.mocked(fetchAlerts);

describe("useAlerts", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValue([]);
  });

  it("asks the server for the selected severities and refetches when they change", async () => {
    const { rerender } = renderHook(
      ({ severities }: { severities: Severity[] }) => useAlerts({ severities, searchText: "" }),
      { initialProps: { severities: ["warning", "critical"] as Severity[] } }
    );
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    expect(mockFetch).toHaveBeenLastCalledWith({ limit: 100, severity: ["critical", "warning"] });

    rerender({ severities: ["critical", "warning"] }); // same set, new array: no refetch
    rerender({ severities: ["critical"] });
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    expect(mockFetch).toHaveBeenLastCalledWith({ limit: 100, severity: ["critical"] });
  });

  it("shows nothing and skips the request when no severity is selected", async () => {
    const { result } = renderHook(() => useAlerts({ severities: [], searchText: "" }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(mockFetch).not.toHaveBeenCalled();
    expect(result.current.filteredAlerts).toEqual([]);
  });
});
