import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { useSession } from "@/app/session/useSession";
import type { CurrentWorkspaceContextValue } from "@/app/workspace-context/types";
import { ShareLinkPanel } from "./ShareLinkPanel";

/**
 * S4 seam 잠금(lock-in) 통합 테스트 — task 5.1 (Req 1.1·5.1).
 *
 * 목적: `ShareLinkPanel` 이 자기완결(self-contained) 표면 마운트 컴포넌트임을 증명한다.
 * 오직 `{ documentId, documentStatus }` prop + 인가된 세션 신호만으로 관리 패널을 렌더하며,
 * s19 문서 뷰어 렌더 경로를 fork/수정하지 않는다(실제 마운트 지점은 교차-spec 검토 항목).
 *
 * 다른 단위 테스트(ShareLinkPanel.test.tsx)는 useShareManager 를 모킹해 배선을 검증하지만,
 * 이 통합 테스트는 REAL useShareManager + REAL InvalidationNotice 를 사용해 관측 신호
 * (documentStatus·isShareable) → invalidated 파생 → 안내 표면화의 종단 경로를 잠근다.
 * 모킹 경계는 api/context 뿐이다: `../api/shareApi`(발급/토글 미호출), useSession(admin
 * override), useCurrentWorkspace(role·isShareable). useShareManager 는 절대 모킹하지 않는다.
 *
 * role=null 상위갭(seam): useCurrentWorkspace().role 은 현재 항상 null 이므로(s16 하드코딩·
 * s18 주입 이연), 게이트 통과는 admin 세션 is_admin override 로 재현한다.
 */

// api 경계만 모킹한다(발급/토글은 이 테스트에서 호출하지 않으므로 apiClient 부작용 격리용).
vi.mock("../api/shareApi", () => ({
  shareApi: {
    issueLink: vi.fn(),
    toggleLink: vi.fn(),
  },
}));
vi.mock("@/app/session/useSession", () => ({ useSession: vi.fn() }));
vi.mock("@/app/workspace-context/useCurrentWorkspace", () => ({
  useCurrentWorkspace: vi.fn(),
}));

const useSessionMock = useSession as unknown as Mock;

// ShareLinkPanel 과 useShareManager 는 동일 alias 모듈 인스턴스를 공유하므로 단일 모킹으로 충분하다.
async function importWorkspaceMock(): Promise<Mock> {
  const mod = await import("@/app/workspace-context/useCurrentWorkspace");
  return mod.useCurrentWorkspace as unknown as Mock;
}

/** useSession 이 admin authenticated 를 반환하도록 설정(INV-3 admin override 로 게이트 통과). */
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
  partial: { role: null; isShareable: boolean },
): void {
  workspaceMock.mockReturnValue(
    partial as unknown as CurrentWorkspaceContextValue,
  );
}

/** 무효화 안내(InvalidationNotice invalidated 분기)의 대표 문구 존재 여부. */
function invalidationAdvisoryShown(): boolean {
  return screen.queryByText(/재발급/) !== null;
}

beforeEach(() => {
  useSessionMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("ShareLinkPanel — S4 자기완결 마운트 seam (REAL useShareManager + InvalidationNotice)", () => {
  it("admin + documentStatus=active + isShareable=true → 패널 렌더, 무효화 안내 미표시 (Req 1.1·5.1)", async () => {
    const workspaceMock = await importWorkspaceMock();
    mockAdmin();
    mockWorkspace(workspaceMock, { role: null, isShareable: true });

    render(<ShareLinkPanel documentId={10} documentStatus="active" />);

    // 자기완결: prop + 세션만으로 관리 컨트롤(발급)이 마운트된다.
    expect(screen.getByRole("button", { name: "링크 발급" })).toBeEnabled();
    // active + shareable → 실 useShareManager 가 invalidated=false 파생 → 안내 null.
    expect(invalidationAdvisoryShown()).toBe(false);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("documentStatus 를 active→trashed 로 rerender → 무효화 안내가 새로 표면화된다 (Req 5.1)", async () => {
    const workspaceMock = await importWorkspaceMock();
    mockAdmin();
    mockWorkspace(workspaceMock, { role: null, isShareable: true });

    const { rerender } = render(
      <ShareLinkPanel documentId={10} documentStatus="active" />,
    );
    // 초기 active 상태에서는 안내가 없다.
    expect(invalidationAdvisoryShown()).toBe(false);

    // 문서 상태 신호 변경(비활성) — 발급 링크가 없어도 관측 신호만으로 안내가 뜬다.
    rerender(<ShareLinkPanel documentId={10} documentStatus="trashed" />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(
      screen.getByText(/현재 공유 링크가 무효화되었을 수 있습니다/),
    ).toBeInTheDocument();
    expect(screen.getByText(/자동으로 복원되지 않습니다/)).toBeInTheDocument();
  });

  it("documentStatus=active 이지만 isShareable=false → 게이트-off 신호로 무효화 안내 + 발급 비활성 (Req 1.3·5.1)", async () => {
    const workspaceMock = await importWorkspaceMock();
    mockAdmin();
    mockWorkspace(workspaceMock, { role: null, isShareable: false });

    render(<ShareLinkPanel documentId={10} documentStatus="active" />);

    // 게이트 off 신호(isShareable=false)가 실 useShareManager 의 invalidated 파생을 켠다.
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(
      screen.getByText(/현재 공유 링크가 무효화되었을 수 있습니다/),
    ).toBeInTheDocument();
    // 동일 게이트 신호가 발급 컨트롤도 비활성화한다.
    expect(screen.getByRole("button", { name: "링크 발급" })).toBeDisabled();
    expect(screen.getByText(/공유가 꺼져 있어/)).toBeInTheDocument();
  });
});
