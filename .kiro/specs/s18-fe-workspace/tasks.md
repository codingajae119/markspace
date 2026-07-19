# Implementation Plan

> 워크스페이스 도메인 관리 화면군(`frontend/src/features/workspace`). 모든 태스크는 s16 공통 레이어(apiClient·
> useSession·**현재 WS 앰비언트 컨텍스트 `useCurrentWorkspace()`**·게이팅 유틸·**`RequireAdmin`**·라우트 등록
> 메커니즘 `RouteModule`·공용 `Page<T>`·UI 프리미티브)를 **소비**하며 이를 재구현하지 않는다. 현재 WS 컨텍스트는
> s16이 단일 소유하므로 이 spec은 소비하고 `role` 값만 단일 소스로 조달한다. 계약에 없는 엔드포인트(멤버 목록·
> 현재 role·비-admin 디렉터리)는 발명하지 않고 seam으로 처리한다(design.md §Contract Constraints & Adjacent Seams).

- [ ] 1. feature 스캐폴드 및 계약 미러 타입
- [x] 1.1 워크스페이스 feature 폴더 구조 및 도메인 타입 정의
  - `frontend/src/features/workspace/api/types.ts`에 **s16이 소유하지 않는** 백엔드 계약 미러 타입만 정의
    (`WorkspaceCreate`/`WorkspaceUpdate`, `MemberRead`/`Create`/`Update`·`MemberRole`, `UserRead`/`Create`/
    `Update`·`AdminPasswordResetRequest`, `OwnerChangeRequest`). `Page<T>`(`{items,total}`)·`WorkspaceRead`는
    s16(`@/shared/types`)에서 **import**(재정의 금지, 새 필드 발명 금지, `WorkspaceRead`에 role 필드 없음 반영)
  - 관찰 가능한 완료: 타입이 `backend/app/workspace/schemas.py`·`admin_account/schemas.py` 필드와 정확히 일치하고,
    `Page<T>`·`WorkspaceRead`가 s16 import로 해소되며 `tsc --noEmit`이 오류 없이 통과함
  - _Requirements: 2.1, 3.1, 4.1, 5.1, 6.1, 8.1_
  - _Boundary: DomainTypes_

- [ ] 2. 도메인 API 어댑터 (s16 apiClient 위)
- [x] 2.1 workspaceApi 어댑터 구현 (P)
  - `api/workspaceApi.ts`에 `list`·`create`·`get`·`update`·`remove`를 s16 `apiClient` 경유로 구현
    (`GET/POST /workspaces`, `GET/PATCH/DELETE /workspaces/{id}`). `list`의 `limit`/`offset`은 쿼리 파라미터로만
    전달하고 응답은 s16 `Page<WorkspaceRead>`(items·total). 자체 fetch·base URL·에러 파싱 없음
  - 관찰 가능한 완료: 각 메서드가 카탈로그 행 10~14의 경로·메서드·바디와 일치하고 `apiClient`만 호출하며 limit/
    offset이 쿼리로 전달됨(단위 테스트로 확인)
  - _Requirements: 1.1, 2.1, 4.1, 4.4, 8.1_
  - _Boundary: workspaceApi_
  - _Depends: 1.1_
- [x] 2.2 memberApi 어댑터 구현 (P)
  - `api/memberApi.ts`에 `add`·`changeRole`·`remove`를 `apiClient` 경유로 구현
    (`POST/PATCH/DELETE /workspaces/{id}/members[/{uid}]`)
  - 관찰 가능한 완료: 각 메서드가 카탈로그 행 15~17과 일치하고 성공 시 `MemberRead`/void를 반환함(단위 테스트로 확인)
  - _Requirements: 3.1, 3.2, 3.3, 8.1_
  - _Boundary: memberApi_
  - _Depends: 1.1_
- [x] 2.3 adminApi 어댑터 구현 (P)
  - `api/adminApi.ts`에 `listUsers`·`createUser`·`updateUser`·`resetPassword`·`changeOwner`를 `apiClient`
    경유로 구현(`GET/POST /admin/users`, `PATCH /admin/users/{id}`, `POST /admin/users/{id}/password`,
    `POST /admin/workspaces/{id}/owner`). `listUsers`의 limit/offset은 쿼리, 응답은 s16 `Page<UserRead>`
  - 관찰 가능한 완료: 각 메서드가 카탈로그 행 5~9와 일치하고 `apiClient`만 호출함(단위 테스트로 확인)
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 6.1, 8.1_
  - _Boundary: adminApi_
  - _Depends: 1.1_

- [ ] 3. 현재 WS 컨텍스트 소비·role 조달·스위처
- [x] 3.1 MembershipRoleSource 구현 (현재 WS role 조달 단일 소스)
  - `context/membershipRoleSource.ts`에 현재 사용자의 WS별 확인된 role을 축적하는 **단일 소스**를 구현
    (`roleFor`·`recordOwner`·`recordSelfRole`). 생성 응답의 owner화·멤버 뮤테이션의 자기 role 에코만 신호로
    사용하고 부재 시 `null`. 이 값을 s16 `CurrentWorkspaceProvider`의 role 주입 seam(= `RequireRole` `currentRole`
    주입과 동형)에 공급하여 `useCurrentWorkspace().role`로 노출되게 결선(s16 파일 수기 편집 없이 seam 경유).
    role 파생 로직은 이 모듈 밖에 두지 않음
  - 관찰 가능한 완료: 생성 owner 기록·자기 role 에코 반영·신호 부재 시 `null`이 확인되고, role 파생이 이 모듈에만
    존재함(단위 테스트로 확인)
  - _Requirements: 1.4_
  - _Boundary: MembershipRoleSource_
  - _Depends: 1.1_
- [x] 3.2 WorkspaceSwitcher·CreateWorkspaceDialog·useWorkspaceActions 구현 (s16 컨텍스트 소비)
  - `components/WorkspaceSwitcher.tsx`(s16 `useCurrentWorkspace()`의 `workspaces`·`currentWorkspace` 표시,
    전환은 `selectWorkspace(String(id))` 호출, `status==="empty"` 빈 상태)·`components/CreateWorkspaceDialog.tsx`
    (이름 입력 → `POST /workspaces`)와 `hooks/useWorkspaceActions.ts`(생성 뮤테이션 → 성공 시 s16 `refresh()`·
    `MembershipRoleSource.recordOwner`)를 구현. 목록 로드·선택 영속은 s16 소유이므로 재구현 없음. 빈 이름 방지·
    서버 422 표시는 s16 `ErrorMessage` 소비
  - 관찰 가능한 완료: 스위처가 s16 컨텍스트 목록을 표시하고 전환 시 `selectWorkspace`가 호출되며, 생성 성공 시
    s16 `refresh()`가 호출되고 실패 시 `ErrorMessage`가 표시됨(통합 테스트로 확인)
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 8.2, 8.4_
  - _Boundary: WorkspaceSwitcher, CreateWorkspaceDialog, useWorkspaceActions_
  - _Depends: 2.1, 3.1_

- [ ] 4. owner 멤버/권한 관리
- [x] 4.1 RoleSelect 및 useMemberActions 구현 (P)
  - `components/RoleSelect.tsx`(owner/editor/viewer 3값만 방출)·`hooks/useMemberActions.ts`(add/changeRole/remove
    뮤테이션 + 뮤테이션 응답 `MemberRead` 기반 로컬 멤버 상태 관리, 실패 시 롤백, 대상이 자기 자신이면
    `MembershipRoleSource.recordSelfRole` 반영). 계약에 멤버 목록 조회가 없다는 S1 전제를 로컬 상태 주석·UI 노출
    문구로 반영
  - 관찰 가능한 완료: `RoleSelect`가 세 값만 방출하고, 뮤테이션 성공 시 로컬 멤버 상태가 갱신·실패 시 롤백됨(단위 테스트로 확인)
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6, 3.7_
  - _Boundary: RoleSelect, useMemberActions_
  - _Depends: 2.2, 3.1_
- [x] 4.2 MemberManagementPanel 구현 (owner 게이팅)
  - `components/MemberManagementPanel.tsx`에서 `<RequireRole minimum={Role.OWNER} currentRole={useCurrentWorkspace().role}>`
    로 감싼 멤버 추가(`user_id`+role)·role 변경·제거 UI를 구현. 현재 role은 s16 컨텍스트에서 주입, 역할 문자열
    직접 비교 없음. 전체 멤버 열거가 아님을 UI에 명시(S1), 서버 403은 항상 오류로 처리
  - 관찰 가능한 완료: owner/admin 컨텍스트에서 패널이 노출되고 viewer/editor 컨텍스트에서 미노출되며, 추가·변경·
    제거 조작이 서버 결선되고 오류가 `ErrorMessage`로 표시됨(UI 테스트로 확인)
  - _Requirements: 3.1, 3.5, 3.6, 3.7, 7.1, 7.3, 7.4, 7.5_
  - _Boundary: MemberManagementPanel_
  - _Depends: 4.1, 3.2_

- [ ] 5. owner 워크스페이스 설정
- [x] 5.1 WorkspaceSettingsPanel 구현 (owner 게이팅, is_shareable 단독 소유)
  - `components/WorkspaceSettingsPanel.tsx`에서 `<RequireRole minimum={Role.OWNER} currentRole={useCurrentWorkspace().role}>`
    로 감싼 이름·`is_shareable` 토글(현재 값은 s16 컨텍스트 `currentWorkspace.is_shareable`/`isShareable`)·
    `trash_retention_days` 편집(`PATCH /workspaces/{id}` 부분 갱신 → s16 `refresh()`)과 빈 WS 삭제
    (`DELETE /workspaces/{id}`, 409 시 "빈 WS만 삭제 가능" 안내)를 구현. `useWorkspaceActions` 확장 소비
  - 관찰 가능한 완료: `is_shareable` 토글·retention·이름 갱신이 s16 `refresh()`로 현재 WS 컨텍스트에 반영되고,
    retention 비양수는 막히거나 422 표시, 비-empty 삭제 409가 안내됨(통합 테스트로 확인)
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 7.1, 7.4, 8.4_
  - _Boundary: WorkspaceSettingsPanel, useWorkspaceActions_
  - _Depends: 3.2_

- [ ] 6. admin 콘솔 (계정 생명주기·소유권 변경) — s16 RequireAdmin 소비
- [x] 6.1 AdminUserPanel 및 AdminUserForm·PasswordResetDialog 구현
  - `admin/AdminUserPanel.tsx`(`GET /admin/users` 목록 — 삭제·비활동 포함 상태 표시)·`AdminUserForm.tsx`
    (`POST /admin/users` 생성 / `PATCH /admin/users/{id}`로 `is_active`·`is_deleted` **독립** 토글)·
    `PasswordResetDialog.tsx`(`POST /admin/users/{id}/password`)를 구현. 단일 admin 비활동/삭제 409·중복 login_id
    409·검증 422를 `ErrorMessage`로 안내
  - 관찰 가능한 완료: 목록이 상태 flag와 함께 표시되고, 생성/상태 토글/비번 재설정이 서버 결선되며 단일 admin 409가
    안내됨(통합 테스트로 확인)
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.7, 8.4_
  - _Boundary: AdminUserPanel, AdminUserForm, PasswordResetDialog_
  - _Depends: 2.3_
- [x] 6.2 AdminOwnerChangePanel 구현
  - `admin/AdminOwnerChangePanel.tsx`에서 대상 WS·`new_owner_user_id`를 지정해 `POST /admin/workspaces/{id}/owner`
    로 소유권을 변경(200 시 `WorkspaceRead` 반영), 누락·404·403을 `ErrorMessage`로 안내
  - 관찰 가능한 완료: 유효 입력 시 소유권 변경이 성공 반영되고, 누락/미존재/권한 오류가 표시됨(통합 테스트로 확인)
  - _Requirements: 6.1, 6.2, 6.3_
  - _Boundary: AdminOwnerChangePanel_
  - _Depends: 2.3_
- [x] 6.3 AdminConsolePage 조립 (s16 RequireAdmin 하위)
  - `admin/AdminConsolePage.tsx`에서 **s16 `<RequireAdmin>`**(`@/shared/auth`, 세션 `is_admin`, INV-3, 재구현
    금지) 하위에 AdminUserPanel·AdminOwnerChangePanel을 배치하는 라우트 셸을 구성. WS role(`RequireRole`)과
    혼동하지 않음
  - 관찰 가능한 완료: admin만 콘솔 화면(사용자 콘솔+소유권 변경)에 접근·렌더되고 비-admin/미인증은 s16
    `RequireAdmin`이 차단함(UI 테스트로 확인)
  - _Requirements: 5.6, 6.2, 7.2_
  - _Boundary: AdminConsolePage_
  - _Depends: 6.1, 6.2_

- [ ] 7. 라우트 등록(RouteModule) 및 검증
- [ ] 7.1 RouteModule[] export 및 role 소스 등록 (통합)
  - `features/workspace/routes.tsx`에서 워크스페이스 화면·admin 서브트리(내부 `RequireAdmin` 게이팅)를 s16
    `RouteModule` 계약의 **보호 슬롯**(`scope: "protected"`) 배열로 export 하고, `MembershipRoleSource`를 s16
    `CurrentWorkspaceProvider`의 role 주입 seam에 등록. `router.tsx`/`main.tsx` 수기 편집 없음, 현재 WS Provider
    마운트는 s16 소유(재마운트 금지)
  - 관찰 가능한 완료: 워크스페이스·admin 화면이 s16 보호 슬롯에서 렌더되고 admin 화면은 s16 `RequireAdmin`으로만
    접근되며, s16 컨텍스트 `role`이 이 spec의 role 소스로 채워짐(수동/통합 확인)
  - _Requirements: 1.4, 1.6, 8.2, 8.3, 8.5_
  - _Boundary: WorkspaceRouteModule, MembershipRoleSource_
  - _Depends: 3.2, 4.2, 5.1, 6.3_
- [ ]* 7.2 도메인 단위·통합·UI 테스트 작성
  - 어댑터 경로/메서드 일치·limit/offset 쿼리·`MembershipRoleSource` 조달/폴백·`RoleSelect` 3값(단위),
    스위처의 s16 컨텍스트 소비·WS 생성·멤버 뮤테이션·설정 갱신(is_shareable/retention/삭제 409)·admin 계정
    (독립 flag·단일 admin 409)·소유권 변경(통합), owner/admin(s16 RequireAdmin) 게이팅 노출·미노출(UI) 테스트를 추가
  - 관찰 가능한 완료: 위 테스트 스위트가 모두 통과함
  - _Requirements: 1.1, 1.4, 2.1, 3.1, 3.4, 4.2, 4.4, 5.3, 5.5, 6.1, 7.1, 7.2, 7.4_
  - _Boundary: Testing_
  - _Depends: 7.1_
- [ ] 7.3 타입체크·빌드 검증
  - `tsc --noEmit`(strict)와 `vite build`를 실행하여 워크스페이스 feature가 `any` 없이(s16 import 정합) 타입
    통과·번들됨을 확인
  - 관찰 가능한 완료: 타입체크와 프로덕션 빌드가 오류 없이 완료됨
  - _Requirements: 8.1, 8.5_
  - _Boundary: DomainTypes_
  - _Depends: 7.1_

## Implementation Notes

구현 착수 전 s16 실소스·백엔드 스키마를 검증한 결과와 사용자 승인 결정(2026-07-19). 모든 태스크는 아래를
ground truth 로 삼는다(설계 표현이 실제와 다르면 아래가 우선).

### D-1. role 주입 seam 결정 (사용자 승인)
- **s16 현실**: `CurrentWorkspaceProvider.tsx:145` 는 `role: null` 을 **하드코딩**하며, 앰비언트 컨텍스트에
  role 값을 주입하는 seam(registry/prop/setter)이 **없다**. s16 주석(`types.ts:23-25`)이 명시하듯 실제
  seam 은 **`RequireRole` 의 `currentRole` prop** 이다(= "isomorphic to RequireRole currentRole").
- **결정**: `MembershipRoleSource`(task 3.1)는 **s18 소유 React 컨텍스트 provider + `useMembershipRole()`
  훅 + 명령형 recorder(`recordOwner`/`recordSelfRole`)**로 구현하고 `Map<workspaceId, Role>` 상태를 보유한다
  (role 파생 단일 소스). owner 패널(4.2·5.1)은 `<RequireRole minimum={Role.OWNER}
  currentRole={useMembershipRole(workspaceId)}>` 로 게이팅한다. **`currentRole={useCurrentWorkspace().role}`
  를 쓰지 말 것** — 항상 null 이라 owner 에게 owner UI 가 숨겨져 Req 7.4 위반. s16 파일은 수정하지 않는다.
- provider 는 s16 `featureProviders` 합성 슬롯(main.tsx)에 등록(task 7.1). admin override 는 role 이 아니라
  s16 `RequireRole`/`RequireAdmin` 이 세션 `is_admin` 으로 별도 통과시킨다(INV-3).

### D-2. main.tsx 등록 결정 (사용자 승인)
- routes·provider 등록은 `main.tsx` 의 두 취합 배열을 **append** 하는 것이 s16 이 구축한 메커니즘이다
  (프레임 `router.tsx`/`ProtectedRoute` 는 불변). task 7.1 에서만:
  `const featureRouteModules = [...authRoutes, ...workspaceRoutes];`,
  `const featureProviders = [MembershipRoleProvider];` 로 수정한다(s16 주석 37-38·11-12 이 초대).

### C-1. s16 소비 계약 (import path·시그니처, 재구현 금지)
- `apiClient` ← `@/shared/api/client`: `get<T>(path,opts?)`·`post<T>(path,body?,opts?)`·`patch<T>(path,body?,opts?)`·
  `del<T>(path,opts?)`. **쿼리 파라미터 전용 옵션 없음** → 쿼리는 path 문자열에 직접 조립
  (`apiClient.get<Page<X>>(\`/workspaces?limit=${l}&offset=${o}\`)`). 204/빈 응답 → `undefined`. 비2xx →
  `ApiError` throw. body 는 JSON 직렬화(FormData 아니면).
- `useSession` ← `@/app/session/useSession`. 판별 유니온: `status: "loading"|"authenticated"|"unauthenticated"`.
  `user`/`settings` 는 authenticated 변형에만. `is_admin` 은 `s.status==="authenticated" && s.user.is_admin`.
- `useCurrentWorkspace` ← `@/app/workspace-context/useCurrentWorkspace`. 값 타입 `CurrentWorkspaceContextValue`
  ← `@/app/workspace-context/types`: `{status:"loading"|"ready"|"empty", workspaces, currentWorkspace,
  workspaceId, role(항상 null), isShareable, selectWorkspace(id:string), refresh()}`. 스위처는 이 목록·
  currentWorkspace 를 표시하고 `selectWorkspace(String(id))` 로 전환(목록 로드·영속 재구현 금지).
- 권한: `Role`(enum, VIEWER=1<EDITOR=2<OWNER=3) ← `@/shared/auth/roles`. `hasWorkspaceRole({currentRole,
  isAdmin,minimum})` ← `@/shared/auth/permissions`. `RequireRole` ← `@/shared/auth/RequireRole`
  (props: `minimum`·`currentRole`·`fallback?`·`children`; is_admin 은 내부에서 useSession 으로 읽음).
  `RequireAdmin` ← `@/shared/auth/RequireAdmin`(props: `fallback?`·`children`; is_admin 만 판정).
- 타입: `Page<T>`={items:T[], total:number} ← `@/shared/types/page`. `WorkspaceRead`={id,created_at,
  updated_at|null, name, is_shareable, trash_retention_days} ← `@/shared/types/workspace`. **둘 다 import,
  재정의 금지.**
- UI: `Button`·`Spinner`·`EmptyState`·`ErrorMessage`(+prop 타입) ← 배럴 `@/shared/ui`.
  **`ErrorMessage` 는 `error: ApiError | null` prop 을 받는다**(message/field_errors 개별 아님). `ApiError`
  ← `@/shared/api/errors`: `{status, code, fieldErrors: FieldError[](camelCase!), raw?}`. catch 패턴:
  `if (e instanceof ApiError) setError(e)`.
- `RouteModule` ← `@/app/routeModule`: `{scope:"protected"|"guest", routes: RouteObject[]}`. 보호 슬롯은
  pathless 레이아웃 자식이라 **상대 경로**(예 `"workspace/members"`). `composeProviders`/`ProviderComponent`
  ← `@/app/providers`. s17 예시: `features/auth/routes.tsx` 의 `authRoutes` 배열.

### C-2. 백엔드 계약 ground truth (미러 타입 드리프트 금지)
- 경로 파라미터: workspace 는 `{id}`·member 는 `{uid}`; admin user 는 `{user_id}`; owner 변경은 `{id}`.
- `MemberRead` = {id, workspace_id, user_id, role} — **타임스탬프 없음**(ORMReadModel). `MemberRole`=
  "owner"|"editor"|"viewer". `MemberCreate`={user_id,role}, `MemberUpdate`={role}.
- `WorkspaceCreate`={name}(비공백). `WorkspaceUpdate`={name?, is_shareable?, trash_retention_days?}(모두 optional).
- `UserRead`={id, created_at, updated_at|null, login_id, name, email|null, is_admin, is_active, is_deleted}.
  `UserCreate`={login_id, password, name, email?|null}. `UserUpdate`={name?, email?|null, is_active?,
  is_deleted?}(is_admin 없음). `AdminPasswordResetRequest`={new_password}. `OwnerChangeRequest`=
  {new_owner_user_id}. `email` 은 plain nullable string.
- 엔드포인트/상태: POST /workspaces→201; GET /workspaces(limit=50,offset=0 query)→200 Page; GET/PATCH
  /workspaces/{id}→200; DELETE /workspaces/{id}→204; POST /workspaces/{id}/members→201; PATCH
  .../members/{uid}→200; DELETE .../members/{uid}→204; POST /admin/workspaces/{id}/owner→200 WorkspaceRead;
  GET /admin/users(limit/offset query)→200 Page; POST /admin/users→201; PATCH /admin/users/{user_id}→200;
  POST /admin/users/{user_id}/password→204.

### D-3. MembershipRoleSource 실제 소비 계약 (task 3.1 완료 — downstream 바인딩)
- 파일: `frontend/src/features/workspace/context/membershipRoleSource.tsx`. exports:
  - `MembershipRoleProvider` — `({children}) => ReactElement`, s16 `ProviderComponent` 호환. task 7.1 에서
    main.tsx `featureProviders` 에 등록.
  - `useMembershipRoleSource(): { roleFor(wsId:number): Role|null; recordOwner(wsId:number): void;
    recordSelfRole(wsId:number, role:Role): void }` — provider 밖 호출 시 throw. 패널(4.2·5.1)은
    `const { roleFor } = useMembershipRoleSource(); const role = currentWorkspace ? roleFor(currentWorkspace.id)
    : null;` 로 읽어 `<RequireRole minimum={Role.OWNER} currentRole={role}>` 에 주입. 뮤테이션 훅(3.2·4.1)은
    `recordOwner`/`recordSelfRole` 호출.
  - `memberRoleToRole(role: MemberRole): Role` — MemberRole 문자열→Role enum 번역 단일 지점. useMemberActions(4.1)
    가 self 에코를 `recordSelfRole(wsId, memberRoleToRole(echoedRole))` 로 반영.
- 상태는 in-memory `Map<number,Role>`(useState). 세션 전환 시 자동 리셋 없음(관측된 concern) — client 게이팅은
  보안 경계 아님(서버 403 권위, Req 7.5)이라 비차단. 통합/7.1 에서 필요 시 세션 변화 리셋 고려 가능.

### C-3. 테스트 하네스
- vitest(jsdom·globals), setup `src/test/setup.ts`, 테스트는 co-located `*.test.ts(x)`. alias `@`→`src`.
- 명령: `npm run test`(vitest run)·`npm run typecheck`(tsc --noEmit)·`npm run build`(tsc --noEmit && vite build),
  모두 `frontend/` 에서. 착수 baseline: 32 files / 186 tests green.
