import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setToken, testLlm } from "../api";

function mockFetchError(status: number, body: unknown) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: false,
    status,
    json: async () => body,
  }));
}

describe("authFetch error surfacing", () => {
  beforeEach(() => setToken("fake-jwt"));
  afterEach(() => vi.unstubAllGlobals());

  it("includes the backend detail in the thrown error", async () => {
    mockFetchError(502, { detail: "Error code: 400 — temperature must be 0 with response_format" });
    await expect(testLlm()).rejects.toThrow(
      "POST /api/settings/llm/test failed: 502 — Error code: 400 — temperature must be 0 with response_format"
    );
  });

  it("falls back to status-only message for non-JSON error bodies", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("not json");
      },
    }));
    await expect(testLlm()).rejects.toThrow("POST /api/settings/llm/test failed: 500");
  });

  it("falls back to status-only message when detail is missing", async () => {
    mockFetchError(502, { error: "something" });
    await expect(testLlm()).rejects.toThrow("POST /api/settings/llm/test failed: 502");
  });
});
