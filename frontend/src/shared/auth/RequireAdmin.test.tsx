import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { RequireAdmin } from "@/shared/auth/RequireAdmin";
import { useSession } from "@/app/session/useSession";

// RequireAdmin 은 판정을 useSession() 의 is_admin(INV-3)으로만 수행한다. UI 노출/차단을
// 관찰하기 위해 세션 훅을 모킹하고 테스트마다 상태를 주입한다.
vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));

const useSessionMock = useSession as unknown as Mock;

/** useSession 이 admin authenticated 를 반환하도록 설정(INV-3 admin). */
function mockAuthenticatedAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 2, login_id: "root", name: "Root", email: null, is_admin: true },
    settings: null,
    refresh: vi.fn(),
  });
}

/** useSession 이 non-admin authenticated 를 반환하도록 설정. */
function mockAuthenticatedNonAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
    settings: null,
    refresh: vi.fn(),
  });
}

/** useSession 이 unauthenticated 를 반환하도록 설정(is_admin 취득 불가 → 거부). */
function mockUnauthenticated(): void {
  useSessionMock.mockReturnValue({ status: "unauthenticated", refresh: vi.fn() });
}

/** useSession 이 loading 을 반환하도록 설정(is_admin 미확정 → 거부). */
function mockLoading(): void {
  useSessionMock.mockReturnValue({ status: "loading", refresh: vi.fn() });
}

const CHILD = <span data-testid="admin-child">admin content</span>;
const FALLBACK = <span data-testid="fallback">not allowed</span>;

beforeEach(() => {
  useSessionMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("RequireAdmin — admin 라우트 게이팅(세션 is_admin, INV-3, WS role 독립)", () => {
  it("authenticated + is_admin=true → children 노출 (WS role 무관, 13.2)", () => {
    mockAuthenticatedAdmin();
    render(
      <RequireAdmin fallback={FALLBACK}>
        {CHILD}
      </RequireAdmin>,
    );
    expect(screen.getByTestId("admin-child")).toBeInTheDocument();
    expect(screen.queryByTestId("fallback")).not.toBeInTheDocument();
  });

  it("authenticated + is_admin=false → children 미노출, fallback 노출", () => {
    mockAuthenticatedNonAdmin();
    render(
      <RequireAdmin fallback={FALLBACK}>
        {CHILD}
      </RequireAdmin>,
    );
    expect(screen.queryByTestId("admin-child")).not.toBeInTheDocument();
    expect(screen.getByTestId("fallback")).toBeInTheDocument();
  });

  it("unauthenticated 세션 → children 미노출, fallback 노출 (is_admin 취득 불가)", () => {
    mockUnauthenticated();
    render(
      <RequireAdmin fallback={FALLBACK}>
        {CHILD}
      </RequireAdmin>,
    );
    expect(screen.queryByTestId("admin-child")).not.toBeInTheDocument();
    expect(screen.getByTestId("fallback")).toBeInTheDocument();
  });

  it("loading 세션 → children 미노출 (is_admin 미확정)", () => {
    mockLoading();
    render(
      <RequireAdmin fallback={FALLBACK}>
        {CHILD}
      </RequireAdmin>,
    );
    expect(screen.queryByTestId("admin-child")).not.toBeInTheDocument();
    expect(screen.getByTestId("fallback")).toBeInTheDocument();
  });

  it("거부 시 fallback 미지정 → 아무것도 렌더하지 않음(기본 null)", () => {
    mockAuthenticatedNonAdmin();
    const { container } = render(<RequireAdmin>{CHILD}</RequireAdmin>);
    expect(screen.queryByTestId("admin-child")).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });
});
