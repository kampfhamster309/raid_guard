import { useState } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { EditionSection } from "../components/EditionSection";
import { EditionContext } from "../edition";
import * as api from "../api";
import type { Edition } from "../types";

vi.mock("../api", () => ({
  updateEdition: vi.fn(),
  fetchGeoIpStatus: vi.fn(),
  requestGeoIpUpdate: vi.fn(),
}));

function Harness({ initial, isAdmin }: { initial: Edition; isAdmin: boolean }) {
  const [edition, setEdition] = useState<Edition>(initial);
  return (
    <EditionContext.Provider value={{ edition, setEdition }}>
      <EditionSection isAdmin={isAdmin} />
    </EditionContext.Provider>
  );
}

const GEO_OK = {
  available: true, city_db_updated: "2026-11-01T00:00:00Z", asn_db_updated: "2026-11-01T00:00:00Z",
  updating: false, last_error: null,
};

describe("EditionSection", () => {
  beforeEach(() => {
    vi.mocked(api.updateEdition).mockReset();
    vi.mocked(api.fetchGeoIpStatus).mockReset().mockResolvedValue(GEO_OK);
    vi.mocked(api.requestGeoIpUpdate).mockReset().mockResolvedValue({ ...GEO_OK, updating: true });
  });

  it("lets an admin switch to pro and shows GeoIP status", async () => {
    vi.mocked(api.updateEdition).mockResolvedValue("pro");
    render(<Harness initial="basic" isAdmin />);
    expect(screen.getByRole("radio", { name: "Basic" })).toHaveAttribute("aria-checked", "true");
    expect(api.fetchGeoIpStatus).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("radio", { name: "Pro" }));
    await waitFor(() => expect(screen.getByRole("radio", { name: "Pro" })).toHaveAttribute("aria-checked", "true"));
    expect(api.updateEdition).toHaveBeenCalledWith("pro");
    expect(await screen.findByText(/DB-IP Lite, offline/)).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("is read-only for viewers", () => {
    render(<Harness initial="basic" isAdmin={false} />);
    expect(screen.getByRole("radio", { name: "Pro" })).toBeDisabled();
  });

  it("shows a Pi-hole hint when the GeoIP download failed", async () => {
    vi.mocked(api.fetchGeoIpStatus).mockResolvedValue({
      ...GEO_OK, available: false, city_db_updated: null, asn_db_updated: null,
      last_error: "download of dbip-city-lite failed: Name or service not known",
    });
    render(<Harness initial="pro" isAdmin />);
    expect(await screen.findByText(/allow/)).toHaveTextContent("download.db-ip.com");
    fireEvent.click(screen.getByRole("button", { name: "Update now" }));
    await waitFor(() => expect(api.requestGeoIpUpdate).toHaveBeenCalled());
  });

  it("surfaces errors when switching fails", async () => {
    vi.mocked(api.updateEdition).mockRejectedValue(new Error("PUT failed: 403"));
    render(<Harness initial="basic" isAdmin />);
    fireEvent.click(screen.getByRole("radio", { name: "Pro" }));
    expect(await screen.findByText("PUT failed: 403")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Basic" })).toHaveAttribute("aria-checked", "true");
  });
});
