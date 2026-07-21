/**
 * s24-role-persistence — provider-role 파급 복원 회귀 + role E2E critical paths (task 4.3;
 * s26 role 축소로 owner/member/비멤버 3-state 로 정합).
 *
 * 이 파일은 s24 task 3.1(`CurrentWorkspaceProvider` 가 로드된 `workspace.role` 로 provider-role 을
 * 파생 — 과거엔 `null` 하드코딩)·task 3.2(`MembershipRoleProvider` 가 로드된 role 로 `roleFor` 시드)의
 * **행동 파급**을 회귀로 못박는다. 프로덕션은 이미 랜딩·커밋되었고 이 파일은 생산 코드를 바꾸지 않는다.
 *
 * ## 모킹 경계 = `global.fetch` 하나 (auth-flow.integration.test.tsx 패턴)
 * 브라우저 E2E 하네스가 없으므로 "E2E" 는 vitest+jsdom 전체 조립 통합 테스트다: 실제
 * `SessionProvider`(`/auth/me`→`/me/settings` 부트스트랩) → 실제 `CurrentWorkspaceProvider`
 * (`GET /workspaces` 로드) → 실제 `MembershipRoleProvider`(시드) 를 결합하고, 그 아래 실제 소비
 * 컴포넌트(`DocumentToolbar`/`MemberManagementPanel`/`EditLockBanner`/`CurrentWorkspaceIndicator`)를
 * 게이팅 로직 무변경으로 렌더한다. provider-role·`roleFor` 는 **주입하지 않고** 오직 mocked
 * `/workspaces` 응답 role 로부터 실제 provider 를 통해 복원된다 — 그래야 파급 복원 주장이 진짜다.
 *
 * 각 시나리오는 in-session 이력(recordOwner/recordSelfRole) 없이 **새 마운트**로 시작하므로
 * 새로고침/재로그인 직후를 시뮬레이션한다. 유일한 role 신호는 로드-시드다.
 *
 * Requirements: 2.2(provider-role 비-null 복원), 4.3(비멤버 편집 차단), 4.4(admin 세션 경로·role
 * 미접합), 5.4(role 신호에 admin override 미접합).
 * Design: §CurrentWorkspaceProvider Risks(파급 복원), §Testing Strategy E2E/UI(role 시나리오).
 */

import { describe, it, expect, afterEach } from "vitest";
import { vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

import { apiConfig } from "@/config";
import { SessionProvider } from "@/app/session/SessionProvider";
import { CurrentWorkspaceProvider } from "@/app/workspace-context/CurrentWorkspaceProvider";
import { ApiError } from "@/shared/api/errors";
import { Role } from "@/shared/auth/roles";
import type { WorkspaceRole } from "@/shared/auth/roles";
import type { WorkspaceRead } from "@/shared/types/workspace";

import { DocumentToolbar } from "./components/DocumentToolbar";
import { useDocumentScope } from "./hooks/useDocumentScope";
import { useEditorScope } from "@/features/editor/hooks/useEditorScope";
import { EditLockBanner } from "@/features/editor/components/EditLockBanner";
import type { LockState } from "@/features/editor/types";
import type { useDocumentMutations } from "./hooks/useDocumentMutations";
import { MemberManagementPanel } from "@/features/workspace/components/MemberManagementPanel";
import { CurrentWorkspaceIndicator } from "@/features/workspace/components/CurrentWorkspaceIndicator";
import {
  MembershipRoleProvider,
  useMembershipRoleSource,
} from "@/features/workspace/context/membershipRoleSource";

// --- fetch mock 유틸 (유일한 모킹 경계) — auth-flow.integration.test.tsx 아이디엄 재사용 -----------

const AUTH_USER = {
  id: 1,
  login_id: "alice",
  name: "Alice",
  email: "alice@example.com",
  is_admin: false,
} as const;

const SETTINGS = { autosave_enabled: true } as const;

/** 테스트가 사용하는 단일 워크스페이스 id(모든 시나리오 공통). */
const WS_ID = 1;

const API_BASE_PATH = new URL(apiConfig.baseUrl, "http://localhost").pathname.replace(/\/+$/, "");

function pathOf(input: RequestInfo | URL): string {
  const raw =
    typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
  const pathname = new URL(raw, "http://localhost").pathname;
  return API_BASE_PATH && pathname.startsWith(API_BASE_PATH)
    ? pathname.slice(API_BASE_PATH.length)
    : pathname;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** id=WS_ID 단일 WS 를 `role` 로 반환하는 WorkspaceRead. 목록 응답 item 계약. */
function makeWorkspace(role: WorkspaceRole | null): WorkspaceRead {
  return {
    id: WS_ID,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: null,
    name: "My WS",
    is_shareable: false,
    trash_retention_days: 30,
    role,
  };
}

/**
 * 전체 조립 부트스트랩을 위한 fetch 스텁: /auth/me(is_admin 주입) → /me/settings → /workspaces
 * (role 주입) → /workspaces/{id}/assignable-users(패널이 게이트 통과 시 조회하는 빈 목록).
 */
function installAssemblyFetch(options: { isAdmin: boolean; role: WorkspaceRole | null }): void {
  const impl = async (input: RequestInfo | URL): Promise<Response> => {
    const p = pathOf(input);
    if (p === "/auth/me") {
      return json({ ...AUTH_USER, is_admin: options.isAdmin });
    }
    if (p === "/me/settings") {
      return json(SETTINGS);
    }
    if (p === "/workspaces") {
      return json({ items: [makeWorkspace(options.role)], total: 1 });
    }
    if (p === `/workspaces/${WS_ID}/assignable-users`) {
      return json({ items: [], total: 0 });
    }
    return json({ code: "internal", message: `unexpected: ${p}` }, 500);
  };
  vi.stubGlobal("fetch", vi.fn(impl));
}

// --- 프로브·조립 -----------------------------------------------------------------------------

/** create/rename/remove/move·state 를 갖춘 타입 안전 mutations 스텁(게이팅과 무관한 leaf 의존). */
function makeMutations(): ReturnType<typeof useDocumentMutations> {
  return {
    create: vi.fn(),
    rename: vi.fn(),
    remove: vi.fn(),
    move: vi.fn(),
    state: { pending: false, error: null },
  };
}

/** `other` 잠금 상태(강제 해제 노출은 OWNER 게이트 + admin bypass 로만 판정). */
const OTHER_LOCK: LockState = {
  kind: "other",
  error: new ApiError({ status: 409, code: "conflict", message: "다른 사용자가 편집 중입니다." }),
};

/**
 * DocumentToolbar 를 **실제** `useDocumentScope().role`(=복원된 provider-role) 로 게이팅한다.
 * currentRole 은 주입이 아니라 실제 provider 파생값이라 파급 복원 주장이 진짜다.
 */
function DocumentToolbarProbe(): ReactElement {
  const { role } = useDocumentScope();
  return (
    <DocumentToolbar mutations={makeMutations()} currentRole={role} selectedId={null} selectedTitle={null} />
  );
}

/** EditLockBanner 를 **실제** `useEditorScope()` role/isAdmin 으로 게이팅한다. */
function EditLockBannerProbe(): ReactElement {
  const { role, isAdmin } = useEditorScope();
  return (
    <EditLockBanner
      lockState={OTHER_LOCK}
      documentId={99}
      currentRole={role}
      isAdmin={isAdmin}
      onRetry={() => {}}
    />
  );
}

/** 복원된 role 신호를 관찰 가능한 텍스트로 노출한다(admin 미접합 검증용). */
function RoleSignalProbe(): ReactElement {
  const { role } = useDocumentScope();
  const { roleFor } = useMembershipRoleSource();
  const member = roleFor(WS_ID);
  return (
    <div>
      <span data-testid="provider-role">{role === null ? "null" : Role[role]}</span>
      <span data-testid="member-role">{member === null ? "null" : Role[member]}</span>
    </div>
  );
}

/** role 시나리오 공통 씬: 배지 + 멤버 관리 패널 + 문서 툴바 + 잠금 배너 + role 신호 프로브. */
function Scene(): ReactElement {
  return (
    <>
      <CurrentWorkspaceIndicator />
      <MemberManagementPanel />
      <DocumentToolbarProbe />
      <EditLockBannerProbe />
      <RoleSignalProbe />
    </>
  );
}

/** SessionProvider → CurrentWorkspaceProvider → MembershipRoleProvider 실제 조립(마운트 순서 규약). */
function renderAssembly(children: ReactNode) {
  return render(
    <SessionProvider>
      <CurrentWorkspaceProvider>
        <MembershipRoleProvider>{children}</MembershipRoleProvider>
      </CurrentWorkspaceProvider>
    </SessionProvider>,
  );
}

// --- 질의 헬퍼 ------------------------------------------------------------------------------

const createButton = () => screen.queryByRole("button", { name: "새 문서" });
const memberPanel = () => screen.queryByRole("region", { name: "멤버 관리" });
const forceUnlockButton = () => screen.queryByRole("button", { name: "강제 해제" });
/** 배지 aria-label 은 `현재 워크스페이스: My WS, 역할: <label>` 형태. */
const roleBadge = (label: string) => screen.findByLabelText(new RegExp(`역할: ${label}$`));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

// ===========================================================================================
// A. 파급 복원 회귀 (Req 2.2 + design §CurrentWorkspaceProvider Risks)
//    provider-role 이 null→실값으로 바뀌며 소비처 게이팅이 member/owner 에게 의도대로 노출됨.
// ===========================================================================================

describe("파급 복원 회귀 — provider-role null→실값으로 소비처 게이팅 노출 (Req 2.2)", () => {
  it("member: 복원된 provider-role 로 DocumentToolbar 조작이 노출된다(과거 null 이면 은닉)", async () => {
    // 비-admin member 세션. role 은 오직 mocked /workspaces 응답에서만 온다(주입 없음).
    installAssemblyFetch({ isAdmin: false, role: "member" });

    renderAssembly(<DocumentToolbarProbe />);

    // 새 문서 생성 컨트롤이 노출된다. provider-role 이 null 하드코딩이던 과거엔 RequireRole(MEMBER)
    // 이 비-admin 에서 fallback null → 이 버튼이 없어 이 단언은 실패했다(회귀 민감).
    await waitFor(() => expect(createButton()).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "이름 변경" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "삭제" })).toBeInTheDocument();
  });

  it("owner: DocumentToolbar + EditLockBanner 강제 해제(OWNER 게이트)가 함께 노출된다", async () => {
    installAssemblyFetch({ isAdmin: false, role: "owner" });

    renderAssembly(
      <>
        <DocumentToolbarProbe />
        <EditLockBannerProbe />
      </>,
    );

    // member+ 게이트 통과(툴바) + OWNER 게이트 통과(강제 해제) 모두 복원된 provider-role 로 열린다.
    await waitFor(() => expect(createButton()).toBeInTheDocument());
    expect(forceUnlockButton()).toBeInTheDocument();
  });

  it("비멤버(role=null): 복원된 role 이 member 미만이라 member+ 게이트가 여전히 닫혀 있다(파급이 과노출 아님)", async () => {
    installAssemblyFetch({ isAdmin: false, role: null });

    renderAssembly(
      <>
        <CurrentWorkspaceIndicator />
        <DocumentToolbarProbe />
        <EditLockBannerProbe />
      </>,
    );

    // 시드 완료의 양성 신호(배지="역할 미확인") 확인 후 음성 단언 — 비멤버(role=null)라
    // member+ 게이트가 닫혀 있음을 증명(읽기는 전역 개방이지만 편집은 멤버십 필요).
    await roleBadge("역할 미확인");
    expect(createButton()).toBeNull();
    expect(forceUnlockButton()).toBeNull();
  });
});

// ===========================================================================================
// B. role E2E critical paths (각 = 새 마운트, in-session 이력 없음 = 새로고침)
//    design §Testing Strategy E2E/UI Tests. s26: owner/member/비멤버/admin.
// ===========================================================================================

describe("role E2E — 새로고침 후 role 복원 critical paths (design §E2E/UI)", () => {
  it("owner 새로고침: 배지=owner + 멤버 관리 접근 + 문서 툴바 노출", async () => {
    installAssemblyFetch({ isAdmin: false, role: "owner" });

    renderAssembly(<Scene />);

    // 배지가 복원된 owner 를 표시(in-session 이력 없이 로드-시드만으로).
    await roleBadge("owner");
    // owner 멤버 관리 패널 접근 복원(Req 4.1) + member+ 문서 툴바 노출.
    expect(memberPanel()).toBeInTheDocument();
    expect(createButton()).toBeInTheDocument();
    // OWNER 강제 해제도 열린다.
    expect(forceUnlockButton()).toBeInTheDocument();
  });

  it("member 새로고침: 문서 툴바 노출 + 멤버 관리 은닉 + 배지=member", async () => {
    installAssemblyFetch({ isAdmin: false, role: "member" });

    renderAssembly(<Scene />);

    // 시드 완료 양성 신호(배지=member) 후 게이팅 단언.
    await roleBadge("member");
    expect(createButton()).toBeInTheDocument(); // 문서 툴바 노출(member ≥ MEMBER)
    expect(memberPanel()).toBeNull(); // 멤버 관리 은닉(member < OWNER, Req 4.3)
    expect(forceUnlockButton()).toBeNull(); // OWNER 강제 해제도 은닉
  });

  it("비멤버(role=null) 새로고침: 읽기 전용(툴바·멤버 관리 미노출) + 배지=역할 미확인", async () => {
    installAssemblyFetch({ isAdmin: false, role: null });

    renderAssembly(<Scene />);

    await roleBadge("역할 미확인");
    expect(createButton()).toBeNull(); // 문서 툴바 미노출(비멤버 < MEMBER)
    expect(memberPanel()).toBeNull(); // 멤버 관리 미노출(비멤버 < OWNER, Req 4.3)
    expect(forceUnlockButton()).toBeNull();
  });

  it("admin: 세션 경로로 관리·툴바 통과하되 role 신호는 멤버십 role 만(admin 미접합, Req 4.4·5.4)", async () => {
    // admin 세션 + WS 멤버십 없음(role=null). admin 은 멤버가 아니므로 role 신호가 상승하면 안 된다.
    installAssemblyFetch({ isAdmin: true, role: null });

    renderAssembly(<Scene />);

    // 세션 경로(is_admin) bypass 로 멤버 관리 패널이 노출된다 — 로드 완료의 양성 신호로 사용.
    await waitFor(() => expect(memberPanel()).toBeInTheDocument());
    // 문서 툴바도 admin bypass 로 노출.
    expect(createButton()).toBeInTheDocument();

    // 그러나 role 신호에는 admin 상승이 접합되지 않는다(Req 4.4·5.4·INV-3):
    // provider-role·roleFor 모두 null(WS 멤버십 없음). 배지는 "역할 미확인".
    expect(screen.getByTestId("provider-role")).toHaveTextContent("null");
    expect(screen.getByTestId("member-role")).toHaveTextContent("null");
    await roleBadge("역할 미확인");
  });
});
