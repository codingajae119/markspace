/**
 * 현재 워크스페이스 + 내 역할(role) 전역 표시 배지.
 *
 * 문제 배경: 워크스페이스 탭에서 WS 를 선택해도(현재 WS 컨텍스트는 라우터 상위에 마운트되어 탭 전환
 * 시 유지됨) 어느 WS 가 활성인지 화면에 **표시가 전혀 없어** 문서 탭 등으로 전이하면 선택을 확인할 수
 * 없었다. 이 컴포넌트는 전역 헤더(`AppHeaderNav`)에 놓여 **모든 인증 화면에서 항상** 현재 WS 이름과
 * 내 역할(owner/member)을 노출한다.
 *
 * 데이터 출처(둘 다 옵셔널 읽기 — provider 밖에서도 던지지 않음):
 * - 현재 WS 이름·id·status: s16 앰비언트 `CurrentWorkspaceContext`.
 * - 역할: s18 `MembershipRoleSource`. 목록 응답의 `WorkspaceRead.role` 로 시드되며(s24 로드-시드)
 *   WS 생성(→owner)·멤버 뮤테이션 응답 에코로도 갱신된다.
 *
 * `role === null` 의 의미(목록 읽기 전역 개방 이후): 목록은 **모든** 워크스페이스를 싣고 비멤버
 * 항목의 `role` 만 null 이므로, null 은 "신호 부재"가 아니라 **비멤버 확정**이다. 이 배지는
 * `status === "loading"` 동안 렌더를 보류하므로 표시 시점에는 목록이 이미 로드돼 있다. 따라서
 * null 을 읽기 전용 열람자, 즉 "viewer" 로 표시한다(owner/member 와 달리 편집 권한 없음).
 *
 * role 번역은 `MembershipRoleSource` 단일 소스(`memberRoleToRole`)와 `Role` enum 을 그대로 소비하며
 * 여기서 문자열↔enum 변환을 재구현하지 않는다.
 */

import { useContext, type ReactElement } from "react";

import { Role } from "@/shared/auth/roles";
import { CurrentWorkspaceContext } from "@/app/workspace-context/CurrentWorkspaceProvider";

import { useMembershipRoleSourceOptional } from "../context/membershipRoleSource";

/** role → 배지 라벨(사용자 요청대로 owner/member 를 명시) + 색조. */
const ROLE_BADGE: Record<Role, { label: string; className: string }> = {
  [Role.OWNER]: { label: "owner", className: "bg-amber-100 text-amber-800" },
  [Role.MEMBER]: { label: "member", className: "bg-sky-100 text-sky-800" },
};

/** 멤버십 role 부재(=비멤버) 시 표시. 읽기만 가능한 열람자이므로 "viewer" 로 명시한다. */
const VIEWER_ROLE_BADGE = {
  label: "viewer",
  className: "bg-slate-100 text-slate-600",
} as const;

/** 전역 헤더에 놓이는 현재 WS·역할 표시. 선택된 WS 가 없으면 안내 배지를 표시한다. */
export function CurrentWorkspaceIndicator(): ReactElement | null {
  // 옵셔널 읽기: provider 밖(예: 라우팅 프레임 단위 테스트)이면 조용히 숨긴다.
  const workspaceCtx = useContext(CurrentWorkspaceContext);
  const roleSource = useMembershipRoleSourceOptional();

  if (workspaceCtx === null) {
    return null;
  }

  const { status, currentWorkspace } = workspaceCtx;

  // 목록 로드 중에는 표시를 보류한다(깜빡임 방지).
  if (status === "loading") {
    return null;
  }

  // 선택된 WS 가 없음: 항상 표시 요구에 맞춰 "미선택"을 명시한다(빈 화면 오해 방지).
  if (currentWorkspace === null) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500"
        aria-label="현재 워크스페이스: 미선택"
      >
        워크스페이스 미선택
      </span>
    );
  }

  const role = roleSource?.roleFor(currentWorkspace.id) ?? null;
  const badge = role !== null ? ROLE_BADGE[role] : VIEWER_ROLE_BADGE;

  return (
    <span
      className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs"
      aria-label={`현재 워크스페이스: ${currentWorkspace.name}, 역할: ${badge.label}`}
    >
      <span className="font-medium text-slate-800">{currentWorkspace.name}</span>
      <span className={`rounded px-1.5 py-0.5 font-semibold ${badge.className}`}>{badge.label}</span>
    </span>
  );
}
