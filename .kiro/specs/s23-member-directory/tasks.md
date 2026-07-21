# Implementation Plan

> 이 기능은 기존 워크스페이스 패키지의 **내부 확장**(읽기 전용)이다. 신규 테이블·마이그레이션·provider 배선 없음.
> 백엔드 그룹(1·2)과 프론트 그룹(3·4·5)은 `AssignableUserRead` 계약 shape가 design 에 동결돼 있어
> 런타임 의존 없이 병렬 진행 가능하다(프론트 테스트는 `@/shared/api/client` mock).

- [ ] 1. 백엔드: 배정 가능 사용자 조회 계약·데이터 접근·엔드포인트
- [x] 1.1 narrow 응답 스키마 추가
  - `workspace/schemas.py` 에 `AssignableUserRead(ORMReadModel)` 추가: `id`·`name`·`email: str | None` 선언 필드만.
  - `ORMReadModel`(from_attributes) 상속으로 `User` ORM 에서 선언 필드만 직렬화 — `login_id`·`password_hash`·상태 flag·타임스탬프는 직렬화 대상에서 원천 제외.
  - email 이 null 인 사용자도 스키마 검증 통과(`email: str | None`), 제외하지 않음.
  - 관찰 가능한 완료: `AssignableUserRead.model_validate(user)` 가 `id`/`name`/`email` 3개 필드만 담은 모델을 반환하고, 계정 필드 접근 시 존재하지 않음.
  - _Requirements: 1.2, 1.3_
  - _Boundary: AssignableUserRead_

- [x] 1.2 (P) 배정 가능 anti-join 저장소 쿼리 추가
  - `workspace/repository.py` 의 `MembershipRepository` 에 `list_assignable_users(db, workspace_id, limit, offset) -> tuple[list[User], int]` 추가.
  - 공유 필터 헬퍼로 items 조회와 count 를 단일화(드리프트 차단): `is_admin=False`·`is_active=True`·`is_deleted=False`·상관 `~exists(WorkspaceMember where workspace_id 일치 and user_id==User.id)`.
  - items 는 `ORDER BY User.id`·`limit`·`offset` 적용, `total` 은 **동일 필터** count(무필터 `list_paginated`·`user_exists` 관례 복제 금지).
  - 관찰 가능한 완료: admin·비활성·삭제·기존 멤버가 결과에서 제외되고, `total` 이 페이지 크기와 무관하게 배정 가능 총수와 일치하며 순서가 `user.id` 오름차순으로 결정적.
  - _Requirements: 1.1, 1.5_
  - _Boundary: MembershipRepository_

- [x] 1.3 배정 가능 조회 서비스 메서드 추가
  - `workspace/service.py` 의 `MembershipService` 에 `list_assignable_users(db, workspace_id, limit, offset) -> Page[AssignableUserRead]` 추가.
  - repo `(items, total)` → `Page(items=[AssignableUserRead.model_validate(u) for u in items], total=total)` 매핑. 인증 게이팅은 미보유(호출부 책임 — 기존 관례).
  - 배정 가능 사용자가 없으면 `Page(items=[], total=0)` 반환(오류 아님).
  - 관찰 가능한 완료: 서비스 호출이 배정 가능 총수를 `total` 로 담은 `Page[AssignableUserRead]` 를 반환하고, 빈 경우 예외 없이 빈 페이지를 돌려줌.
  - _Requirements: 1.1, 1.4_
  - _Depends: 1.1, 1.2_

- [x] 1.4 owner-gated 조회 엔드포인트 결선
  - `workspace/router.py` 에 `GET /workspaces/{id}/assignable-users` 추가: `require_ws_role(Role.OWNER)`(경로 `{id}`→`workspace_id` 어댑터, `common` 직접 사용 금지) + `limit: Query(50, ge=1)`·`offset: Query(0, ge=0)`.
  - 기존 `get_membership_service` provider 재사용(신규 배선 없음). 존재하지 않는 workspace 는 게이트 단계에서 비-멤버→403(404 로 존재 노출 안 함).
  - 관찰 가능한 완료: `GET /api/1.0/workspaces/{id}/assignable-users` 가 owner 에게 200+`Page[AssignableUserRead]`, 비-owner 에게 403, 미인증에게 401, 잘못된 limit/offset 에 422 를 반환.
  - _Requirements: 1.1, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4_
  - _Depends: 1.3_

- [ ] 2. 백엔드 검증: 필터·누출·게이팅·페이지네이션
- [x] 2.1 (P) 저장소·스키마 단위 테스트
  - repo 필터 경계: admin·비활성·삭제·기존 멤버 각 1건이 제외되고 배정 가능만 반환됨을 검증.
  - `total` 정확성: 배정 가능 총수 > 페이지 크기일 때 `total` 이 총수와 일치(무필터 count 회귀 방지). 순서 `ORDER BY user.id` 결정성 검증.
  - narrow 직렬화: `AssignableUserRead` 응답에 `login_id`·상태 flag·타임스탬프·`password_hash` 부재, email null 통과.
  - 관찰 가능한 완료: pytest 단위 스위트가 필터 제외·total 정확성·순서 결정성·누출 부재 케이스에서 통과.
  - _Requirements: 1.1, 1.2, 1.3, 1.5_
  - _Boundary: MembershipRepository, AssignableUserRead_
  - _Depends: 1.1, 1.2_

- [x] 2.2 게이팅·페이지네이션 통합 테스트
  - 게이팅 매트릭스: owner→200, editor/viewer/비멤버→403, admin(비-owner)→200, 미인증→401.
  - 존재하지 않는 workspace→403(404 로 존재 노출 안 함, anti-enumeration). limit/offset 경계에서 items/total 일관, 배정 가능 0명→`{items:[],total:0}`.
  - 관찰 가능한 완료: FastAPI 통합 스위트가 전체 게이팅 매트릭스와 페이지네이션 경계에서 기대 상태코드·응답 봉투로 통과.
  - _Requirements: 1.4, 1.5, 2.1, 2.2, 2.3, 2.4_
  - _Depends: 1.4_

- [ ] 3. (P) 프론트: 배정 가능 조회 계층
  - design 에 동결된 `AssignableUserRead` 계약 shape 를 미러 — 백엔드 런타임 없이 병렬 진행(테스트는 `@/shared/api/client` mock).
- [ ] 3.1 프론트 타입·조회 어댑터 추가
  - `features/workspace/api/types.ts` 에 `AssignableUser { id: number; name: string; email: string | null }` 추가.
  - `features/workspace/api/assignableUserApi.ts` 신규: `listAssignable(workspaceId, {limit,offset})` 가 `URLSearchParams` 로 경로 조립(기존 관례) 후 `apiClient.get<Page<AssignableUser>>` 호출. base URL·전역 401 은 `apiClient` 소유.
  - 관찰 가능한 완료: `assignableUserApi.listAssignable(1, {limit:50, offset:0})` 가 `/workspaces/1/assignable-users?limit=50&offset=0` 경로로 `apiClient.get` 를 호출하고 `Page<AssignableUser>` 를 반환.
  - _Requirements: 3.1_
  - _Boundary: assignableUserApi, workspace/api/types_

- [ ] 3.2 배정 가능 조회 훅 추가
  - `features/workspace/hooks/useAssignableUsers.ts` 신규: `status(loading|ready|error)`·`users`·`total`·`error` 상태 + `reload()`. `useVersionHistory` 형태 미러(마운트 fetch·인-플라이트 가드·`mountedRef` 언마운트 가드·`toApiError` 정규화).
  - `workspaceId === null` 이면 fetch 금지(안정 초기값). 조회 실패는 `error` 에 저장하고 `status="error"`.
  - 관찰 가능한 완료: 마운트 시 첫 페이지를 fetch 해 `status="ready"`+`users`/`total` 노출, 실패 시 `status="error"`+`error` 노출, `reload()` 호출이 재-fetch 를 트리거.
  - _Requirements: 3.1, 3.4, 3.6, 4.1_
  - _Boundary: useAssignableUsers_
  - _Depends: 3.1_

- [ ] 3.3 (P) 배정 가능 선택 컴포넌트 추가
  - `features/workspace/components/AssignableUserSelect.tsx` 신규(순수 표시): props `users`·`status`·`error`·`value`·`onChange`·`disabled`.
  - 렌더 분기: `loading`→`Spinner`(선택 비활성), `ready && users.length===0`→`EmptyState`("배정 가능한 사용자가 없습니다", 비활성), `error`→`ErrorMessage`, 그 외 `select` 옵션 `이름 (email)`(email 빈값이면 이름만). 데이터·reload 는 상위 소유(역할 선택은 별도 `RoleSelect`).
  - 관찰 가능한 완료: status 별로 Spinner/EmptyState/ErrorMessage/select 중 정확히 하나를 렌더하고, 옵션 선택 시 `onChange(userId)` 호출.
  - _Requirements: 3.1, 3.5, 3.6, 4.1_
  - _Boundary: AssignableUserSelect_
  - _Depends: 3.1_

- [ ] 4. 프론트 통합: 멤버 관리 폼 선택 UI 결선
- [ ] 4.1 raw user_id 입력 → 선택 UI 교체·추가 후 reload
  - `components/MemberManagementPanel.tsx` 의 `MemberManagementContent` 에서 `<input id="member-add-user-id">` 제거, `AssignableUserSelect`(선택 사용자) + 기존 `RoleSelect`(역할)로 교체하고 `useAssignableUsers(workspaceId)` 결선.
  - 제출: `await add(workspaceId, { user_id, role })` → 선택 초기화 → 성공/실패 무관 `void assignable.reload()`(단일 경로). 추가 버튼 disabled 조건: `pending || status !== "ready" || users.length === 0 || selectedUserId === null`.
  - 오류 표면화: 추가 실패는 `useMemberActions.error`, 조회 실패는 `assignable.error` 둘 다 `ErrorMessage`(클라 게이팅으로 억제 금지). 상위 `RequireRole minimum={OWNER} currentRole={roleFor(id)}` 게이팅은 변경 없음. `useMemberActions` 비낙관 계약(성공 시에만 append)은 그대로 재사용.
  - 관찰 가능한 완료: owner 가 목록에서 사용자·role 선택 후 추가하면 멤버가 추가되고 배정 가능 목록이 refetch 로 갱신되며, 실패 시 로컬 상태가 시도 이전과 동일하게 유지됨.
  - _Requirements: 3.2, 3.3, 3.4, 4.2, 4.3_
  - _Depends: 3.2, 3.3_

- [ ] 5. 프론트 검증: 선택·상태·오류 흐름
- [ ] 5.1 멤버 관리 UI 상태·흐름 테스트
  - 성공 경로: 선택→역할→추가 성공 후 해당 사용자가 목록에서 사라짐(reload). 빈 상태: 0명→`EmptyState`+추가 버튼 disabled. 로딩: `status=loading`→`Spinner`+추가 방지.
  - 오류 경로: 조회 403/401→`ErrorMessage`(게이팅으로 억제 안 됨); 추가 stale-409→`ErrorMessage`(409)+목록 refetch; 추가 실패 시 로컬 상태 무변경. `vi.mock` 대상은 hooks 또는 `@/shared/api/client`(기존 `MemberManagementPanel.test` 관례), `RequireRole`/`RoleSelect`/`ErrorMessage` 는 실제 사용.
  - 관찰 가능한 완료: Vitest + Testing Library 스위트가 성공·빈·로딩·조회오류·stale-409·추가실패 롤백 케이스에서 통과.
  - _Requirements: 3.1, 3.4, 3.5, 3.6, 4.1, 4.2, 4.3_
  - _Depends: 4.1_

## Implementation Notes

- **2.1 커버리지 위치**: 저장소 단위 테스트(필터 제외·total 정확성·순서 결정성·상관 NOT EXISTS 정확성)는 task 1.2 커밋(`test_membership_repository.py`)에, narrow 직렬화 스키마 테스트(계정 필드/타임스탬프/`password_hash` 비노출·email null 통과)는 task 1.1 커밋(`test_schemas.py:176-232`)에 이미 존재한다. 2.1 은 신규 코드 없이 이 커버리지가 수용 기준을 충족함을 검증(36 passed)해 완료 처리했다.
