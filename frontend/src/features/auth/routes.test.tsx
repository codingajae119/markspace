import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { MemoryRouter, useLocation, useRoutes } from "react-router-dom";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import { authRoutes, CHANGE_PASSWORD_PATH } from "./routes";
import { createAppRoutes } from "@/app/router";
import { collectRoutesByScope } from "@/app/routeModule";
import { ROUTES } from "@/app/routes";
import { useSession } from "@/app/session/useSession";
import type { SessionContextValue, SessionState } from "@/app/session/SessionProvider";

// s17 등록 결선 통합 테스트: 실제 compose 경로(authRoutes → collectRoutesByScope → createAppRoutes)를
// in-memory 라우터로 마운트하고 세션 훅만 모킹해, 로그인(게스트 프레임)·비밀번호 변경(보호 프레임)
// 화면이 s16 프레임 슬롯에 올바르게 결선됨을 관찰한다. LoginPage/ChangePasswordPage 는 렌더 시점에
// API 를 호출하지 않으므로(제출 시에만) authApi 모킹은 불필요하다.
//
// router.test.tsx 와 동일하게 history 기반 MemoryRouter + useRoutes 로 구동한다(데이터 라우터의
// jsdom/undici AbortSignal realm 비호환 회피 — router.tsx 주석 참조).
vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));

const useSessionMock = useSession as unknown as Mock;

/** 세션 훅 반환값을 고정한다. refresh 는 계약상 항상 노출되므로 no-op 로 채운다. */
function setSession(state: SessionState): void {
  useSessionMock.mockReturnValue({ ...state, refresh: vi.fn() } as SessionContextValue);
}

/** 현재 location(pathname+search)을 노출해 리다이렉트 목적지를 검증하는 프로브. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

/** authRoutes 를 s16 실제 compose 경로로 취합·프레임에 주입해 useRoutes 로 렌더한다. */
function RoutesView() {
  return useRoutes(createAppRoutes(collectRoutesByScope(authRoutes)));
}

/** authRoutes 로 결선한 프레임을 지정 진입 경로로 마운트한다. */
function renderAt(initialEntries: string[]): void {
  render(
    <MemoryRouter initialEntries={initialEntries}>
      <LocationProbe />
      <RoutesView />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useSessionMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("authRoutes 등록 결선 (로그인=게스트 프레임 · 비밀번호 변경=보호 프레임)", () => {
  it("authRoutes 는 게스트 모듈(ROUTES.login)과 보호 모듈(비밀번호 변경)을 노출한다 (모듈 형태)", () => {
    const guest = authRoutes.find((module) => module.scope === "guest");
    const guarded = authRoutes.find((module) => module.scope === "protected");

    // 게스트 슬롯: 로그인 경로는 s16 ROUTES.login 상수여야 한다(하드코딩 금지).
    expect(guest).toBeDefined();
    expect(guest?.routes[0]?.path).toBe(ROUTES.login);

    // 보호 슬롯: 비밀번호 변경은 상대 경로로 등록되고 절대 경로 상수로 노출된다.
    expect(guarded).toBeDefined();
    expect(guarded?.routes[0]?.path).toBe("settings/password");
    expect(CHANGE_PASSWORD_PATH).toBe("/settings/password");
  });

  it("미인증 + /login → 게스트 프레임으로 실제 로그인 화면이 렌더된다(플레이스홀더 아님, 리다이렉트 없음) (Req 1.1, 6.1)", () => {
    setSession({ status: "unauthenticated" });

    renderAt([ROUTES.login]);

    // LoginForm 의 라벨 입력(login_id·password)이 렌더된다 = 실제 로그인 화면.
    expect(screen.getByLabelText("아이디")).toBeInTheDocument();
    expect(screen.getByLabelText("비밀번호")).toBeInTheDocument();
    // built-in 플레이스홀더(<div>login</div>)는 치환되어 더 이상 노출되지 않는다.
    expect(screen.queryByText("login")).not.toBeInTheDocument();
    // 게스트 프레임: 미인증이어도 로그인으로 강제 리다이렉트하지 않는다.
    expect(screen.getByTestId("location")).toHaveTextContent(ROUTES.login);
  });

  it("미인증 + /settings/password → 보호 프레임 가드가 returnTo 보존 로그인으로 리다이렉트한다 (Req 6.2, 6.3)", async () => {
    setSession({ status: "unauthenticated" });

    renderAt([CHANGE_PASSWORD_PATH]);

    // 리다이렉트 성립 → 로그인 화면(게스트 프레임)이 렌더되고 보호 콘텐츠는 노출되지 않는다.
    await waitFor(() => expect(screen.getByLabelText("아이디")).toBeInTheDocument());
    expect(screen.queryByLabelText("새 비밀번호")).not.toBeInTheDocument();
    // 진입하려던 경로가 returnTo 로 보존된 로그인 경로로 이동했다.
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/login?returnTo=%2Fsettings%2Fpassword",
    );
  });

  it("인증 + /settings/password → 보호 프레임 하위에서 비밀번호 변경 화면이 렌더된다 (Req 4.1, 6.1)", () => {
    setSession({
      status: "authenticated",
      user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
      settings: null,
    });

    renderAt([CHANGE_PASSWORD_PATH]);

    // ChangePasswordPage 의 현재/새 비밀번호 입력이 보호 프레임(main) 안에 렌더된다.
    expect(screen.getByLabelText("현재 비밀번호")).toBeInTheDocument();
    expect(screen.getByLabelText("새 비밀번호")).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent(CHANGE_PASSWORD_PATH);
  });
});
