import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import type { RouteObject } from "react-router-dom";
import { MemoryRouter, useLocation, useRoutes } from "react-router-dom";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import { createAppRoutes } from "@/app/router";
import type { AppRouteExtensions } from "@/app/router";
import { useSession } from "@/app/session/useSession";
import type { SessionContextValue, SessionState } from "@/app/session/SessionProvider";

// 보호/게스트 프레임 통합 테스트: 실제 라우트 트리(createAppRoutes)를 in-memory 라우터로 마운트하고
// 세션 훅을 모킹해 ProtectedRoute 의 loading 유보 / 미인증 returnTo 리다이렉트 / 인증 Outlet 렌더를
// 프레임 문맥에서 관찰한다. 게스트 라우트(/share/:token)는 세션 없이 렌더됨을 확인한다.
//
// history 기반 `MemoryRouter` + `useRoutes` 로 구동한다. 데이터 라우터(`createMemoryRouter`)는
// 내비게이션 시 `new Request(url, { signal })` 를 만드는데, jsdom/undici 의 AbortSignal 이 서로 다른
// realm 이라 undici 가 이를 거부해(테스트 환경 한정 비호환) `<Navigate>` 리다이렉트가 크래시한다.
// history 기반 라우터는 Request 를 만들지 않아 이 이슈를 우회하며, 동일한 `createAppRoutes` 프레임을
// initialEntries 로 그대로 구동한다(앱 부팅은 `createAppRouter` 가 `createBrowserRouter` 로 마운트).
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

/** createAppRoutes 프레임을 useRoutes 로 렌더한다. */
function RoutesView({ ext }: { ext?: AppRouteExtensions }) {
  return useRoutes(createAppRoutes(ext));
}

/** createAppRoutes 로 만든 프레임을 지정 진입 경로로 마운트한다. */
function renderAt(initialEntries: string[], ext?: AppRouteExtensions): void {
  render(
    <MemoryRouter initialEntries={initialEntries}>
      <LocationProbe />
      <RoutesView ext={ext} />
    </MemoryRouter>,
  );
}

/** 보호 슬롯에 등록되는 샘플 feature 자식(3.5/7.1 이 실제 화면을 플러그인하는 슬롯 검증용). */
const docsChild: RouteObject = { path: "docs/:id", element: <div>doc content</div> };

beforeEach(() => {
  useSessionMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("보호/게스트 라우트 프레임", () => {
  it("미인증 상태로 보호 경로 진입 → returnTo 보존 로그인 리다이렉트 (AC 2.1, 2.2)", async () => {
    setSession({ status: "unauthenticated" });

    renderAt(["/docs/5"], { protectedRoutes: [docsChild] });

    // 로그인 플레이스홀더가 렌더되고(리다이렉트 성립), 보호 콘텐츠는 노출되지 않는다.
    await waitFor(() => expect(screen.getByText("login")).toBeInTheDocument());
    expect(screen.queryByText("doc content")).not.toBeInTheDocument();

    // 진입하려던 경로가 returnTo 로 보존된 로그인 경로로 이동했다(pathname+search).
    expect(screen.getByTestId("location")).toHaveTextContent("/login?returnTo=%2Fdocs%2F5");
  });

  it("부트스트랩 중(loading)에는 판정을 유보하고 로딩만 표시한다 — 리다이렉트 없음 (AC 2.5)", () => {
    setSession({ status: "loading" });

    renderAt(["/docs/5"], { protectedRoutes: [docsChild] });

    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    // 로딩 중에는 로그인 리다이렉트도, 보호 콘텐츠도 렌더하지 않는다(잘못된 리다이렉트 방지).
    expect(screen.queryByText("login")).not.toBeInTheDocument();
    expect(screen.queryByText("doc content")).not.toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("/docs/5");
  });

  it("인증 상태면 보호 자식(Outlet)이 AppLayout 프레임 안에 렌더된다 (AC 2.1, 7.2)", () => {
    setSession({
      status: "authenticated",
      user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
      settings: null,
    });

    renderAt(["/docs/5"], { protectedRoutes: [docsChild] });

    // 자식 콘텐츠가 렌더되고(Outlet), 인증 영역 공통 레이아웃(AppLayout)의 main 프레임 안에 놓인다.
    const layoutMain = screen.getByRole("main");
    expect(layoutMain).toBeInTheDocument();
    const child = screen.getByText("doc content");
    expect(child).toBeInTheDocument();
    expect(layoutMain).toContainElement(child);
    expect(screen.queryByText("login")).not.toBeInTheDocument();
  });

  it("/share/:token 게스트 라우트는 세션 없이 렌더되고 로그인으로 리다이렉트하지 않는다 (AC 2.4, 4.3)", () => {
    setSession({ status: "unauthenticated" });

    renderAt(["/share/abc"]);

    expect(screen.getByText("share")).toBeInTheDocument();
    expect(screen.queryByText("login")).not.toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("/share/abc");
  });
});
