import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { Role } from "@/shared/auth/roles";
import { ApiError } from "@/shared/api/errors";
import { useSession } from "@/app/session/useSession";
import type { CurrentWorkspaceContextValue } from "@/app/workspace-context/types";
import { useShareManager } from "../hooks/useShareManager";
import type { UseShareManagerResult } from "../hooks/useShareManager";
import type { ShareLinkRead } from "../api/types";
import { ShareLinkPanel } from "./ShareLinkPanel";

// ShareLinkPanel 은 관리 UI 전체를 RequireRole(minimum=EDITOR, currentRole=useCurrentWorkspace().role)
// 단일 게이트로 감싸 viewer·비멤버에게 미노출한다(Req 1.1·1.2). RequireRole 은 isAdmin 을
// useSession() 에서만 취득하므로(admin override) 세션 훅을 모킹한다. 발급/토글 상태는
// useShareManager 를 모킹해 제어하며, InvalidationNotice·CopyLinkButton 은 실제 컴포넌트를 사용한다.
//
// role=null 상위갭(seam): useCurrentWorkspace().role 은 현재 항상 null(s16 하드코딩·s18 주입 이연)
// 이므로, 오늘 패널은 admin 세션의 is_admin override 로만 노출된다. 이를 재현하기 위해 게이트 통과
// 케이스는 mockAdmin() 또는 role=EDITOR 를 명시적으로 주입한다.
// Requirements: 1.1, 1.2, 1.3, 1.5, 2.2, 3.3, 5.1

vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));
vi.mock("@/app/workspace-context/useCurrentWorkspace", () => ({
  useCurrentWorkspace: vi.fn(),
}));
vi.mock("../hooks/useShareManager", () => ({ useShareManager: vi.fn() }));

// mockable 경계 훅들에 대한 타입 안전 참조(any 미사용; 문서화된 as unknown as Mock 예외).
const useSessionMock = useSession as unknown as Mock;
const useShareManagerMock = useShareManager as unknown as Mock;
// useCurrentWorkspace 는 컴포넌트가 relative 가 아닌 alias 로 import 하므로 alias 경로를 다시 가져온다.
// (동일 모듈 인스턴스이므로 아래 helper 로 반환값을 제어한다.)
async function importWorkspaceMock(): Promise<Mock> {
  const mod = await import("@/app/workspace-context/useCurrentWorkspace");
  return mod.useCurrentWorkspace as unknown as Mock;
}

/** useSession 이 non-admin authenticated 를 반환하도록 설정(admin override 미적용). */
function mockNonAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 1, login_id: "alice", name: "Alice", email: null, is_admin: false },
    settings: null,
    refresh: vi.fn(),
  });
}

/** useSession 이 admin authenticated 를 반환하도록 설정(INV-3 admin override). */
function mockAdmin(): void {
  useSessionMock.mockReturnValue({
    status: "authenticated",
    user: { id: 2, login_id: "root", name: "Root", email: null, is_admin: true },
    settings: null,
    refresh: vi.fn(),
  });
}

/** useCurrentWorkspace 가 role·isShareable 을 반환하도록 설정. */
function mockWorkspace(
  workspaceMock: Mock,
  partial: { role: Role | null; isShareable: boolean },
): void {
  workspaceMock.mockReturnValue(
    partial as unknown as CurrentWorkspaceContextValue,
  );
}

/** useShareManager 반환 상태를 구성(기본은 링크 없음·오류 없음). */
function makeManager(
  overrides: Partial<UseShareManagerResult> = {},
): UseShareManagerResult {
  return {
    link: null,
    frontShareUrl: null,
    reissued: false,
    invalidated: false,
    pending: false,
    error: null,
    issue: vi.fn(),
    toggle: vi.fn(),
    ...overrides,
  };
}

const activeLink: ShareLinkRead = {
  id: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
  document_id: 10,
  token: "tok-abc",
  is_enabled: true,
  share_url: "/public/tok-abc",
};

beforeEach(() => {
  useSessionMock.mockReset();
  useShareManagerMock.mockReset();
  useShareManagerMock.mockReturnValue(makeManager());
});

afterEach(() => {
  cleanup();
});

describe("ShareLinkPanel — RequireRole 게이팅 + 발급/토글 배선", () => {
  it("viewer(비-admin) → 관리 컨트롤 미노출 + 도메인 훅 미호출 (Req 1.1·1.2)", async () => {
    const workspaceMock = await importWorkspaceMock();
    mockNonAdmin();
    mockWorkspace(workspaceMock, { role: Role.VIEWER, isShareable: true });

    render(<ShareLinkPanel documentId={10} documentStatus="active" />);

    expect(screen.queryByRole("button", { name: "링크 발급" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "링크 복사" })).not.toBeInTheDocument();
    // 게이트 실패 시 관리 콘텐츠가 마운트되지 않아 도메인 훅도 호출되지 않는다.
    expect(useShareManagerMock).not.toHaveBeenCalled();
  });

  it("admin 세션 + role=null → 관리 패널 노출(RequireRole admin override, Req 1.2)", async () => {
    const workspaceMock = await importWorkspaceMock();
    mockAdmin();
    mockWorkspace(workspaceMock, { role: null, isShareable: true });

    render(<ShareLinkPanel documentId={10} documentStatus="active" />);

    expect(screen.getByRole("button", { name: "링크 발급" })).toBeInTheDocument();
  });

  it("role=EDITOR(비-admin) → 관리 패널 노출(currentRole 주입 경로, Req 1.1)", async () => {
    const workspaceMock = await importWorkspaceMock();
    mockNonAdmin();
    mockWorkspace(workspaceMock, { role: Role.EDITOR, isShareable: true });

    render(<ShareLinkPanel documentId={10} documentStatus="active" />);

    expect(screen.getByRole("button", { name: "링크 발급" })).toBeInTheDocument();
  });

  it("isShareable=false → 발급 비활성 + 게이트 off 안내 노출 (Req 1.3)", async () => {
    const workspaceMock = await importWorkspaceMock();
    mockAdmin();
    mockWorkspace(workspaceMock, { role: null, isShareable: false });

    render(<ShareLinkPanel documentId={10} documentStatus="active" />);

    expect(screen.getByRole("button", { name: "링크 발급" })).toBeDisabled();
    expect(screen.getByText(/공유가 꺼져 있어/)).toBeInTheDocument();
  });

  it("useShareManager.error(ApiError) → ErrorMessage 로 표면화 (Req 1.5·2.2·3.3)", async () => {
    const workspaceMock = await importWorkspaceMock();
    mockAdmin();
    mockWorkspace(workspaceMock, { role: null, isShareable: true });
    useShareManagerMock.mockReturnValue(
      makeManager({
        error: new ApiError({
          status: 409,
          code: "conflict",
          message: "공유가 꺼져 있거나 문서가 활성 상태가 아닙니다.",
        }),
      }),
    );

    render(<ShareLinkPanel documentId={10} documentStatus="active" />);

    expect(
      screen.getByText("공유가 꺼져 있거나 문서가 활성 상태가 아닙니다."),
    ).toBeInTheDocument();
  });

  it("invalidated/reissued 신호 → InvalidationNotice 내용 노출 (Req 5.1)", async () => {
    const workspaceMock = await importWorkspaceMock();
    mockAdmin();
    mockWorkspace(workspaceMock, { role: null, isShareable: true });
    useShareManagerMock.mockReturnValue(
      makeManager({ invalidated: true, reissued: true }),
    );

    render(<ShareLinkPanel documentId={10} documentStatus="archived" />);

    // 실제 InvalidationNotice 가 두 안내를 렌더한다.
    expect(screen.getByText(/무효화되었을 수 있습니다/)).toBeInTheDocument();
    expect(screen.getByText(/이전에 배포한 링크는 더 이상 유효하지 않습니다/)).toBeInTheDocument();
  });

  it("링크 존재 시 CopyLinkButton 이 frontShareUrl 로 활성화된다 (Req 2.2)", async () => {
    const workspaceMock = await importWorkspaceMock();
    mockAdmin();
    mockWorkspace(workspaceMock, { role: null, isShareable: true });
    useShareManagerMock.mockReturnValue(
      makeManager({
        link: activeLink,
        frontShareUrl: "http://localhost/share/tok-abc",
      }),
    );

    render(<ShareLinkPanel documentId={10} documentStatus="active" />);

    expect(screen.getByRole("button", { name: "링크 복사" })).toBeEnabled();
  });

  it("링크 부재 시 CopyLinkButton 이 비활성이다 (Req 2.2·4.4)", async () => {
    const workspaceMock = await importWorkspaceMock();
    mockAdmin();
    mockWorkspace(workspaceMock, { role: null, isShareable: true });
    // 기본 makeManager(): link=null, frontShareUrl=null.

    render(<ShareLinkPanel documentId={10} documentStatus="active" />);

    expect(screen.getByRole("button", { name: "링크 복사" })).toBeDisabled();
  });
});
