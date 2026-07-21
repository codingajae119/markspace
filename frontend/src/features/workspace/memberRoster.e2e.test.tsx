/**
 * s25-member-roster — 재로그인 가시성 + 제거 재동기화 E2E critical paths (task 6.1).
 *
 * 이 파일은 s25 의 핵심 가치를 종단으로 못박는다: (1) 재로그인(새 세션·로컬 델타 부재) 이후에도
 * 서버 로스터로 기존 멤버 전량이 보이고(Req 3.2), (2) preexisting 멤버(이번 세션에서 add 한 적이
 * 없는 멤버) 제거가 reload 로 서버 진실에서 제외된다(Req 4.1, 델타 병합만으로는 불가한
 * removal-of-preexisting). 프로덕션은 이미 task 2.2·5.1 로 랜딩·커밋되었고 이 파일은 생산 코드를
 * 바꾸지 않는다(테스트 전용).
 *
 * ## 모킹 경계 = `global.fetch` 하나 (rolePersistence.e2e.test.tsx 패턴)
 * 브라우저 E2E 하네스가 없으므로 "E2E" 는 vitest+jsdom 전체 조립 통합 테스트다: 실제
 * `SessionProvider`(`/auth/me`→`/me/settings` 부트스트랩) → 실제 `CurrentWorkspaceProvider`
 * (`GET /workspaces` 로드) → 실제 `MembershipRoleProvider`(로드-시드) 를 결합하고, 그 아래 **실제**
 * `MemberManagementPanel` 을 게이팅·표시원·뮤테이션 결선 무변경으로 렌더한다. role/roleFor 는
 * **주입하지 않고** 오직 mocked `/workspaces` 응답 role(=owner) 로부터 실제 provider 를 통해
 * 복원된다. 로스터 표시원(`useWorkspaceMembers`)·뮤테이션(`useMemberActions`)·API 어댑터
 * (`memberApi`)·`apiClient` 모두 실물이며 `fetch` 만 스텁이다.
 *
 * 각 시나리오는 in-session 이력(recordOwner/recordSelfRole/add) 없이 **새 마운트**로 시작하므로
 * 재로그인/새로고침 직후를 시뮬레이션한다 — 표시되는 멤버의 유일한 출처는 서버 로스터다.
 *
 * ## 상태ful fetch mock (제거가 서버 진실을 바꿈)
 * DELETE `/workspaces/{id}/members/{uid}` 핸들러가 mock 이 클로징하는 가변 `roster` 배열에서 대상
 * 멤버를 제거하고 204 를 반환한다. 따라서 뮤테이션 이후 `roster.reload()` 가 발사하는 두 번째
 * GET `/members` 는 제거 반영된 로스터를 돌려준다 — 실서버의 remove→re-read 를 그대로 미러한다.
 *
 * Requirements: 3.2(재로그인 서버 시드 가시성), 4.1(뮤테이션 로스터 재동기화·removal-of-preexisting).
 * Design: §Testing Strategy E2E(Frontend), §단일 소스 표시 + 뮤테이션 재동기화.
 */

import { describe, it, expect, afterEach, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";

import { apiConfig } from "@/config";
import { SessionProvider } from "@/app/session/SessionProvider";
import { CurrentWorkspaceProvider } from "@/app/workspace-context/CurrentWorkspaceProvider";
import type { WorkspaceRole } from "@/shared/auth/roles";
import type { WorkspaceRead } from "@/shared/types/workspace";

import { MemberManagementPanel } from "@/features/workspace/components/MemberManagementPanel";
import { MembershipRoleProvider } from "@/features/workspace/context/membershipRoleSource";
import type { MemberRosterRow } from "@/features/workspace/api/types";

// --- fetch mock 유틸 (유일한 모킹 경계) — rolePersistence.e2e.test.tsx 아이디엄 재사용 -------------

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

/** id=WS_ID 단일 WS 를 `role` 로 반환하는 WorkspaceRead. 목록 응답 item 계약(role 이 provider 시드). */
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

/** 백엔드 `MemberRosterRead` 미러 행(user_id·name·email·role). 라벨은 `${user_id} ${name}`. */
function rosterRow(
  userId: number,
  name: string,
  role: MemberRosterRow["role"],
  email: string | null = null,
): MemberRosterRow {
  return { user_id: userId, name, email, role };
}

/** mock 이 관찰한 요청 로그 항목(비-공허성 단언용). */
interface CallLog {
  method: string;
  path: string;
}

/**
 * 전체 조립 부트스트랩 + 상태ful 로스터를 위한 fetch 스텁. 라우트:
 * - GET `/auth/me`(is_admin 주입) → `/me/settings` → `/workspaces`(role 주입 → provider-role 시드)
 * - GET `/workspaces/{id}/members` → 가변 `roster`(표시원). reload 마다 현재 서버 진실을 반환.
 * - GET `/workspaces/{id}/assignable-users` → 빈 목록(추가 폼 데이터).
 * - DELETE `/workspaces/{id}/members/{uid}` → `roster` 에서 대상 제거 후 204(서버 진실 변경).
 *
 * 반환 핸들의 `calls` 로 어떤 요청이 발사됐는지 단언한다(초기 GET·DELETE·reload GET 존재 검증).
 */
function installRosterFetch(options: {
  isAdmin?: boolean;
  role?: WorkspaceRole | null;
  roster: MemberRosterRow[];
}): { calls: CallLog[] } {
  const isAdmin = options.isAdmin ?? false;
  const role = options.role ?? "owner";
  let roster = [...options.roster];
  const calls: CallLog[] = [];

  const impl = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const p = pathOf(input);
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, path: p });

    if (method === "GET" && p === "/auth/me") {
      return json({ ...AUTH_USER, is_admin: isAdmin });
    }
    if (method === "GET" && p === "/me/settings") {
      return json(SETTINGS);
    }
    if (method === "GET" && p === "/workspaces") {
      return json({ items: [makeWorkspace(role)], total: 1 });
    }
    if (method === "GET" && p === `/workspaces/${WS_ID}/members`) {
      // 표시원: 현재 서버 로스터(reload 시 제거 반영된 최신 상태를 돌려줌).
      return json({ items: roster, total: roster.length });
    }
    if (method === "GET" && p === `/workspaces/${WS_ID}/assignable-users`) {
      return json({ items: [], total: 0 });
    }
    // DELETE `/workspaces/{WS_ID}/members/{uid}` → 서버 진실에서 제거 후 204(무본문).
    const del = p.match(new RegExp(`^/workspaces/${WS_ID}/members/(\\d+)$`));
    if (method === "DELETE" && del) {
      const uid = Number(del[1]);
      roster = roster.filter((r) => r.user_id !== uid);
      return new Response(null, { status: 204 });
    }
    return json({ code: "internal", message: `unexpected: ${method} ${p}` }, 500);
  };

  vi.stubGlobal("fetch", vi.fn(impl));
  return { calls };
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

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

// ===========================================================================================
// A. 재로그인 가시성 (Req 3.2 + design §Testing Strategy E2E)
//    새 마운트(로컬 세션 델타 부재) → 서버 로스터로 기존 멤버 전량이 표시된다.
// ===========================================================================================

describe("재로그인 가시성 E2E — 로컬 델타 없이 서버 로스터 전량 표시 (Req 3.2)", () => {
  it("owner 재로그인: 마운트 시 서버 로스터의 기존 멤버 전량이 이름으로 표시된다", async () => {
    // 로컬 add/record 이력이 전혀 없는 새 세션. role 은 오직 mocked /workspaces 응답에서만 온다.
    installRosterFetch({
      role: "owner",
      roster: [
        rosterRow(3, "Alice", "owner", "alice@example.com"),
        rosterRow(4, "Bob", "member"),
        rosterRow(5, "Carol", "member", "carol@example.com"),
      ],
    });

    renderAssembly(<MemberManagementPanel />);

    // 재로그인 이후 가시성의 핵심: 로컬 뮤테이션 이력 0 인데도 서버 로스터 멤버가 전량 보인다.
    // 표시원이 로컬 세션 델타였다면(과거 동작) 이 목록은 비어 이 단언들이 전부 실패한다.
    await waitFor(() => expect(screen.getByText("3 Alice")).toBeInTheDocument());
    expect(screen.getByText("4 Bob")).toBeInTheDocument();
    expect(screen.getByText("5 Carol")).toBeInTheDocument();
  });
});

// ===========================================================================================
// B. 제거 재동기화 (Req 4.1, removal-of-preexisting)
//    preexisting 멤버(이번 세션에서 add 한 적 없음) 제거 → reload 로 서버 진실에서 제외됨.
// ===========================================================================================

describe("제거 재동기화 E2E — preexisting 멤버 제거가 reload 로 목록에서 제외된다 (Req 4.1)", () => {
  it("기존 로스터 멤버 제거 → DELETE 후 로스터 reload 로 목록에서 사라진다(델타 병합 불가 케이스)", async () => {
    // 4 Bob 은 이번 세션에서 add 한 적이 없는 preexisting 멤버 — 서버 시드로만 존재한다.
    // 로컬 세션 델타 병합 방식이었다면 add 이력에 없는 4 Bob 을 애초에 표시할 수도, 제거할 수도 없다.
    const handle = installRosterFetch({
      role: "owner",
      roster: [rosterRow(3, "Alice", "owner"), rosterRow(4, "Bob", "member")],
    });

    renderAssembly(<MemberManagementPanel />);

    // 두 멤버 모두 서버 시드로 표시(4 Bob 이 preexisting 임을 확인).
    await waitFor(() => expect(screen.getByText("4 Bob")).toBeInTheDocument());
    expect(screen.getByText("3 Alice")).toBeInTheDocument();

    // preexisting 멤버 제거(라벨 = `${user_id} ${name} 제거`).
    await userEvent.click(screen.getByRole("button", { name: "4 Bob 제거" }));

    // 뮤테이션 후 reload 로 서버 진실(4 Bob 제외)이 재동기화되어 목록에서 사라진다.
    await waitFor(() => expect(screen.queryByText("4 Bob")).not.toBeInTheDocument());
    // 나머지 멤버는 그대로 유지된다(선택적 제거).
    expect(screen.getByText("3 Alice")).toBeInTheDocument();

    // --- 비-공허성: DELETE 가 실제로 발사되고 로스터 GET 이 초기+reload 로 최소 2회 호출됐다. ---
    const deleteCalls = handle.calls.filter(
      (c) => c.method === "DELETE" && c.path === `/workspaces/${WS_ID}/members/4`,
    );
    expect(deleteCalls).toHaveLength(1);
    const rosterGets = handle.calls.filter(
      (c) => c.method === "GET" && c.path === `/workspaces/${WS_ID}/members`,
    );
    expect(rosterGets.length).toBeGreaterThanOrEqual(2);
  });
});
