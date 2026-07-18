import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import { apiConfig } from "@/config";
import { ApiError } from "@/shared/api/errors";
import { setNavigator, resetNavigation } from "@/shared/api/navigation";
import { apiClient, apiRequest } from "@/shared/api/client";

/** fetch 를 stub 하고 원하는 응답을 반환하도록 구성하는 헬퍼. */
function stubFetch(): ReturnType<typeof vi.fn> {
  const fn = vi.fn();
  vi.stubGlobal("fetch", fn);
  return fn;
}

interface FakeResponseInit {
  status: number;
  body?: unknown; // 객체 → JSON 직렬화, 문자열 → 그대로, undefined → 빈 본문
  blob?: Blob;
}

/** apiRequest 가 사용하는 최소 표면(ok/status/text/blob)만 갖춘 가짜 Response. */
function makeResponse(init: FakeResponseInit): Response {
  const { status } = init;
  const ok = status >= 200 && status < 300;
  const text =
    init.body === undefined
      ? ""
      : typeof init.body === "string"
        ? init.body
        : JSON.stringify(init.body);
  const fake = {
    ok,
    status,
    text: async () => text,
    blob: async () => init.blob ?? new Blob([text]),
  };
  return fake as unknown as Response;
}

/** jsdom 의 현재 경로를 제어(pathname + search). */
function setLocation(pathAndSearch: string): void {
  window.history.pushState({}, "", pathAndSearch);
}

/** fetch 호출 시 두 번째 인자(RequestInit)를 헤더까지 좁혀 반환. */
function lastInit(fn: ReturnType<typeof vi.fn>): RequestInit {
  const call = fn.mock.calls[0];
  return call[1] as RequestInit;
}

beforeEach(() => {
  resetNavigation();
  setLocation("/");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  resetNavigation();
});

describe("apiRequest / apiClient", () => {
  it("GET 200 json → parses typed body; fetch uses baseUrl+path and credentials:include", async () => {
    const fetchFn = stubFetch();
    fetchFn.mockResolvedValue(makeResponse({ status: 200, body: { id: "d1", title: "hi" } }));

    interface Doc {
      id: string;
      title: string;
    }
    const result = await apiClient.get<Doc>("/documents/d1");

    expect(result).toEqual({ id: "d1", title: "hi" });
    const [url] = fetchFn.mock.calls[0];
    expect(url).toBe(`${apiConfig.baseUrl}/documents/d1`);
    const init = lastInit(fetchFn);
    expect(init.credentials).toBe("include");
    expect(init.method).toBe("GET");
  });

  it("responseType:blob 200 → returns a Blob", async () => {
    const fetchFn = stubFetch();
    const payload = new Blob(["binary"], { type: "image/png" });
    fetchFn.mockResolvedValue(makeResponse({ status: 200, blob: payload }));

    const result = await apiClient.get<Blob>("/attachments/a1", { responseType: "blob" });

    expect(result).toBeInstanceOf(Blob);
  });

  it("204 empty json response → resolves to undefined", async () => {
    const fetchFn = stubFetch();
    fetchFn.mockResolvedValue(makeResponse({ status: 204 }));

    const result = await apiClient.del<undefined>("/documents/d1");

    expect(result).toBeUndefined();
  });

  it("POST with JSON body → sets Content-Type application/json + serialized body", async () => {
    const fetchFn = stubFetch();
    fetchFn.mockResolvedValue(makeResponse({ status: 201, body: { ok: true } }));

    await apiClient.post("/documents", { title: "new" });

    const init = lastInit(fetchFn);
    const headers = init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ title: "new" }));
    expect(init.method).toBe("POST");
  });

  it("POST with FormData body → does NOT set a JSON Content-Type and passes FormData as-is", async () => {
    const fetchFn = stubFetch();
    fetchFn.mockResolvedValue(makeResponse({ status: 201, body: { id: "a1" } }));

    const form = new FormData();
    form.append("file", new Blob(["x"]), "x.png");
    await apiClient.post("/attachments", form);

    const init = lastInit(fetchFn);
    const headers = (init.headers ?? {}) as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
    expect(init.body).toBe(form);
  });

  it("422 validation_error → throws ApiError with fieldErrors and does NOT redirect", async () => {
    const fetchFn = stubFetch();
    const nav = vi.fn();
    setNavigator(nav);
    fetchFn.mockResolvedValue(
      makeResponse({
        status: 422,
        body: {
          code: "validation_error",
          message: "invalid",
          field_errors: [{ field: "title", message: "required" }],
        },
      }),
    );

    await expect(apiClient.post("/documents", { title: "" })).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      fieldErrors: [{ field: "title", message: "required" }],
    });
    expect(nav).not.toHaveBeenCalled();
  });

  it("500 non-structured body → throws ApiError code internal and does NOT redirect", async () => {
    const fetchFn = stubFetch();
    const nav = vi.fn();
    setNavigator(nav);
    fetchFn.mockResolvedValue(
      makeResponse({ status: 500, body: "boom: stacktrace secret" }),
    );

    const err = await apiClient.get("/documents/d1").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("internal");
    expect((err as ApiError).message).not.toContain("stacktrace");
    expect(nav).not.toHaveBeenCalled();
  });

  it("401 with skipAuthRedirect:true → throws ApiError, navigator NOT called (bootstrap /auth/me)", async () => {
    const fetchFn = stubFetch();
    const nav = vi.fn();
    setNavigator(nav);
    setLocation("/documents/d1");
    fetchFn.mockResolvedValue(
      makeResponse({ status: 401, body: { code: "unauthenticated", message: "no session" } }),
    );

    await expect(
      apiClient.get("/auth/me", { skipAuthRedirect: true }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(nav).not.toHaveBeenCalled();
  });

  it("401 (no skip), not on login → calls navigator with /login?returnTo=<encoded path> AND throws", async () => {
    const fetchFn = stubFetch();
    const nav = vi.fn();
    setNavigator(nav);
    setLocation("/documents/d1?tab=history");
    fetchFn.mockResolvedValue(
      makeResponse({ status: 401, body: { code: "unauthenticated", message: "no session" } }),
    );

    await expect(apiRequest("/documents/d1")).rejects.toBeInstanceOf(ApiError);
    const encoded = encodeURIComponent("/documents/d1?tab=history");
    expect(nav).toHaveBeenCalledTimes(1);
    expect(nav).toHaveBeenCalledWith(`/login?returnTo=${encoded}`, { replace: true });
  });

  it("401 (no skip) while already on /login → navigator NOT called (loop prevention)", async () => {
    const fetchFn = stubFetch();
    const nav = vi.fn();
    setNavigator(nav);
    setLocation("/login?returnTo=%2Fdocuments");
    fetchFn.mockResolvedValue(
      makeResponse({ status: 401, body: { code: "unauthenticated", message: "no session" } }),
    );

    await expect(apiRequest("/workspaces")).rejects.toBeInstanceOf(ApiError);
    expect(nav).not.toHaveBeenCalled();
  });
});
