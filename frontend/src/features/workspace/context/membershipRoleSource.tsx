/**
 * MembershipRoleSource — 현재 사용자의 WS별 role 을 조달하는 **단일 소스**
 * (design.md "MembershipRoleSource (현재 WS role 조달 단일 소스)", requirements Req 1.4).
 *
 * 백엔드 `WorkspaceRead` 는 호출자 role 을 담지 않고, 계약에 role 직접 조회 엔드포인트도 없다.
 * 따라서 이 모듈은 조달 가능한 신호(생성 응답의 owner화·멤버 뮤테이션 응답의 자기 role 에코)만으로
 * role 을 **best-effort 축적**한다. 신호가 없으면 `null`(부재 → null). role 파생·번역 로직은 이
 * 모듈 **한 곳**에만 존재한다(단일 소스 규칙).
 *
 * ## s16 seam 결정 (tasks.md Implementation Notes D-1, 사용자 승인 2026-07-19)
 * s16 `CurrentWorkspaceProvider` 는 `role: null` 을 하드코딩하며 앰비언트 컨텍스트에 role 값을
 * 주입하는 seam 이 없다. 실제 seam 은 `RequireRole` 의 `currentRole` prop 이다. 그래서 이
 * `MembershipRoleSource` 를 **s18 소유 React 컨텍스트 provider + 훅**으로 구현하고
 * `Map<workspaceId, Role>` 상태를 보유한다. record 뮤테이션은 상태를 갱신해 그 role 을 읽는 패널을
 * 재렌더한다. owner 패널(task 4.2·5.1)은
 * `<RequireRole minimum={Role.OWNER} currentRole={useMembershipRoleSource().roleFor(wsId)}>` 로
 * 게이팅한다. s16 파일은 수정하지 않는다.
 *
 * admin override 는 role 에 접합하지 않는다 — s16 `RequireRole`/`RequireAdmin` 이 세션 `is_admin`
 * 으로 별도 통과시킨다(INV-3). 이 모듈은 admin/세션을 알지 못한다.
 *
 * Requirements: 1.4 (단일 role 소스, best-effort 신호 조달·부재 시 null).
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactElement, ReactNode } from "react";

import { Role, memberRoleToRole as translateMemberRole } from "@/shared/auth/roles";
import { CurrentWorkspaceContext } from "@/app/workspace-context/CurrentWorkspaceProvider";

/**
 * role 번역 단일 소스 재-export shim. `memberRoleToRole` 소유는 `@/shared/auth/roles` 로 이관되어
 * {@link Role} enum 과 co-locate 한다(단일 소스 규칙). 기존 importer(예: `CurrentWorkspaceIndicator`,
 * `useMemberActions` 및 테스트)의 후방 호환을 위해 여기서 그대로 재-export 한다 — 동일 함수 참조.
 */
export { memberRoleToRole } from "@/shared/auth/roles";

/**
 * 현재 사용자의 WS별 확인된 role 을 축적하는 단일 소스 인터페이스(design.md Contracts).
 * s16 role 주입 seam(`RequireRole` `currentRole`)이 `roleFor` 로 소비한다.
 */
export interface MembershipRoleSource {
  /** 확인된 role, 신호 부재 시 `null`(S2 best-effort). */
  roleFor(workspaceId: number): Role | null;
  /** WS 생성 응답 → 생성자를 해당 WS 의 owner 로 기록(요구 2.3). */
  recordOwner(workspaceId: number): void;
  /** 멤버 뮤테이션 응답의 자기 role 에코를 해당 WS role 로 반영(덮어쓰기). */
  recordSelfRole(workspaceId: number, role: Role): void;
  /**
   * 로드-시드: 목록 응답의 `[wsId, role]` 항목을 Map upsert 로 반영한다(s24, Req 5.2·5.3).
   * 목록에 있는 WS 는 서버 권위값으로 **덮어쓰고**(server-authoritative), 목록에 없는 WS 의
   * in-session 기록은 **보존**한다(비목록 항목 무변경). WS 당 단일 Map 항목 → 단일 role 값만
   * 노출(모순된 두 값 동시 노출 금지). 시드는 대체가 아니라 보강이며 `recordOwner`/`recordSelfRole`
   * 동작을 바꾸지 않는다(Req 5.1).
   */
  seedRoles(entries: Iterable<readonly [number, Role]>): void;
}

/**
 * 컨텍스트. provider 밖 소비를 감지하기 위해 기본값을 `null` 로 둔다
 * ({@link useMembershipRoleSource} 가드 — s16 `useCurrentWorkspace` 가드 idiom 미러).
 */
const MembershipRoleContext = createContext<MembershipRoleSource | null>(null);

/**
 * s18 소유 role 소스 provider. `Map<workspaceId, Role>` 상태를 보유하며 record 뮤테이션 시
 * 새 Map 으로 교체해(ref 은밀 변형 금지) 소비자 재렌더를 트리거한다. status 와 무관하게 항상
 * `children` 을 렌더한다. s16 `ProviderComponent`(`@/app/providers`)와 형태 호환이다.
 */
export function MembershipRoleProvider({ children }: { children: ReactNode }): ReactElement {
  const [roles, setRoles] = useState<Map<number, Role>>(() => new Map());

  const recordRole = useCallback((workspaceId: number, role: Role): void => {
    // 함수형 업데이트 + 새 Map 으로 role 을 덮어쓴다(불변 갱신 → 재렌더 보장).
    setRoles((prev) => {
      const next = new Map(prev);
      next.set(workspaceId, role);
      return next;
    });
  }, []);

  const recordOwner = useCallback(
    (workspaceId: number): void => {
      recordRole(workspaceId, Role.OWNER);
    },
    [recordRole],
  );

  const recordSelfRole = useCallback(
    (workspaceId: number, role: Role): void => {
      recordRole(workspaceId, role);
    },
    [recordRole],
  );

  // 로드-시드 upsert: 목록 항목은 서버값으로 덮어쓰고(server-authoritative) 비목록 항목은 보존한다.
  // 함수형 업데이트 + 새 Map(불변 갱신 → 재렌더 보장). in-session 기록을 대체하지 않고 보강한다.
  const seedRoles = useCallback((entries: Iterable<readonly [number, Role]>): void => {
    setRoles((prev) => {
      const next = new Map(prev);
      for (const [id, role] of entries) {
        next.set(id, role);
      }
      return next;
    });
  }, []);

  // 상위 CurrentWorkspaceProvider(=app) 를 **옵셔널**로 읽는다. provider 밖(standalone 단위
  // 테스트)에서는 null → 시드하지 않고 기존 in-session 전용 동작을 보존한다(Req 5.1). 실제 앱은
  // MembershipRoleProvider 가 CurrentWorkspaceProvider **하위**에 마운트되어 non-null 이다(mount order).
  const wsContext = useContext(CurrentWorkspaceContext);
  const workspaces = wsContext?.workspaces;

  useEffect(() => {
    if (workspaces === undefined) {
      // standalone(컨텍스트 null): 시드 없음.
      return;
    }
    // role≠null 항목만 [id, Role] 로 시드한다. role=null/undefined(비멤버·미시드)는 제외하고
    // admin override 는 접합하지 않는다(멤버십 role 문자열만 시드, Req 2.4/5.4·INV-3). 번역은
    // memberRoleToRole 단일 소스만 사용한다.
    const entries: [number, Role][] = [];
    for (const ws of workspaces) {
      if (ws.role != null) {
        entries.push([ws.id, translateMemberRole(ws.role)]);
      }
    }
    seedRoles(entries);
    // 커밋된 workspaces 배열 참조에 반응한다(새 로드 = 새 배열). seedRoles 는 local Map 만 갱신하고
    // 부모의 workspaces 참조를 바꾸지 않으므로 자기 시드로 재발화하지 않는다(무한 루프 없음).
  }, [workspaces, seedRoles]);

  const value = useMemo<MembershipRoleSource>(
    () => ({
      roleFor: (workspaceId: number): Role | null => roles.get(workspaceId) ?? null,
      recordOwner,
      recordSelfRole,
      seedRoles,
    }),
    [roles, recordOwner, recordSelfRole, seedRoles],
  );

  return (
    <MembershipRoleContext.Provider value={value}>{children}</MembershipRoleContext.Provider>
  );
}

/**
 * role 소스를 읽는다. `MembershipRoleProvider` 밖에서 호출되면(기본값 `null`) 조립 실수를 조기에
 * 드러내도록 명확한 오류를 던진다(s16 `useCurrentWorkspace` 가드 idiom 미러).
 */
export function useMembershipRoleSource(): MembershipRoleSource {
  const value = useContext(MembershipRoleContext);
  if (value === null) {
    throw new Error("useMembershipRoleSource must be used within a MembershipRoleProvider");
  }
  return value;
}

/**
 * role 소스를 **옵셔널**로 읽는다(provider 밖이면 던지지 않고 `null`).
 *
 * 조립 실수를 조기에 드러내야 하는 뮤테이션 경로는 던지는 {@link useMembershipRoleSource} 를 쓴다.
 * 반면 전역 헤더의 현재 WS 배지처럼 provider 유무와 무관한 여러 마운트 컨텍스트(예: 라우팅 프레임
 * 단위 테스트)에서 렌더될 수 있는 **표시 전용** 컴포넌트는 이 옵셔널 접근자로 읽어, 조립이 미비하면
 * 조용히 배지를 숨긴다(앱 크래시 방지). role 파생·번역 단일 소스 규칙은 그대로 유지된다.
 */
export function useMembershipRoleSourceOptional(): MembershipRoleSource | null {
  return useContext(MembershipRoleContext);
}
