/**
 * 워크스페이스 role 위계 — 백엔드 `app/common/permissions.py` 의 `Role(IntEnum)` 정확 미러.
 *
 * 정수 순서가 곧 권한 포함 관계다: `OWNER(3) ≥ EDITOR(2) ≥ VIEWER(1)`.
 * 읽기 전용 UI 는 최소 요구 role 을 `VIEWER` 로 표현한다. 수치(1/2/3)는 프론트에서
 * 위계 비교(`currentRole >= minimum`)를 간결히 하기 위한 편의이며, 불변식은 owner 가
 * 가장 높다는 **순서**다(Req 6.1·6.2, INV-1).
 *
 * 권한 판정은 워크스페이스 단위 role 로만 수행하며 문서별 개별 권한 개념은 없다(AC 6.1, INV-1).
 */
export enum Role {
  VIEWER = 1,
  EDITOR = 2,
  OWNER = 3,
}

/**
 * 멤버 role 의 API 직렬화용 문자열 유니온 — 백엔드 `MemberRole`(str Enum) 미러.
 *
 * 값은 백엔드 `workspace_member.role` ENUM(owner/editor/viewer)과 동일하다. 위계 비교용
 * {@link Role}(enum, VIEWER<EDITOR<OWNER)과는 별개다: 요청/응답 직렬화에는 이 문자열 유니온을,
 * 권한 게이팅에는 {@link Role} 을 사용한다. features 계층의 `MemberRole` 과 구조적으로 동일하다.
 */
export type WorkspaceRole = "owner" | "editor" | "viewer";

/**
 * 백엔드 role 문자열("owner"|"editor"|"viewer")을 {@link Role} enum 으로 번역하는 **단일 소스**.
 * {@link Role} enum 과 co-locate 하여 모든 role 번역을 여기 한 곳에만 둔다 — app·features 양측이
 * 이 함수를 소비하고, 패널·어댑터가 산발적으로 문자열↔enum 변환을 재구현하지 않는다.
 */
export function memberRoleToRole(role: WorkspaceRole): Role {
  switch (role) {
    case "owner":
      return Role.OWNER;
    case "editor":
      return Role.EDITOR;
    case "viewer":
      return Role.VIEWER;
  }
}
