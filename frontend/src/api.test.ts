import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, post, token, validateAndSaveToken } from "./api";

const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const rejected = () =>
  response(
    { error: { message: "Invalid or revoked access credential." } },
    401,
  );
const nativeFetch = globalThis.fetch;

beforeEach(() => sessionStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

describe("saved credential recovery", () => {
  it("restores an open local dashboard after the saved token is rejected", async () => {
    sessionStorage.setItem("recallops-token", "revoked");
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(rejected())
      .mockResolvedValueOnce(
        response({ mode: "development", auth_required: false }),
      )
      .mockResolvedValueOnce(response({ active_incidents: 2 }));
    vi.stubGlobal("fetch", fetch);
    await expect(api("/dashboard?mode=replay")).resolves.toEqual({
      active_incidents: 2,
    });
    expect(token()).toBe("");
    expect(fetch.mock.calls[2][1].headers.has("Authorization")).toBe(false);
  });

  it.each([
    { mode: "production", auth_required: true },
    { mode: "development", auth_required: true },
    { mode: "public_demo", auth_required: false },
  ])(
    "never falls back to anonymous access for $mode / auth_required=$auth_required",
    async (config) => {
      sessionStorage.setItem("recallops-token", "revoked");
      const fetch = vi
        .fn()
        .mockResolvedValueOnce(rejected())
        .mockResolvedValueOnce(response(config));
      vi.stubGlobal("fetch", fetch);
      await expect(api("/dashboard")).rejects.toMatchObject({ status: 401 });
      expect(token()).toBe("revoked");
      expect(fetch).toHaveBeenCalledTimes(2);
    },
  );

  it("never repeats a rejected write", async () => {
    sessionStorage.setItem("recallops-token", "revoked");
    const fetch = vi.fn().mockResolvedValueOnce(rejected());
    vi.stubGlobal("fetch", fetch);
    await expect(post("/investigator/demo")).rejects.toBeInstanceOf(ApiError);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(token()).toBe("revoked");
  });

  it("does not clear a newly saved token when an older request fails", async () => {
    sessionStorage.setItem("recallops-token", "old-token");
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(rejected())
      .mockImplementationOnce(async () => {
        sessionStorage.setItem("recallops-token", "new-token");
        return response({ mode: "development", auth_required: false });
      });
    vi.stubGlobal("fetch", fetch);
    await expect(api("/dashboard")).rejects.toMatchObject({ status: 401 });
    expect(token()).toBe("new-token");
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("preserves the existing credential if proposed replacement is invalid", async () => {
    sessionStorage.setItem("recallops-token", "working-token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(rejected()));
    await expect(validateAndSaveToken("wrong-token")).rejects.toMatchObject({
      status: 401,
    });
    expect(token()).toBe("working-token");
  });

  it("normalizes and validates a pasted bearer credential before saving", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response([]));
    vi.stubGlobal("fetch", fetch);
    await validateAndSaveToken("  Bearer valid-token  ");
    expect(fetch.mock.calls[0][1].headers.Authorization).toBe(
      "Bearer valid-token",
    );
    expect(token()).toBe("valid-token");
  });

  it("does not discard a token for permission errors", async () => {
    sessionStorage.setItem("recallops-token", "viewer-token");
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        response({ error: { message: "Forbidden" } }, 403),
      );
    vi.stubGlobal("fetch", fetch);
    await expect(api("/operations/credentials")).rejects.toMatchObject({
      status: 403,
    });
    expect(token()).toBe("viewer-token");
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

// Optional HTTP integration check, still without launching or controlling a browser.
const liveUrl = import.meta.env.VITE_RECALLOPS_TEST_URL;
describe.skipIf(!liveUrl)(
  "running local application's credential recovery",
  () => {
    it("recovers a real 401 and reads the running dashboard", async () => {
      sessionStorage.setItem(
        "recallops-token",
        "deliberately-invalid-http-regression",
      );
      vi.stubGlobal("fetch", (input: string, init?: RequestInit) =>
        nativeFetch(new URL(input, liveUrl), init),
      );
      const result = await api<{ active_incidents: number }>(
        "/dashboard?mode=replay",
      );
      expect(result.active_incidents).toBeTypeOf("number");
      expect(token()).toBe("");
    });
    it("rejects an invalid proposed token before saving it", async () => {
      vi.stubGlobal("fetch", (input: string, init?: RequestInit) =>
        nativeFetch(new URL(input, liveUrl), init),
      );
      await expect(
        validateAndSaveToken("deliberately-invalid-http-regression"),
      ).rejects.toMatchObject({ status: 401 });
      expect(token()).toBe("");
    });
  },
);
