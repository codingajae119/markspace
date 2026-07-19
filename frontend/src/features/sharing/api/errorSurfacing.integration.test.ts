/**
 * 오류 표면화·공개 무리다이렉트 통합 검증 (task 5.2, Req 8.1·8.2·8.3).
 *
 * 실제 `shareApi`(`./shareApi`)·`publicApi`(`./publicApi`)가 실제 s16 `apiClient`(`client.ts`)
 * 를 그대로 통과한다는 전제에서, 전역 401 인터셉터·비-401 오류 전파·공개 경로 무리다이렉트를
 * 통합 수준에서 검증한다. apiClient 는 목(mock)하지 않고, 네트워크 경계(`fetch`)만 stub 하며
 * 네비게이션 seam(`navigation.ts`)에는 spy navigator 를 주입한다.
 *
 * 관찰 대상:
 * - 관리(shareApi) 401 → navigator 호출(로그인 리다이렉트) + `ApiError`(status 401) reject (Req 8.1)
 * - 관리 403/404/409 → `ApiError`(status·code 보존) reject, navigator 미호출(비-401 전파) (Req 8.2)
 * - 공개(publicApi) 401 → navigator 미호출(skipAuthRedirect) + `ApiError` reject (Req 8.3)
 * - 공개 404 → `ApiError`(status 404) reject, navigator 미호출(무효 경로 전파만)
 *
 * jsdom 기본 경로는 `/`(로그인 경로 아님)이므로 401 리다이렉트 판정이 정상 동작한다.
 * (로그인 경로에서만 루프 방지로 리다이렉트가 억제된다 — client.ts `isOnLoginRoute`.)
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import { ApiError } from "@/shared/api/errors";
import { setNavigator, resetNavigation } from "@/shared/api/navigation";

import { shareApi } from "./shareApi";
import { publicApi } from "./publicApi";

/** fetch 를 stub 하고 원하는 응답을 반환하도록 구성하는 헬퍼(client.test.ts 관용구). */
function stubFetch(): ReturnType<typeof vi.fn> {
  const fn = vi.fn();
  vi.stubGlobal("fetch", fn);
  return fn;
}

interface FakeResponseInit {
  status: number;
  body?: unknown; // 객체 → JSON 직렬화, 문자열 → 그대로, undefined → 빈 본문
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
    blob: async () => new Blob([text]),
  };
  return fake as unknown as Response;
}

beforeEach(() => {
  resetNavigation();
  // jsdom 기본 경로(/)를 명시적으로 복원해 로그인 경로 오염이 없도록 한다(리다이렉트 판정 결정성).
  window.history.pushState({}, "", "/");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  resetNavigation();
});

describe("sharing 오류 표면화 · 공개 무리다이렉트 (통합)", () => {
  it("shareApi.issueLink 401(관리) → navigator 호출(로그인 리다이렉트) + ApiError(401) reject (Req 8.1)", async () => {
    const fetchFn = stubFetch();
    const nav = vi.fn();
    setNavigator(nav);
    fetchFn.mockResolvedValue(
      makeResponse({
        status: 401,
        body: { code: "unauthenticated", message: "no session" },
      }),
    );

    const err = await shareApi.issueLink(1).catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(401);
    // shareApi 는 skipAuthRedirect 를 전달하지 않으므로 전역 401 인터셉터가 발동한다.
    expect(nav).toHaveBeenCalledTimes(1);
  });

  it.each([
    { status: 403, code: "forbidden", message: "no access" },
    { status: 404, code: "not_found", message: "missing" },
    { status: 409, code: "conflict", message: "stale" },
  ])(
    "shareApi.issueLink $status(관리) → ApiError(status·code 보존) reject, navigator 미호출 (Req 8.2)",
    async ({ status, code, message }) => {
      const fetchFn = stubFetch();
      const nav = vi.fn();
      setNavigator(nav);
      fetchFn.mockResolvedValue(makeResponse({ status, body: { code, message } }));

      const err = await shareApi.issueLink(1).catch((e: unknown) => e);

      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(status);
      expect((err as ApiError).code).toBe(code);
      // 401 만 리다이렉트한다 — 비-401 오류는 하위 ErrorMessage 소비용으로 전파만 된다.
      expect(nav).not.toHaveBeenCalled();
    },
  );

  it.each([
    { status: 403, code: "forbidden", message: "no access" },
    { status: 404, code: "not_found", message: "missing" },
    { status: 409, code: "conflict", message: "stale" },
  ])(
    "shareApi.toggleLink $status(관리) → ApiError(status·code 보존) reject, navigator 미호출 (Req 8.2)",
    async ({ status, code, message }) => {
      const fetchFn = stubFetch();
      const nav = vi.fn();
      setNavigator(nav);
      fetchFn.mockResolvedValue(makeResponse({ status, body: { code, message } }));

      const err = await shareApi
        .toggleLink(1, { is_enabled: false })
        .catch((e: unknown) => e);

      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(status);
      expect((err as ApiError).code).toBe(code);
      expect(nav).not.toHaveBeenCalled();
    },
  );

  it("publicApi.getPublicDocument 401(공개) → navigator 미호출(skipAuthRedirect) + ApiError reject (Req 8.3)", async () => {
    const fetchFn = stubFetch();
    const nav = vi.fn();
    setNavigator(nav);
    fetchFn.mockResolvedValue(
      makeResponse({
        status: 401,
        body: { code: "unauthenticated", message: "no session" },
      }),
    );

    const err = await publicApi.getPublicDocument("tok").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(401);
    // 공개 경로는 skipAuthRedirect:true 이므로 미인증이어도 로그인으로 튕기지 않는다.
    expect(nav).not.toHaveBeenCalled();
  });

  it("publicApi.getPublicDocument 404(공개) → ApiError(404) reject, navigator 미호출(무효 경로 전파)", async () => {
    const fetchFn = stubFetch();
    const nav = vi.fn();
    setNavigator(nav);
    fetchFn.mockResolvedValue(
      makeResponse({ status: 404, body: { code: "not_found", message: "gone" } }),
    );

    const err = await publicApi.getPublicDocument("tok").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
    expect((err as ApiError).code).toBe("not_found");
    expect(nav).not.toHaveBeenCalled();
  });
});
