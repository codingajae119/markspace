import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

import { useLogout } from "./useLogout";
import { authApi } from "../api/authApi";
import { ROUTES } from "@/app/routes";

// useLogout 은 s16 계약(useSession.refresh·navigate·ROUTES)과 authApi.logout 을 조합한다.
// 협력자를 모킹해 순서(logout→refresh→navigate)·중복 제출 방지(submitting)를 관찰한다.
const navigateMock = vi.fn();
const refreshMock = vi.fn().mockResolvedValue(undefined);

vi.mock("react-router-dom", async (orig) => {
  const actual = await orig<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("@/app/session/useSession", () => ({
  useSession: () => ({ status: "authenticated", refresh: refreshMock }),
}));

vi.mock("../api/authApi", () => ({ authApi: { logout: vi.fn() } }));

const logoutMock = authApi.logout as unknown as Mock;

beforeEach(() => {
  navigateMock.mockReset();
  refreshMock.mockReset();
  refreshMock.mockResolvedValue(undefined);
  logoutMock.mockReset();
  logoutMock.mockResolvedValue(undefined);
});

describe("useLogout", () => {
  it("logout() → refresh() → navigate(ROUTES.login) 순서로 수행한다", async () => {
    const { result } = renderHook(() => useLogout());

    await act(async () => {
      await result.current.submit();
    });

    expect(logoutMock).toHaveBeenCalledTimes(1);
    expect(refreshMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith(ROUTES.login);
    // 순서: logout < refresh < navigate.
    expect(logoutMock.mock.invocationCallOrder[0]).toBeLessThan(
      refreshMock.mock.invocationCallOrder[0],
    );
    expect(refreshMock.mock.invocationCallOrder[0]).toBeLessThan(
      navigateMock.mock.invocationCallOrder[0],
    );
  });

  it("refresh 가 resolve 되기 전에는 navigate 하지 않는다(순서 보장)", async () => {
    let releaseRefresh: () => void = () => {};
    refreshMock.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          releaseRefresh = resolve;
        }),
    );

    const { result } = renderHook(() => useLogout());

    let submitPromise: Promise<void>;
    act(() => {
      submitPromise = result.current.submit();
    });

    // refresh 진행 중: navigate 아직 없음.
    await waitFor(() => expect(refreshMock).toHaveBeenCalledTimes(1));
    expect(navigateMock).not.toHaveBeenCalled();

    await act(async () => {
      releaseRefresh();
      await submitPromise;
    });
    expect(navigateMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledWith(ROUTES.login);
  });

  it("in-flight 동안 submitting=true, 완료 후 false 로 돌아온다", async () => {
    let releaseLogout: () => void = () => {};
    logoutMock.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          releaseLogout = resolve;
        }),
    );

    const { result } = renderHook(() => useLogout());
    expect(result.current.submitting).toBe(false);

    let submitPromise: Promise<void>;
    act(() => {
      submitPromise = result.current.submit();
    });

    await waitFor(() => expect(result.current.submitting).toBe(true));

    await act(async () => {
      releaseLogout();
      await submitPromise;
    });
    expect(result.current.submitting).toBe(false);
  });

  it("진행 중 재호출은 무시되어 logout 이 중복 실행되지 않는다(중복 방지)", async () => {
    let releaseLogout: () => void = () => {};
    logoutMock.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          releaseLogout = resolve;
        }),
    );

    const { result } = renderHook(() => useLogout());

    let first: Promise<void>;
    act(() => {
      first = result.current.submit();
    });
    await waitFor(() => expect(result.current.submitting).toBe(true));

    // 진행 중 두 번째 호출: 무시되어야 한다.
    await act(async () => {
      await result.current.submit();
    });
    expect(logoutMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      releaseLogout();
      await first;
    });
    expect(logoutMock).toHaveBeenCalledTimes(1);
    expect(navigateMock).toHaveBeenCalledTimes(1);
  });
});
