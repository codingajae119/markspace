/**
 * 인증 플로우 통합 테스트 (s17-fe-auth, task 5.1).
 *
 * 모킹을 진짜 네트워크 경계(`global.fetch`) 하나로 최소화하고, 그 위 계층은 전부 실제로 결합한다:
 * s16 공용 `apiClient`(`skipAuthRedirect` + 전역 401 인터셉터 + `ApiError` 정규화),
 * `SessionProvider` 부트스트랩(`/auth/me` → `/me/settings`), react-router, 그리고 실제 s17 훅/컴포넌트
 * (useLogin·useLogout·useChangePassword·LoginForm·LogoutButton·ChangePasswordPage).
 *
 * 커버 플로우:
 *  1. 로그인 성공 → 세션 authenticated 전이 → returnTo 복귀(없으면 기본 홈 ROUTES.root)
 *  2. 로그인 401 → 전역 401 리다이렉트 미발동(skipAuthRedirect) · ErrorMessage 인라인 (headline)
 *  3. 로그아웃 → 204 → unauthenticated → 로그인 경로 이동
 *  4. 비밀번호 변경 422 두 갈래(unprocessable 메시지 / validation_error field_errors)
 *
 * Requirements: 1.3, 2.1, 2.3, 3.3, 4.4, 4.5, 5.1
 */

import { describe, it, expect, afterEach, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import type { ReactElement } from "react";

import { apiConfig } from "@/config";
import { SessionProvider } from "@/app/session/SessionProvider";
import { useSession } from "@/app/session/useSession";
import { ROUTES } from "@/app/routes";
import { setNavigator, resetNavigation } from "@/shared/api/navigation";

import { LoginForm } from "./components/LoginForm";
import { LogoutButton } from "./components/LogoutButton";
import { ChangePasswordPage } from "./pages/ChangePasswordPage";

// --- fetch mock 유틸 (유일한 모킹 경계) ------------------------------------

/** apiClient 가 소비하는 최소 응답 계약. `/auth/me`·`/auth/login` → AuthUser 형태. */
const AUTH_USER = {
  id: 1,
  login_id: "alice",
  name: "Alice",
  email: "alice@example.com",
  is_admin: false,
} as const;

/** `/me/settings` → UserSettings 형태. */
const SETTINGS = { autosave_enabled: true } as const;

/**
 * base URL 의 경로 부분(예: `/api/1.0`) — 백엔드가 모든 API 를 마운트한 버전 전송 prefix.
 * apiClient 가 요청 앞에 붙이므로, 테스트 라우팅은 이를 벗긴 **논리 경로**로 대조한다.
 */
const API_BASE_PATH = new URL(apiConfig.baseUrl, "http://localhost").pathname.replace(/\/+$/, "");

/** apiClient 는 `fetch(buildUrl(path), ...)` 로 호출한다. base URL(origin+prefix)을 떼고 논리 경로만 뽑는다. */
function pathOf(input: RequestInfo | URL): string {
  const raw =
    typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
  const pathname = new URL(raw, "http://localhost").pathname;
  return API_BASE_PATH && pathname.startsWith(API_BASE_PATH)
    ? pathname.slice(API_BASE_PATH.length)
    : pathname;
}

/** 요청 메서드(2번째 fetch 인자). 기본 GET. */
function methodOf(init?: RequestInit): string {
  return (init?.method ?? "GET").toUpperCase();
}

/** apiClient 의 `res.text()`/`res.status`/`res.ok` 가 실제 동작하도록 REAL Response 를 만든다. */
function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** 204(빈 본문) 응답. 로그아웃 성공에 사용. */
function noContent(): Response {
  return new Response(null, { status: 204 });
}

type FetchImpl = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

/** 주어진 구현으로 global.fetch 를 스텁하고 mock 을 반환한다. afterEach 에서 unstub. */
function installFetch(impl: FetchImpl): void {
  vi.stubGlobal("fetch", vi.fn(impl));
}

// --- 프로브 컴포넌트 --------------------------------------------------------

/** 실제 useSession() 으로 현재 세션 status 를 노출한다. */
function SessionProbe(): ReactElement {
  const session = useSession();
  return <div data-testid="session">{session.status}</div>;
}

/** 현재 location(pathname+search)을 노출해 네비게이션 목적지를 관찰한다. */
function LocationProbe(): ReactElement {
  const location = useLocation();
  return <div data-testid="loc">{`${location.pathname}${location.search}`}</div>;
}

afterEach(() => {
  cleanup();
  // 모듈 스코프 싱글턴(navigator/loginPathBuilder) 누수 방지.
  resetNavigation();
  // stub 한 global.fetch 복원 + spy 복원.
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------

describe("인증 플로우 통합 — 로그인 성공·세션 전이·returnTo 복귀 (Req 1.3, 5.1)", () => {
  it("로그인 성공 시 세션이 authenticated 로 전이하고 returnTo(/docs/5)로 복귀한다", async () => {
    // /auth/me 는 stateful: 로그인 전 401 → 로그인 후 200 을 관찰해 refresh 가 전이를 확정한다.
    let authed = false;
    installFetch(async (input, init) => {
      const p = pathOf(input);
      const m = methodOf(init);
      if (p === "/auth/login" && m === "POST") {
        authed = true;
        return json(AUTH_USER);
      }
      if (p === "/auth/me") {
        return authed ? json(AUTH_USER) : json({ code: "unauthenticated", message: "no session" }, 401);
      }
      if (p === "/me/settings") {
        return json(SETTINGS);
      }
      return json({ code: "internal", message: "unexpected" }, 500);
    });

    render(
      <SessionProvider>
        <MemoryRouter initialEntries={["/login?returnTo=%2Fdocs%2F5"]}>
          <LocationProbe />
          <SessionProbe />
          <LoginForm />
        </MemoryRouter>
      </SessionProvider>,
    );

    // 부트스트랩: 로그인 전 세션은 unauthenticated 로 확정된다.
    await waitFor(() => expect(screen.getByTestId("session")).toHaveTextContent("unauthenticated"));

    await userEvent.type(screen.getByLabelText("아이디"), "alice");
    await userEvent.type(screen.getByLabelText("비밀번호"), "s3cret-pass");
    await userEvent.click(screen.getByRole("button", { name: "로그인" }));

    // login → refresh(/auth/me 200 → /me/settings) → authenticated 전이.
    await waitFor(() => expect(screen.getByTestId("session")).toHaveTextContent("authenticated"));
    // returnTo 복귀: 비-루트 경로 /docs/5 로 이동(기본 홈과 자명하게 구분됨).
    expect(screen.getByTestId("loc")).toHaveTextContent("/docs/5");
  });

  it("returnTo 가 없으면 기본 홈(ROUTES.root)으로 복귀한다", async () => {
    let authed = false;
    installFetch(async (input, init) => {
      const p = pathOf(input);
      const m = methodOf(init);
      if (p === "/auth/login" && m === "POST") {
        authed = true;
        return json(AUTH_USER);
      }
      if (p === "/auth/me") {
        return authed ? json(AUTH_USER) : json({ code: "unauthenticated", message: "no session" }, 401);
      }
      if (p === "/me/settings") {
        return json(SETTINGS);
      }
      return json({ code: "internal", message: "unexpected" }, 500);
    });

    render(
      <SessionProvider>
        <MemoryRouter initialEntries={["/login"]}>
          <LocationProbe />
          <SessionProbe />
          <LoginForm />
        </MemoryRouter>
      </SessionProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("session")).toHaveTextContent("unauthenticated"));

    await userEvent.type(screen.getByLabelText("아이디"), "alice");
    await userEvent.type(screen.getByLabelText("비밀번호"), "s3cret-pass");
    await userEvent.click(screen.getByRole("button", { name: "로그인" }));

    await waitFor(() => expect(screen.getByTestId("session")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("loc")).toHaveTextContent(ROUTES.root);
  });
});

describe("인증 플로우 통합 — 로그인 401 인라인 · 전역 리다이렉트 미발동 (Req 2.1, 2.3) [headline]", () => {
  it("401 이면 ErrorMessage 를 인라인 표시하고, /login 에 머물며, navSpy 는 호출되지 않는다", async () => {
    // 전역 401 인터셉터의 navigate seam 을 스파이로 주입한다. 이것이 호출되면 세션-만료 리다이렉트.
    const navSpy = vi.fn();
    setNavigator(navSpy);

    installFetch(async (input, init) => {
      const p = pathOf(input);
      const m = methodOf(init);
      if (p === "/auth/login" && m === "POST") {
        return json({ code: "unauthenticated", message: "Invalid credentials" }, 401);
      }
      if (p === "/auth/me") {
        return json({ code: "unauthenticated", message: "no session" }, 401);
      }
      if (p === "/me/settings") {
        return json(SETTINGS);
      }
      return json({ code: "internal", message: "unexpected" }, 500);
    });

    render(
      <SessionProvider>
        <MemoryRouter initialEntries={["/login"]}>
          <LocationProbe />
          <SessionProbe />
          <LoginForm />
        </MemoryRouter>
      </SessionProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("session")).toHaveTextContent("unauthenticated"));

    await userEvent.type(screen.getByLabelText("아이디"), "alice");
    await userEvent.type(screen.getByLabelText("비밀번호"), "wrong-pass");
    await userEvent.click(screen.getByRole("button", { name: "로그인" }));

    // 백엔드 401 메시지가 role=alert 로 인라인 표면화된다.
    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent("Invalid credentials");
    });

    // 로그인 경로에 그대로 머문다(리다이렉트 없음).
    expect(screen.getByTestId("loc")).toHaveTextContent("/login");

    // HEADLINE 단언: navSpy 는 호출되지 않는다.
    // 이유: authApi.login 은 `skipAuthRedirect: true` 로 호출한다 → apiClient 의 401 인터셉터 조건
    //   `skipAuthRedirect !== true` 가 false → redirectToLogin() 이 실행되지 않아 navigator seam 미호출.
    // 즉 로그인 실패의 401 은 세션-만료 리다이렉트가 아니라 폼 인라인 오류로만 처리된다(Req 2.3).
    // (만약 authApi.login 이 skipAuthRedirect 옵션을 누락하면 window.location.pathname="/" 이라
    //  isOnLoginRoute()=false 가 되어 redirectToLogin 이 호출되고 이 단언이 실패한다 → load-bearing.)
    expect(navSpy).not.toHaveBeenCalled();
  });
});

describe("인증 플로우 통합 — 로그아웃 → 204 → unauthenticated → 로그인 이동 (Req 3.3, 5.1)", () => {
  it("로그아웃 클릭 시 세션이 unauthenticated 로 전이하고 /login 으로 이동한다", async () => {
    // 초기 authenticated: /auth/me 200. 로그아웃 후 401 로 뒤집혀 refresh 가 미인증 전이를 관찰.
    let authed = true;
    installFetch(async (input, init) => {
      const p = pathOf(input);
      const m = methodOf(init);
      if (p === "/auth/logout" && m === "POST") {
        authed = false;
        return noContent();
      }
      if (p === "/auth/me") {
        return authed ? json(AUTH_USER) : json({ code: "unauthenticated", message: "logged out" }, 401);
      }
      if (p === "/me/settings") {
        return json(SETTINGS);
      }
      return json({ code: "internal", message: "unexpected" }, 500);
    });

    render(
      <SessionProvider>
        <MemoryRouter initialEntries={["/settings"]}>
          <LocationProbe />
          <SessionProbe />
          <LogoutButton />
        </MemoryRouter>
      </SessionProvider>,
    );

    // 부트스트랩: 초기엔 authenticated.
    await waitFor(() => expect(screen.getByTestId("session")).toHaveTextContent("authenticated"));

    await userEvent.click(screen.getByRole("button", { name: "로그아웃" }));

    // logout(204) → refresh(/auth/me 401) → unauthenticated → navigate(ROUTES.login).
    await waitFor(() => expect(screen.getByTestId("session")).toHaveTextContent("unauthenticated"));
    expect(screen.getByTestId("loc")).toHaveTextContent(ROUTES.login);
  });
});

describe("인증 플로우 통합 — 비밀번호 변경 422 두 갈래 (Req 4.4, 4.5)", () => {
  it("422 unprocessable(현재 비밀번호 불일치) message 를 표면화한다 (Req 4.4)", async () => {
    installFetch(async (input, init) => {
      const p = pathOf(input);
      const m = methodOf(init);
      if (p === "/auth/password" && m === "POST") {
        return json({ code: "unprocessable", message: "Current password does not match" }, 422);
      }
      return json({ code: "internal", message: "unexpected" }, 500);
    });

    render(<ChangePasswordPage />);

    await userEvent.type(screen.getByLabelText("현재 비밀번호"), "wrong-current");
    await userEvent.type(screen.getByLabelText("새 비밀번호"), "new-password-123");
    await userEvent.click(screen.getByRole("button", { name: "비밀번호 변경" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Current password does not match");
    });
  });

  it("422 validation_error(새 비밀번호 정책) field_errors 를 표면화한다 (Req 4.5)", async () => {
    installFetch(async (input, init) => {
      const p = pathOf(input);
      const m = methodOf(init);
      if (p === "/auth/password" && m === "POST") {
        return json(
          {
            code: "validation_error",
            message: "입력값을 확인하세요.",
            field_errors: [{ field: "new_password", message: "비밀번호는 8자 이상" }],
          },
          422,
        );
      }
      return json({ code: "internal", message: "unexpected" }, 500);
    });

    render(<ChangePasswordPage />);

    await userEvent.type(screen.getByLabelText("현재 비밀번호"), "correct-current");
    await userEvent.type(screen.getByLabelText("새 비밀번호"), "short");
    await userEvent.click(screen.getByRole("button", { name: "비밀번호 변경" }));

    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent("비밀번호는 8자 이상");
    });
  });
});
