# Implementation Plan

## 1. 백엔드: 로스터 데이터·스키마 레이어

- [x] 1.1 (P) MemberRosterRead narrow 읽기 모델 추가
  - `BaseModel` 상속으로 `user_id`·`name`·`email`(nullable)·`role`(`MemberRole`) 4필드만 선언하고 `__all__` 에 등록한다(join 프로젝션이므로 `ORMReadModel` from_attributes 미사용, 선언 필드만 직렬화).
  - 임의 User 유사 dict 에 `login_id`·`password_hash`·상태 flag·타임스탬프를 주입해도 응답에 누출되지 않고, `email` 은 없으면 `null` 로 보존됨을 단위 테스트로 확인한다.
  - 관찰 가능: 스키마 인스턴스가 정확히 `{user_id, name, email, role}` 만 직렬화하며 그 외 필드는 존재하지 않는다.
  - _Requirements: 1.2, 2.6_
  - _Boundary: MemberRosterRead (backend schema)_

- [x] 1.2 (P) MembershipRepository.list_members 소속 전량 조회 추가
  - `User` ⋈ `WorkspaceMember`(ON `user_id`, WHERE `workspace_id`) inner-join 으로 `(User, role)` 목록을 `User.id` 오름차순·limit/offset 적용해 반환하고, 소속 멤버십 전체 개수를 별도 count(limit/offset 무관, 동일 `workspace_id` 필터만 공유)로 함께 반환한다.
  - **소프트삭제 필터를 적용하지 않는다**(`is_active`/`is_deleted` 미필터) — 비활성·삭제 상태 멤버도 role 과 함께 포함한다(INV-4 물리삭제 없음으로 inner-join FK dangling 없음). role 은 원시 문자열 그대로 반환하고 위계 비교·bypass 판정은 하지 않는다.
  - 단위 테스트로 (a) 비활성·삭제 멤버가 role 과 함께 포함, (b) owner 자신 포함, (c) `User.id` 오름차순 결정적 순서, (d) total 은 소속 전체 개수(페이지 크기 초과 시에도 limit/offset 무관)를 확인한다.
  - 관찰 가능: 대상 워크스페이스의 모든 멤버십이 `(User, role)` 로 결정적 순서로 반환되고, total 이 페이지 경계와 무관하게 전체 멤버 수를 보고한다.
  - _Requirements: 1.1, 1.3, 1.5, 1.6_
  - _Boundary: MembershipRepository (backend data)_

## 2. 백엔드: 서비스·라우트 조립

- [x] 2.1 MembershipService.list_members 로 narrow Page 직렬화
  - 리포지토리 `(User, role)` 행을 각각 `MemberRosterRead(user_id=user.id, name=user.name, email=user.email, role=MemberRole(role))` 로 **명시 생성**하고(join 프로젝션이므로 `model_validate` 의 id→user_id 리네임 모호 회피), 리포지토리가 계산한 total 을 그대로 `Page[MemberRosterRead]` 로 반환한다(items 길이 아님).
  - role 문자열→`MemberRole` 정규화·email null 보존이 정확하고, 멤버 0명이라도 `Page(items=[], total=…)` 로 방어적으로 매핑됨을 단위 테스트로 확인한다(게이팅은 서비스 책임 아님).
  - 관찰 가능: 서비스가 `Page[MemberRosterRead]` 를 반환하고 각 item 이 `user_id`·name·email·role 을 담으며 순서·total 은 리포지토리 계약을 승계한다.
  - _Depends: 1.1, 1.2_
  - _Requirements: 1.1, 1.2, 1.4_
  - _Boundary: MembershipService (backend service)_

- [x] 2.2 GET /workspaces/{id}/members owner-gated 라우트 결선
  - `response_model=Page[MemberRosterRead]`, `Depends(require_ws_role(Role.OWNER))` 게이트 부착만으로 서비스에 위임하고(위계 미달·비-멤버·미존재 WS→403, 미인증→401, admin override→통과: 판정은 s01·s05 소유·재구현 금지), `limit`(기본 50, ge=1)·`offset`(기본 0, ge=0) query 를 수용한다.
  - 기존 POST `/workspaces/{id}/members`(add_member)와 동일 경로·다른 메서드로 충돌 없이 등록되고, **별도 존재검사를 추가하지 않아**(게이트 선행이 유일 판정점) 미존재 WS 가 404 로 존재를 노출하지 않음을 확인한다.
  - 관찰 가능: owner 세션의 GET 이 200 `Page[MemberRosterRead]` 를 반환하고, 라우트가 앱에 등록되어 게이트가 선행 실행된다.
  - _Depends: 2.1_
  - _Requirements: 1.1, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5_
  - _Boundary: workspace router (GET /workspaces/{id}/members)_

## 3. 백엔드: 통합 검증 (게이팅·divergence·narrow·pagination)

- [x] 3.1 게이팅 매트릭스·anti-enumeration 통합 테스트
  - 신규 `test_member_roster_integration.py` 에서 assignable 하네스를 미러해 owner→200, editor→403, viewer→403, 비-멤버→403, admin(비-owner)→200, 미인증→401 을 HTTP 경계에서 단언한다(admin override 는 요청자 owner 여부와 무관, INV-3).
  - 미존재 WS 조회가 404 가 아닌 **403** 으로 응답해 워크스페이스 존재 여부를 드러내지 않음을 별도 케이스로 단언한다.
  - 관찰 가능: 게이팅 6개 역할 경로 + anti-enumeration 케이스가 모두 통과한다.
  - _Depends: 2.2_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - _Boundary: backend integration (test_member_roster_integration)_

- [x] 3.2 로스터 divergence·narrow 봉투·pagination 통합 테스트
  - 동일 통합 파일에서 비활성·삭제 상태 멤버가 role 과 함께 로스터에 존재하고(소프트삭제 미필터 divergence), 조회 owner 자신이 포함됨을 200 응답 본문으로 단언한다.
  - 각 item 키가 정확히 `{user_id, name, email, role}` 이며 `login_id`·`password_hash`·상태 flag·타임스탬프가 부재하고 email null 멤버가 `email: null` 로 포함됨을 단언한다. total > 페이지 크기일 때 limit/offset 경계에서 items·total 이 일관·결정적 순서이고, `limit=0`·`offset=-1` 은 422 임을 확인한다.
  - 관찰 가능: divergence·narrow 봉투·pagination 케이스가 모두 통과하고 전체 백엔드 스위트가 그린이다.
  - _Depends: 3.1_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.6_
  - _Boundary: backend integration (test_member_roster_integration)_

## 4. 프론트: 조회 어댑터·로드 훅

- [x] 4.1 (P) memberApi.list 어댑터 + MemberRosterRow 미러 타입
  - `types.ts` 에 백엔드 `MemberRosterRead` 를 미러하는 `MemberRosterRow`(`user_id`·`name`·`email: string | null`·`role: MemberRole`) 인터페이스를 추가하고, 기존 `memberApi` 객체에 `list(id, {limit?, offset?}): Promise<Page<MemberRosterRow>>` 를 `assignableUserApi.listAssignable` query 조립 관례를 미러해 추가한다(fetch·baseURL·credentials·401·에러 파싱은 `apiClient` 단일 소유·재구현 금지).
  - 단위 테스트로 경로 `/workspaces/{id}/members`·query(limit/offset 기본 50/0) 조립과 `Page<MemberRosterRow>` 반환을 확인한다(apiClient mock).
  - 관찰 가능: `memberApi.list` 호출이 올바른 경로·query 로 `apiClient.get` 을 호출하고 타입이 그린이다.
  - _Requirements: 1.2, 3.1_
  - _Boundary: memberApi.list + types (features/workspace api) — 백엔드 2.2 계약 미러_

- [x] 4.2 useWorkspaceMembers 로드 훅 (신규)
  - `useAssignableUsers` 형태를 미러해 서버 로스터를 유일 표시원으로 로드하는 훅을 추가한다(items→`members`, 타입 `MemberRosterRow`, `status`·`total`·`error`·`reload` 노출). `workspaceId` non-null 변경 시 재조회(`[workspaceId]` effect), 마운트 fetch 가 로컬 세션 이력과 무관하게 서버 시드.
  - `workspaceId === null` 이면 fetch 없이 안정 `status:"ready"`·빈 목록·total 0·error null 로 정착(로딩 고착 금지, null 동안 `reload()` no-op). `loadingRef`(in-flight 가드)·`mountedRef`(언마운트 후 갱신 억제), 실패는 `toApiError` 정규화→`status:"error"`.
  - 단위 테스트로 null 가드(안정 ready·no-op reload), 마운트 fetch, `[workspaceId]` 재조회, 성공 시 members·total, 실패 시 error 상태, reload 재조회를 확인한다(useAssignableUsers 테스트 미러).
  - 관찰 가능: 훅이 WS 선택 시 서버 로스터로 members·total 을 채우고, 미선택 시 조회 없이 안정 비로딩을 유지하며, reload 가 서버 현재상태로 재동기화한다.
  - _Depends: 4.1_
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 4.3_
  - _Boundary: useWorkspaceMembers (features/workspace hook)_

## 5. 프론트: 패널 표시원 전환 (단일 소스화)

- [ ] 5.1 MemberManagementPanel 서버 로스터 단일 표시원 전환
  - 표시원을 `useWorkspaceMembers(workspaceId).members`(서버 로스터)로 전환하고 `useMemberActions().members` 를 표시에서 사용하지 않는다(단일 소스). `nameById` Map 을 제거하고 멤버 라벨은 로스터 `name` 을 사용한다(`` `${row.user_id} ${row.name}` ``). S1 열거 한계 안내 문구는 제거한다.
  - 뮤테이션(add/changeRole/remove)은 `useMemberActions` 를 그대로 호출하고 await 후 `void roster.reload()` 로 서버 재동기화한다(add·remove 시 `void assignable.reload()` 유지, changeRole 은 로스터만). 로딩(`status==="loading"`)·오류(`status==="error"`→`error`)·빈(`status==="ready"` && `members.length===0`) 상태를 표면화하고, 뮤테이션 오류는 기존 `useMemberActions().error` 표시를 유지한다. 게이팅 노출(`RequireRole`+`MembershipRoleSource`)은 무변경.
  - 패널 테스트로 재로그인 시드(로컬 이력 없이 마운트 시 서버 로스터 표시), 이름=서버 값(`nameById` 부재), 단일 소스(로스터가 표시원), reload-after-mutation(add/changeRole/remove 후 재조회 반영), 로딩·오류·빈 상태, WS 미선택 시 안정 비로딩을 확인한다.
  - 관찰 가능: 새 세션 마운트에서 로컬 뮤테이션 이력 없이 서버 로스터의 기존 멤버 전량이 이름과 함께 표시되고, 뮤테이션 후 목록이 서버 진실로 재동기화된다.
  - _Depends: 4.2_
  - _Requirements: 3.5, 3.7, 4.1, 4.2_
  - _Boundary: MemberManagementPanel (features/workspace component)_

## 6. E2E 검증

- [ ] 6.1 재로그인 가시성·제거 재동기화 E2E
  - 재로그인 → 멤버 관리 진입 → 서버 로스터로 기존 멤버 전량이 표시됨을 E2E 로 검증한다(재로그인 이후 가시성, 로컬 세션 델타 부재 상태).
  - 기존 로스터 멤버 제거 → reload 후 목록에서 제외됨을 검증한다(델타 병합만으로는 불가한 removal-of-preexisting 케이스 실증).
  - 관찰 가능: 두 E2E 시나리오(재로그인 전량 표시·제거 후 제외)가 모두 통과한다.
  - _Depends: 2.2, 5.1_
  - _Requirements: 3.2, 4.1_
  - _Boundary: E2E (member roster visibility)_

## Implementation Notes

- **track 병렬성**: 백엔드 track(1·2·3)과 프론트 track(4·5)은 서로의 런타임에 의존하지 않는다 — 프론트 어댑터(4.1)는 design 에 동결된 GET `/workspaces/{id}/members` 계약을 미러하고 단위 테스트는 `apiClient` 를 mock 하므로, 두 track 은 병렬 진행 가능하다. 실제 서버 결선의 검증은 E2E(6.1)가 게이트한다(백엔드 2.2 + 프론트 5.1 양측 완료 후).
- **divergence 주의(핵심 함정)**: `list_members`(1.2)는 s23 `list_assignable_users` 의 배제형 필터와 **정반대**로 소프트삭제 필터를 적용하지 않는다. 템플릿을 무비판 복사해 `is_active`/`is_deleted` 필터를 남기면 비활성·삭제 멤버가 로스터에서 탈락해 이 기능의 존재 이유(기존 멤버 전량 노출, Req 1.5)를 스스로 깬다. 3.2 통합 테스트가 이 divergence 를 회귀로 고정한다.
- **narrow 봉투는 스키마 형태로 강제**: `MemberRosterRead`(1.1)는 선언 4필드만 직렬화하므로 계정 필드 누출은 별도 화이트리스트 없이 원천 차단된다. 3.2 가 HTTP 경계에서 누출 부재를 단언한다.
- **anti-enumeration 불변**: 미존재 WS 는 반드시 403(404 금지). 서비스·리포지토리에 존재검사를 추가하지 않는다 — 게이트(`require_ws_role`) 선행이 유일 판정점이다.
- **service 매핑은 명시 생성**: 2.1 은 join 프로젝션 `(User, role)` 을 `model_validate(user)` 가 아니라 `MemberRosterRead(user_id=user.id, …)` 로 명시 생성한다(id→user_id 리네임 모호 회피). total 은 리포지토리 계산값을 그대로 전달(items 길이 아님).
- **단일 소스 = reload 만**: 5.1 은 로컬 델타를 표시에 병합하지 않고 뮤테이션 후 로스터 reload 로만 반영한다("두 목록 분리" 금지, Req 4.2). reload 가 서버 권위로 add(중복 없음)·remove(제외)·role 변경을 반영하므로 Req 4.1 을 자명 충족한다. reload 는 뮤테이션 pending false 후 호출되어 in-flight 가드와 경합하지 않는다.
- **신규 마이그레이션·의존성 없음**: 백엔드는 기존 `schemas.py`/`repository.py`/`service.py`/`router.py` 에 가산, 프론트는 기존 `types.ts`/`memberApi.ts`/`MemberManagementPanel.tsx` 수정 + `useWorkspaceMembers.ts` 신규만. 스키마·마이그레이션·패키지 변경 없음.
