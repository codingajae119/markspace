import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

import { useLogin } from "./useLogin";
import { authApi } from "../api/authApi";
import { ApiError } from "@/shared/api/errors";
import { resolveReturnTo } from "@/app/routes";

// useLogin 은 s16 계약(useSession·resolveReturnTo·navigate)과 authApi 를 조합한다.
// 협력자를 모킹해 순서(refresh→navigate)·복귀 경로·실패 인라인·재제출 오류 해제를 관찰한다.
const navigateMock = vi.fn();
const refreshMock = vi.fn().mockResolvedValue(undefined);
let currentSearch = "";

vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => navigateMock,
    useLocation: () => ({
      search: currentSearch,
      pathname: "/",
      hash: "",
      state: null,
      key: "t",
    }),
  };
});

vi.mock("@/app/session/useSession", () => ({
  useSession: () => ({ status: "authenticated", refresh: refreshMock }),
}));

vi.mock("../api/authApi", () => ({ authApi: { login: vi.fn() } }));

const loginMock = authApi.login as unknown as Mock;

function unauthenticated(): ApiError {
  return new ApiError({
    status: 401,
    code: "unauthenticated",
    message: "Invalid credentials",
  });
}

beforeEach(() => {
  navigateMock.mockReset();
  refreshMock.mockReset();
  refreshMock.mockResolvedValue(undefined);
  loginMock.mockReset();
  currentSearch = "";
});

describe("useLogin", () => {
  it("성공 시 refresh() 후 resolveReturnTo 경로(returnTo)로 네비게이션한다", async () => {
    currentSearch = "?returnTo=%2Fdocs%2F5";
    loginMock.mockResolvedValueOnce({
      id: 1,
      login_id: "u",
      name: "U",
      email: null,
      is_admin: false,
    });

    const { result } = renderHook(() => useLogin());

    await act(async () => {
      await result.current.submit({ login_id: "u", password: "p" });
    });

    expect(refreshMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith(resolveReturnTo(currentSearch));
    expect(navigateMock).toHaveBeenCalledWith("/docs/5");
    // refresh 가 navigate 이전에 호출되어 인증 확정 전 리다이렉트를 피한다.
    expect(refreshMock.mock.invocationCallOrder[0]).toBeLessThan(
      navigateMock.mock.invocationCallOrder[0],
    );
    expect(result.current.error).toBeNull();
  });

  it("returnTo 가 없으면 기본 홈(ROUTES.root)으로 네비게이션한다", async () => {
    currentSearch = "";
    loginMock.mockResolvedValueOnce({
      id: 1,
      login_id: "u",
      name: "U",
      email: null,
      is_admin: false,
    });

    const { result } = renderHook(() => useLogin());

    await act(async () => {
      await result.current.submit({ login_id: "u", password: "p" });
    });

    expect(navigateMock).toHaveBeenCalledWith("/");
  });

  it("refresh 가 resolve 되기 전에는 navigate 하지 않는다(순서 보장)", async () => {
    currentSearch = "";
    loginMock.mockResolvedValueOnce({
      id: 1,
      login_id: "u",
      name: "U",
      email: null,
      is_admin: false,
    });
    let releaseRefresh: () => void = () => {};
    refreshMock.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          releaseRefresh = resolve;
        }),
    );

    const { result } = renderHook(() => useLogin());

    let submitPromise: Promise<void>;
    act(() => {
      submitPromise = result.current.submit({ login_id: "u", password: "p" });
    });

    // refresh 진행 중: navigate 아직 없음.
    await waitFor(() => expect(refreshMock).toHaveBeenCalledTimes(1));
    expect(navigateMock).not.toHaveBeenCalled();

    await act(async () => {
      releaseRefresh();
      await submitPromise;
    });
    expect(navigateMock).toHaveBeenCalledTimes(1);
  });

  it("401 실패 시 error 를 세팅하고 네비게이션하지 않는다", async () => {
    const err = unauthenticated();
    loginMock.mockRejectedValueOnce(err);

    const { result } = renderHook(() => useLogin());

    await act(async () => {
      await result.current.submit({ login_id: "u", password: "wrong" });
    });

    expect(result.current.error).toBe(err);
    expect(refreshMock).not.toHaveBeenCalled();
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("재제출 시 직전 error 를 해제한다(Req 2.5)", async () => {
    const err = unauthenticated();
    loginMock.mockRejectedValueOnce(err);

    const { result } = renderHook(() => useLogin());

    await act(async () => {
      await result.current.submit({ login_id: "u", password: "wrong" });
    });
    expect(result.current.error).toBe(err);

    // 두 번째 제출은 성공: 시작 시 직전 오류가 해제되고 최종 null 로 남는다.
    loginMock.mockResolvedValueOnce({
      id: 1,
      login_id: "u",
      name: "U",
      email: null,
      is_admin: false,
    });
    await act(async () => {
      await result.current.submit({ login_id: "u", password: "p" });
    });
    expect(result.current.error).toBeNull();
    expect(navigateMock).toHaveBeenCalledWith("/");
  });

  it("in-flight 동안 submitting=true, 완료 후 false 로 돌아온다", async () => {
    let releaseLogin: (v: unknown) => void = () => {};
    loginMock.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          releaseLogin = resolve;
        }),
    );

    const { result } = renderHook(() => useLogin());
    expect(result.current.submitting).toBe(false);

    let submitPromise: Promise<void>;
    act(() => {
      submitPromise = result.current.submit({ login_id: "u", password: "p" });
    });

    await waitFor(() => expect(result.current.submitting).toBe(true));

    await act(async () => {
      releaseLogin({ id: 1, login_id: "u", name: "U", email: null, is_admin: false });
      await submitPromise;
    });
    expect(result.current.submitting).toBe(false);
  });
});
