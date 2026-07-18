import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SessionProvider } from "@/app/session/SessionProvider";
import { useSession } from "@/app/session/useSession";
import { apiClient } from "@/shared/api/client";
import { ApiError } from "@/shared/api/errors";

// 부트스트랩 통합 테스트는 실제 HTTP 대신 apiClient 를 모킹해 200/401 전이·설정 로드·refresh 를 관찰한다.
vi.mock("@/shared/api/client", () => ({ apiClient: { get: vi.fn() } }));

// 모의 get 은 제네릭 시그니처 대신 경로 기반 분기로 다루므로 단순 Mock 으로 취급한다(테스트 로컬).
const getMock = apiClient.get as unknown as Mock;

/** 401 미인증 ApiError(부트스트랩 예외 경로 유발용). */
function unauthorizedError(): ApiError {
  return new ApiError({ status: 401, code: "unauthenticated", message: "unauthenticated" });
}

/** useSession() 을 소비해 상태·사용자·설정을 노출하는 최소 프로브. */
function Probe() {
  const session = useSession();
  return (
    <div>
      <span data-testid="status">{session.status}</span>
      {session.status === "authenticated" ? (
        <>
          <span data-testid="user-name">{session.user.name}</span>
          <span data-testid="is-admin">{String(session.user.is_admin)}</span>
          <span data-testid="settings">
            {session.settings === null ? "null" : String(session.settings.autosave_enabled)}
          </span>
        </>
      ) : null}
      <button
        type="button"
        onClick={() => {
          void session.refresh();
        }}
      >
        refresh
      </button>
    </div>
  );
}

function renderWithProvider(): void {
  render(
    <SessionProvider>
      <Probe />
    </SessionProvider>,
  );
}

beforeEach(() => {
  getMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("SessionProvider bootstrap", () => {
  it("/auth/me 200 → authenticated 로 전이하고 is_admin·settings 를 채운다 (AC 5.1, 5.2, 5.6)", async () => {
    getMock.mockImplementation((path: string) => {
      if (path === "/auth/me") {
        return Promise.resolve({
          id: 1,
          login_id: "alice",
          name: "Alice",
          email: null,
          is_admin: true,
        });
      }
      if (path === "/me/settings") {
        return Promise.resolve({ autosave_enabled: true });
      }
      return Promise.reject(new Error(`unexpected path ${path}`));
    });

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("user-name")).toHaveTextContent("Alice");
    expect(screen.getByTestId("is-admin")).toHaveTextContent("true");
    expect(screen.getByTestId("settings")).toHaveTextContent("true");

    // skipAuthRedirect:true 로 /auth/me 호출(부트스트랩 401 이 전역 리다이렉트를 트리거하지 않게).
    expect(getMock).toHaveBeenCalledWith("/auth/me", { skipAuthRedirect: true });
    expect(getMock).toHaveBeenCalledWith("/me/settings");
  });

  it("/auth/me 401 → unauthenticated 로 전이하고 /me/settings 는 호출하지 않는다 (AC 5.3)", async () => {
    getMock.mockImplementation((path: string) => {
      if (path === "/auth/me") {
        return Promise.reject(unauthorizedError());
      }
      return Promise.resolve({ autosave_enabled: true });
    });

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(getMock).toHaveBeenCalledWith("/auth/me", { skipAuthRedirect: true });
    expect(getMock).not.toHaveBeenCalledWith("/me/settings");
  });

  it("최초 렌더는 promise 해소 전 loading 을 노출한다 (AC 5.4)", () => {
    // 해소되지 않는 promise → 상태가 loading 에 머문다.
    getMock.mockImplementation(() => new Promise(() => {}));

    renderWithProvider();

    expect(screen.getByTestId("status")).toHaveTextContent("loading");
  });

  it("refresh() 가 부트스트랩을 재실행한다: 401(unauthenticated) → 200(authenticated) (AC 5.5)", async () => {
    let phase = 0;
    getMock.mockImplementation((path: string) => {
      if (path === "/auth/me") {
        if (phase === 0) {
          return Promise.reject(unauthorizedError());
        }
        return Promise.resolve({
          id: 2,
          login_id: "bob",
          name: "Bob",
          email: "bob@example.com",
          is_admin: false,
        });
      }
      return Promise.resolve({ autosave_enabled: false });
    });

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));

    phase = 1;
    await userEvent.click(screen.getByRole("button", { name: "refresh" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("user-name")).toHaveTextContent("Bob");
    expect(screen.getByTestId("settings")).toHaveTextContent("false");
  });

  it("/me/settings 실패에도 /auth/me 성공이면 authenticated 이며 settings 는 null (AC 5.2 nullable)", async () => {
    getMock.mockImplementation((path: string) => {
      if (path === "/auth/me") {
        return Promise.resolve({
          id: 1,
          login_id: "alice",
          name: "Alice",
          email: null,
          is_admin: false,
        });
      }
      return Promise.reject(new ApiError({ status: 500, code: "internal", message: "boom" }));
    });

    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("settings")).toHaveTextContent("null");
  });

  it("useSession() 을 SessionProvider 밖에서 쓰면 명확한 오류를 던진다", () => {
    // React 는 렌더 예외를 콘솔에 로깅하므로 테스트 노이즈를 억제한다.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/SessionProvider/);
    spy.mockRestore();
  });
});
