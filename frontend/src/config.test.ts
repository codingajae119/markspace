import { describe, it, expect, afterEach, vi } from "vitest";

import { apiConfig } from "@/config";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("apiConfig", () => {
  it("exposes a non-empty string baseUrl (single config source)", () => {
    expect(typeof apiConfig.baseUrl).toBe("string");
    expect(apiConfig.baseUrl.length).toBeGreaterThan(0);
  });

  it("falls back to a sensible default when VITE_API_BASE_URL is unset", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "");
    vi.resetModules();
    const { apiConfig: reloaded } = await import("@/config");
    expect(reloaded.baseUrl).toBe("http://localhost:8000");
  });

  it("reflects the single VITE_API_BASE_URL env var when set", async () => {
    vi.stubEnv("VITE_API_BASE_URL", "https://api.example.test");
    vi.resetModules();
    const { apiConfig: reloaded } = await import("@/config");
    expect(reloaded.baseUrl).toBe("https://api.example.test");
  });
});
