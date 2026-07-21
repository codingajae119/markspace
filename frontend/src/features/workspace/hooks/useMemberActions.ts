/**
 * 멤버 관리 뮤테이션 useCase 훅 (design.md "features/workspace/hooks → useMemberActions").
 *
 * `memberApi` 로 멤버 추가·role 변경·제거를 수행하고, 확인된 결과만 **로컬** `members` 상태에 축적한다.
 *
 * ## S1 전제 (로컬 상태는 권위 있는 전체 열거가 아님)
 * 계약에 멤버 목록 조회(GET) 엔드포인트가 없다(design.md Contract Constraints S1). 따라서 이 훅의
 * `members` 는 뮤테이션 응답(`MemberRead`)으로 **이 세션에서 확인된 멤버만** 담는 best-effort 뷰이며,
 * 워크스페이스의 권위 있는 전체 멤버 열거가 아니다. 소비 UI(4.2 MemberManagementPanel)는 이 열거 한계를
 * 사용자에게 명시해야 한다(Req 3.7).
 *
 * 성공 시에만 로컬 상태를 반영한다:
 * - add    → 반환된 `MemberRead` 를 `members` 에 append(Req 3.1)
 * - changeRole → user_id 매칭 멤버를 반환된 `MemberRead` 로 교체(Req 3.2)
 * - remove → 대상 user_id 멤버를 제외(Req 3.3)
 *
 * 실패(`ApiError`) 시 `members` 를 시도 이전과 **정확히 동일**하게 남긴다(참조까지 불변) — 낙관적/부분
 * 반영 잔여가 없다(Req 3.6, 롤백). 실패는 `error` 로 보관해 폼이 `ErrorMessage` 로 인라인 표시한다.
 * 뮤테이션은 성공 응답을 받은 뒤에만 상태를 갱신하므로 롤백은 "실패 시 상태를 건드리지 않음"으로 성립한다.
 *
 * ## self role 에코 (role 소스 단일 반영)
 * 뮤테이션 대상 user_id 가 현재 세션 사용자와 같으면(add·changeRole 은 role 을 동반), 자기 role 을
 * `useMembershipRoleSource().recordSelfRole(wsId, memberRoleToRole(role))` 로 반영한다(Req 3.7).
 * MemberRole 문자열→Role enum 번역은 `memberRoleToRole` 단일 지점만 사용하고 여기서 재구현하지 않는다.
 * 세션 사용자 id 는 `useSession()` 의 `status==="authenticated"` 일 때만 확정한다(그 외엔 self 판정 없음).
 *
 * 계약 경계(모두 소비, 재구현 금지): fetch·에러 파싱은 `memberApi`→s16 `apiClient` 위임, role 파생·번역은
 * `MembershipRoleSource` 단일 소스. 응집 액션 객체를 반환해 소비 패널이 결선한다.
 *
 * Requirements: 3.1(추가·반영), 3.2(role 변경·반영), 3.3(제거·반영), 3.4(role 3값),
 * 3.6(실패 오류·롤백), 3.7(self role 에코·열거 한계).
 */

import { useCallback, useState } from "react";

import { memberApi } from "../api/memberApi";
import type { MemberCreate, MemberRead, MemberRole, MemberUpdate } from "../api/types";
import { useMembershipRoleSource } from "../context/membershipRoleSource";
import { useSession } from "@/app/session/useSession";
import { ApiError } from "@/shared/api/errors";
import { memberRoleToRole } from "@/shared/auth/roles";

/** useMemberActions 가 노출하는 멤버 뮤테이션 액션·로컬 상태·진행/오류. */
export interface UseMemberActionsResult {
  /** 이 세션에서 확인된 멤버(S1: 권위 있는 전체 열거 아님). */
  members: MemberRead[];
  /** 멤버 추가. 성공 시 반환 `MemberRead` 를 로컬 상태에 append. */
  add: (workspaceId: number, body: MemberCreate) => Promise<void>;
  /** 멤버 role 변경. 성공 시 매칭 멤버를 갱신. */
  changeRole: (workspaceId: number, uid: number, body: MemberUpdate) => Promise<void>;
  /** 멤버 제거. 성공 시 로컬 상태에서 제외. */
  remove: (workspaceId: number, uid: number) => Promise<void>;
  /** 뮤테이션 진행 중 여부(중복 제출 방지). */
  pending: boolean;
  /** 직전 뮤테이션 실패의 정규화된 오류(없으면 null). */
  error: ApiError | null;
}

/**
 * 멤버 추가·role 변경·제거 뮤테이션과 로컬 멤버 상태(S1)·self role 에코(role 소스)·진행/오류 상태를
 * 노출한다.
 */
export function useMemberActions(): UseMemberActionsResult {
  const { recordSelfRole } = useMembershipRoleSource();
  const session = useSession();
  const [members, setMembers] = useState<MemberRead[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  // 현재 세션 사용자 id — 인증 상태일 때만 확정(그 외엔 self 판정 없음).
  const selfUserId = session.status === "authenticated" ? session.user.id : null;

  // 대상 user_id 가 자기 자신이면 role 을 role 소스에 에코(add·changeRole 만 role 을 동반).
  const echoSelfRole = useCallback(
    (workspaceId: number, targetUserId: number, role: MemberRole): void => {
      if (selfUserId !== null && targetUserId === selfUserId) {
        recordSelfRole(workspaceId, memberRoleToRole(role));
      }
    },
    [selfUserId, recordSelfRole],
  );

  const add = useCallback(
    async (workspaceId: number, body: MemberCreate): Promise<void> => {
      setPending(true);
      setError(null);
      try {
        const created = await memberApi.add(workspaceId, body);
        // 성공 시에만 로컬 상태 반영(실패 시 상태 무변경 = 롤백).
        setMembers((prev) => [...prev, created]);
        echoSelfRole(workspaceId, created.user_id, created.role);
      } catch (caught) {
        if (caught instanceof ApiError) {
          setError(caught);
        }
      } finally {
        setPending(false);
      }
    },
    [echoSelfRole],
  );

  const changeRole = useCallback(
    async (workspaceId: number, uid: number, body: MemberUpdate): Promise<void> => {
      setPending(true);
      setError(null);
      try {
        const updated = await memberApi.changeRole(workspaceId, uid, body);
        // user_id 매칭 멤버만 갱신 응답으로 교체(그 외 원소 참조 보존).
        setMembers((prev) =>
          prev.map((member) => (member.user_id === uid ? updated : member)),
        );
        echoSelfRole(workspaceId, uid, updated.role);
      } catch (caught) {
        if (caught instanceof ApiError) {
          setError(caught);
        }
      } finally {
        setPending(false);
      }
    },
    [echoSelfRole],
  );

  const remove = useCallback(
    async (workspaceId: number, uid: number): Promise<void> => {
      setPending(true);
      setError(null);
      try {
        await memberApi.remove(workspaceId, uid);
        // 성공 시에만 대상 제외(remove 는 role 을 동반하지 않아 self 에코 없음).
        setMembers((prev) => prev.filter((member) => member.user_id !== uid));
      } catch (caught) {
        if (caught instanceof ApiError) {
          setError(caught);
        }
      } finally {
        setPending(false);
      }
    },
    [],
  );

  return { members, add, changeRole, remove, pending, error };
}
