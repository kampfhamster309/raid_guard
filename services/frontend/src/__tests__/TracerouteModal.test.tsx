import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TracerouteModal } from "../components/TracerouteModal";
import * as api from "../api";
import type { TracerouteResult } from "../types";

vi.mock("../api", () => ({ runTraceroute: vi.fn() }));
vi.mock("../components/TracerouteMap", () => ({
  default: ({ hops }: { hops: unknown[] }) => <div data-testid="map">{hops.length} hops on map</div>,
}));

const RESULT: TracerouteResult = {
  target: "8.8.8.8",
  reached: true,
  trailing_timeouts: 0,
  geo_available: true,
  duration_ms: 4200,
  hops: [
    { hop: 1, ip: "192.168.178.1", hostname: "fritz.box", rtt_ms: 0.5, private: true, geo: null, asn: null },
    { hop: 2, ip: null, hostname: null, rtt_ms: null, private: false, geo: null, asn: null },
    {
      hop: 3, ip: "8.8.8.8", hostname: "dns.google", rtt_ms: 12.3, private: false,
      geo: { lat: 37.4, lon: -122.1, city: "Mountain View", region: "California", country: "United States", country_code: "US" },
      asn: { number: 15169, org: "Google LLC" },
    },
  ],
};

describe("TracerouteModal", () => {
  beforeEach(() => vi.mocked(api.runTraceroute).mockReset());

  it("runs a trace on open and renders the hop path", async () => {
    vi.mocked(api.runTraceroute).mockResolvedValue(RESULT);
    render(<TracerouteModal target="8.8.8.8" onClose={() => {}} />);

    expect(api.runTraceroute).toHaveBeenCalledWith("8.8.8.8");
    expect(await screen.findByText("Reached in 3 hops · 4.2 s")).toBeInTheDocument();
    expect(screen.getByText("fritz.box")).toBeInTheDocument();
    expect(screen.getByText("Private network")).toBeInTheDocument();
    expect(screen.getByText("No reply")).toBeInTheDocument();
    expect(screen.getByText(/AS15169 Google LLC · Mountain View, California, US/)).toBeInTheDocument();
    expect(await screen.findByTestId("map")).toHaveTextContent("3 hops on map");
    expect(screen.getByRole("link", { name: /DB-IP/ })).toHaveAttribute("href", "https://db-ip.com");
  });

  it("explains unreached destinations and missing GeoIP data", async () => {
    vi.mocked(api.runTraceroute).mockResolvedValue({
      ...RESULT, reached: false, trailing_timeouts: 4, geo_available: false, hops: RESULT.hops.slice(0, 1),
    });
    render(<TracerouteModal target="8.8.8.8" onClose={() => {}} />);
    expect(await screen.findByText(/Destination did not answer — 1 of 5 hops replied, last 4 timed out/)).toBeInTheDocument();
    expect(screen.getByText(/GeoIP databases aren't downloaded yet/)).toBeInTheDocument();
  });

  it("shows errors and can run again", async () => {
    vi.mocked(api.runTraceroute).mockRejectedValueOnce(new Error("POST /api/pro/traceroute failed: 502 — boom"));
    render(<TracerouteModal target="8.8.8.8" onClose={() => {}} />);
    expect(await screen.findByText(/502 — boom/)).toBeInTheDocument();

    vi.mocked(api.runTraceroute).mockResolvedValue(RESULT);
    fireEvent.click(screen.getByRole("button", { name: "Run again" }));
    await waitFor(() => expect(api.runTraceroute).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("dns.google")).toBeInTheDocument();
  });

  it("closes on Escape without propagating to the drawer", async () => {
    vi.mocked(api.runTraceroute).mockResolvedValue(RESULT);
    const onClose = vi.fn();
    const drawerHandler = vi.fn();
    document.addEventListener("keydown", drawerHandler);
    render(<TracerouteModal target="8.8.8.8" onClose={onClose} />);
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
    expect(drawerHandler).not.toHaveBeenCalled();
    document.removeEventListener("keydown", drawerHandler);
  });
});
