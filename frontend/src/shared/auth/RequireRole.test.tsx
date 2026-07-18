import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { Role } from "@/shared/auth/roles";
import { RequireRole } from "@/shared/auth/RequireRole";
import { useSession } from "@/app/session/useSession";

// RequireRole 은 isAdmin 을 useSession() 에서만 취득한다(currentRole 은 prop 주입). UI 게이팅을
// 관찰하기 위해 세션 훅을 모킹하고 테스트마다 상태를 주입한다.
vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));

const useSessionMock = useSession as unknown as Mock;

/** useSession 이 non-admin authenticated 를 반환하도록 설정. */
function mockAuthenticatedNonAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
    settings: null,
    refresh: vi.fn(),
  });
}

/** useSession 이 admin authenticated 를 반환하도록 설정(INV-3 admin override). */
function mockAuthenticatedAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 2, login_id: "root", name: "Root", email: null, is_admin: true },
    settings: null,
    refresh: vi.fn(),
  });
}

/** useSession 이 unauthenticated 를 반환하도록 설정(isAdmin=false). */
function mockUnauthenticated(): void {
  useSessionMock.mockReturnValue({ status: "unauthenticated", refresh: vi.fn() });
}

/** useSession 이 loading 을 반환하도록 설정(isAdmin=false). */
function mockLoading(): void {
  useSessionMock.mockReturnValue({ status: "loading", refresh: vi.fn() });
}

const CHILD = <span data-testid="gated-child">gated content</span>;
const FALLBACK = <span data-testid="fallback">not allowed</span>;

beforeEach(() => {
  useSessionMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("RequireRole — 선언형 워크스페이스 role 게이팅(INV-1·2·3)", () => {
  it("viewer + non-admin, minimum EDITOR → children 미노출, fallback 노출 (INV-2)", () => {
    mockAuthenticatedNonAdmin();
    render(
      <RequireRole minimum={Role.EDITOR} currentRole={Role.VIEWER} fallback={FALLBACK}>
        {CHILD}
      </RequireRole>,
    );
    expect(screen.queryByTestId("gated-child")).not.toBeInTheDocument();
    expect(screen.getByTestId("fallback")).toBeInTheDocument();
  });

  it("owner + non-admin, minimum EDITOR → children 노출 (owner ≥ editor)", () => {
    mockAuthenticatedNonAdmin();
    render(
      <RequireRole minimum={Role.EDITOR} currentRole={Role.OWNER}>
        {CHILD}
      </RequireRole>,
    );
    expect(screen.getByTestId("gated-child")).toBeInTheDocument();
  });

  it("admin 세션, currentRole null, minimum OWNER → children 노출 (admin override, INV-3)", () => {
    mockAuthenticatedAdmin();
    render(
      <RequireRole minimum={Role.OWNER} currentRole={null}>
        {CHILD}
      </RequireRole>,
    );
    expect(screen.getByTestId("gated-child")).toBeInTheDocument();
  });

  it("admin 세션, currentRole viewer, minimum OWNER → children 노출 (admin override, INV-3)", () => {
    mockAuthenticatedAdmin();
    render(
      <RequireRole minimum={Role.OWNER} currentRole={Role.VIEWER}>
        {CHILD}
      </RequireRole>,
    );
    expect(screen.getByTestId("gated-child")).toBeInTheDocument();
  });

  it("거부 시 custom fallback 노출, 기본(fallback 미지정) → 아무것도 렌더하지 않음", () => {
    mockAuthenticatedNonAdmin();
    // fallback 미지정 → children 도 fallback 도 없음.
    const { container } = render(
      <RequireRole minimum={Role.EDITOR} currentRole={Role.VIEWER}>
        {CHILD}
      </RequireRole>,
    );
    expect(screen.queryByTestId("gated-child")).not.toBeInTheDocument();
    expect(screen.queryByTestId("fallback")).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it("unauthenticated 세션 → isAdmin false, viewer + minimum EDITOR → 거부 (currentRole 만 판정)", () => {
    mockUnauthenticated();
    render(
      <RequireRole minimum={Role.EDITOR} currentRole={Role.VIEWER} fallback={FALLBACK}>
        {CHILD}
      </RequireRole>,
    );
    expect(screen.queryByTestId("gated-child")).not.toBeInTheDocument();
    expect(screen.getByTestId("fallback")).toBeInTheDocument();
  });

  it("loading 세션 → isAdmin false, viewer + minimum EDITOR → 거부", () => {
    mockLoading();
    render(
      <RequireRole minimum={Role.EDITOR} currentRole={Role.VIEWER}>
        {CHILD}
      </RequireRole>,
    );
    expect(screen.queryByTestId("gated-child")).not.toBeInTheDocument();
  });

  it("unauthenticated 세션이라도 currentRole 이 충족하면 노출 (currentRole 만으로 판정)", () => {
    mockUnauthenticated();
    render(
      <RequireRole minimum={Role.VIEWER} currentRole={Role.EDITOR}>
        {CHILD}
      </RequireRole>,
    );
    expect(screen.getByTestId("gated-child")).toBeInTheDocument();
  });
});
