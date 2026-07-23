# Requirements Document

## Introduction

`s18-fe-workspace`는 MarkSpace 프론트엔드의 **워크스페이스 도메인 관리 화면군**을 소유한다. 사용자가 소속
워크스페이스를 전환하고(공통 레이어의 현재 WS 앰비언트 컨텍스트를 소비하는 스위처), owner가 멤버·권한과 WS
설정(`is_shareable`·보관 기간)을 관리하며, admin이 사용자 계정 생명주기와 WS 소유권을 관리하는 화면을
구현한다. 이 spec은 프론트 Wave-2 feature로, 공통 레이어(`s16-fe-foundation`)가 단일 소유한 세션 컨텍스트·
공용 API 클라이언트·권한 게이팅 유틸(`RequireAdmin` 포함)·**현재 WS 앰비언트 컨텍스트**·라우트/Provider 등록
메커니즘·공용 `Page<T>`를 **소비만** 하며 이를 재구현하지 않는다.

현재 워크스페이스 전역 컨텍스트(`CurrentWorkspaceProvider`·`useCurrentWorkspace()`·
`CurrentWorkspaceContextValue`)는 **s16이 단일 소유**한다. 이 spec은 그 컨텍스트를 소비하고, 컨텍스트가 담지
못하는 현재 사용자 `role`(백엔드 `WorkspaceRead`에 호출자 role 부재)을 멤버십 데이터 경로로 조달하는 **단일
role 소스**를 소유한다. `is_shareable` 플래그 관리 UI 역시 이 spec이 단독 소유한다(s22 공유 링크 발급은 이
플래그를 게이트로 소비만).

검증 기준은 백엔드와 동일하게 `s01-contract-foundation`의 계약 단일 소스다. 소비하는 API 형태는 백엔드
라우터의 실제 시그니처(워크스페이스·멤버 8개 엔드포인트, admin 소유권 변경 1개, admin 계정 4개)를 그대로
미러링하며 새 API 형태를 발명하지 않는다. 공용 `Page<T>`·`WorkspaceRead` 미러 타입은 s16 단일 정의를 import
한다(재정의 금지, `Page<T>`={items,total}). 특히 권한 위계는 s16 게이팅 유틸(owner ≥ editor ≥ viewer + admin
override, INV-1·2·3)과 s16 `RequireAdmin`(세션 `is_admin`)을 경유하고, 컴포넌트마다 역할 비교 로직을 흩뿌리지
않는다.

산출물 언어는 한국어이며, 상위 근거로 `s16-fe-foundation`(공통 레이어 계약)·`s01-contract-foundation`
(워크스페이스·멤버·권한 계약)의 requirements.md·design.md, 백엔드 라우터
(`backend/app/workspace/router.py`·`admin_router.py`·`backend/app/admin_account/router.py`), 스키마
(`backend/app/workspace/schemas.py`·`backend/app/schemas/base.py`), steering(`tech.md`·`structure.md`·
`roadmap.md`)를 참조한다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - 워크스페이스 스위처: **s16 현재 WS 앰비언트 컨텍스트**(`useCurrentWorkspace()`)를 소비해 소속 WS 목록·현재
    WS를 표시하고 `selectWorkspace`로 전환. 목록 로드·선택 영속은 s16 소유이므로 재구현하지 않는다.
  - 현재 사용자 `role` 조달: s16 `CurrentWorkspaceContextValue.role`(형태·기본값 null은 s16 소유)의 값을 멤버십
    데이터 경로로 공급하는 **단일 role 소스**(뮤테이션 응답 best-effort, 부재 시 null).
  - 워크스페이스 생성(인증된 사용자, 생성자 owner화), 성공 시 s16 `refresh()`로 컨텍스트 갱신.
  - owner 멤버/권한 관리: 멤버 추가·role 변경(owner/editor/viewer)·제거. INV-1·2 권한 경계의 UI 반영.
  - owner WS 설정: 이름·`is_shareable` 토글·`trash_retention_days`(보관 기간) 편집, 빈 WS 삭제.
  - admin 사용자 콘솔: 계정 목록·생성·수정(비활동/재활성화·삭제/복원 flag)·비밀번호 재설정.
  - admin WS 소유권 변경(admin override, INV-3).
  - 위 화면의 s16 라우트 등록 메커니즘(`RouteModule[]` export) 결선과, owner/admin 전용 UI 노출을 s16 게이팅
    유틸(`RequireRole`)·s16 `RequireAdmin`으로 결정.
- **Out of scope (다른 spec이 소유)**:
  - **현재 WS 앰비언트 컨텍스트 자체**: `CurrentWorkspaceProvider`·`useCurrentWorkspace()`·
    `CurrentWorkspaceContextValue`·선택 localStorage 영속(모두 s16 소유, 이 spec은 소비만).
  - 공통 레이어 자체: 세션 컨텍스트·공용 API 클라이언트·전역 401·권한 게이팅 유틸·`RequireAdmin`·라우터 셸·
    라우트/Provider 등록 메커니즘·공용 `Page<T>`·UI 프리미티브(모두 s16 소유, 이 spec은 소비만).
  - 로그인·로그아웃·본인 비밀번호 변경·세션 진입/복귀(s17).
  - 문서 트리·CRUD·이동·뷰어·휴지통 화면(s19).
  - 편집 생명주기·lock·자동저장·버전 뷰어(s20), 첨부(s21).
  - 공유 링크 발급/토글/무효화 관리 UI와 게스트 읽기 뷰(s22) — 이 spec은 `is_shareable` 게이트 플래그 관리 UI만
    소유하고 링크 발급 흐름은 소유하지 않는다.
  - 백엔드 API의 **동작**(워크스페이스·멤버·admin 계정 동작은 s03·s05 백엔드가 이미 소유·구현).
- **Adjacent expectations (인접 spec과의 기대·seam)**:
  - 현재 WS 경계·현재 role·`is_shareable`은 **s16 앰비언트 컨텍스트**가 후속 spec(s19·s20·s22)에 노출하는 단일
    계약이다. 이 spec은 그 컨텍스트를 소비하고 `role` 값을 조달할 뿐, 컨텍스트 형태의 소유자가 아니다(형태 변경
    재검증은 s16이 트리거).
  - 백엔드 계약에는 **워크스페이스 멤버 목록 조회 엔드포인트가 없고**(카탈로그 행 15~17은 추가·변경·제거
    뮤테이션만), **`WorkspaceRead`에 현재 사용자 role 필드가 없다**. 멤버 열거와 비-admin의 현재 role
    정확 조달은 계약이 제공하지 않는 seam이며, 이 spec은 조달 가능한 신호로 best-effort 처리하고 서버측
    403을 권위로 삼는다(cross-spec review·백엔드 후속에서 조정). 새 엔드포인트를 발명하지 않는다.
  - 사용자 디렉터리(전체 사용자 목록)는 `GET /admin/users`(admin 전용)만 존재한다. 비-admin owner의 멤버
    추가는 대상 `user_id` 입력을 전제로 하며, 비-admin 사용자 디렉터리 엔드포인트는 계약에 없다(seam).
  - s17-fe-auth와 동일 wave에서 병렬 생성되며(같은 user 도메인의 로그인 측), 세션 write 흐름은 s17 소유다.
    이 spec은 세션 변화 반영에 s16 `useSession().refresh()`만 소비한다.

## Requirements

### Requirement 1: 워크스페이스 스위처 및 현재 WS 컨텍스트 소비 · role 조달

**Objective:** As a 사용자, I want 소속 워크스페이스를 s16 현재 WS 앰비언트 컨텍스트를 통해 전환하고 현재 WS
role이 정확히 게이팅에 반영되기를, so that WS를 일관되게 전환하고 owner 전용 UI가 올바르게 노출된다.

#### Acceptance Criteria

1. When 인증된 사용자가 앱의 인증 영역에 진입하면, the system shall s16 `useCurrentWorkspace()`가 노출하는 소속
   워크스페이스 목록·현재 WS를 스위처에 표시하며, 목록 로드(`GET /workspaces`)·선택 영속을 자체 재구현하지 않는다.
2. When 사용자가 스위처에서 특정 워크스페이스를 선택하면, the system shall s16 컨텍스트의
   `selectWorkspace(String(id))`를 호출하여 현재 WS 전환을 위임하고, 현재 WS·`workspaceId`를 컨텍스트에서 소비한다.
3. The system shall 현재 WS 선택 지속(persist)·복원 로직을 **s16 소유로 간주**하여 재구현하지 않고, s16 컨텍스트가
   제공하는 현재 WS(및 `status`)를 그대로 표시한다.
4. The system shall s16 `CurrentWorkspaceContextValue.role`(형태·기본값 null은 s16 소유)의 값을 조달하는 **단일
   멤버십 role 소스**를 제공하되, 계약이 role 직접 조달 엔드포인트를 주지 않으므로 조달 가능한 신호(생성 응답의
   owner화·멤버 뮤테이션 응답의 자기 role 에코)로 best-effort 채우고 부재 시 `null`로 둔다(role 파생 로직은 이
   단일 소스에만 존재). admin은 s16 `RequireAdmin`/`hasWorkspaceRole`이 세션 `is_admin`으로 별도 처리한다.
5. When 소속 워크스페이스가 하나도 없어 s16 컨텍스트 `status`가 `empty`이면, the system shall 빈 상태(안내)를
   표시하고 잘못된 현재 WS 선택을 강제하지 않는다.
6. The system shall 현재 WS 경계 소비를 s16 앰비언트 컨텍스트 훅으로만 수행하고, 별도 WS 목록/선택 컨텍스트를
   새로 만들지 않는다(feature 격리, 컨텍스트 단일 소유는 s16).

### Requirement 2: 워크스페이스 생성

**Objective:** As a 인증된 사용자, I want 새 워크스페이스를 생성하기를, so that 내 문서 협업 공간을 만들고 그
공간의 owner가 된다.

#### Acceptance Criteria

1. When 사용자가 이름을 입력하고 생성을 요청하면, the system shall `POST /workspaces`(`WorkspaceCreate`:
   `name`)로 생성하고 성공(201) 시 반환된 `WorkspaceRead`를 s16 `refresh()`로 목록·컨텍스트에 반영한다.
2. If 이름이 비어 있거나 공백뿐이면, the system shall 생성 요청 전에 이를 막거나 서버 422 응답을 사용자에게
   오류로 표시한다(`is_shareable`·`trash_retention_days`는 입력받지 않으며 서버 기본값이 적용됨).
3. When 생성이 성공하면, the system shall 생성자를 owner로 간주하여 새 WS를 현재 WS로 선택 가능하게 하고(s16
   `selectWorkspace`), 단일 role 소스에 해당 WS의 owner role을 기록한다(요구 1.4 조달 신호).
4. If 생성 요청이 오류(4xx/5xx)로 실패하면, the system shall 공통 `ErrorResponse` 기반 오류 표시로 사용자에게
   실패 원인을 안내하고 목록 상태를 손상시키지 않는다.

### Requirement 3: 멤버/권한 관리 (owner)

**Objective:** As a 워크스페이스 owner, I want 멤버를 추가하고 역할을 변경하며 제거하기를, so that 워크스페이스
협업 권한을 owner/editor/viewer 위계로 통제한다.

#### Acceptance Criteria

1. When owner가 대상 사용자(`user_id`)와 role을 지정해 멤버 추가를 요청하면, the system shall
   `POST /workspaces/{id}/members`(`MemberCreate`: `user_id`·`role`)로 추가하고 성공(201) 시 반환된
   `MemberRead`(user_id·role)를 화면 상태에 반영한다.
2. When owner가 특정 멤버의 role 변경을 요청하면, the system shall
   `PATCH /workspaces/{id}/members/{uid}`(`MemberUpdate`: `role`)로 갱신하고 성공 시 `MemberRead`를 반영한다.
3. When owner가 특정 멤버 제거를 요청하면, the system shall `DELETE /workspaces/{id}/members/{uid}`로 제거하고
   성공(204) 시 화면 상태에서 해당 멤버를 제외한다.
4. The system shall role 선택 UI가 `owner`·`editor`·`viewer` 세 값(`MemberRole` 문자열)만 허용하고 그 외 값을
   전송하지 않도록 한다.
5. The system shall 멤버/권한 관리 UI 전체를 owner(및 admin override) 조건에서만 노출하며, 노출 판정을 s16 권한
   게이팅 유틸(요구 role = owner, 현재 role은 s16 컨텍스트에서 주입)로 수행하고 컴포넌트에서 역할 문자열을 직접
   비교하지 않는다(INV-1·2).
6. If 멤버 추가·변경·제거가 오류(대상 미존재 404·중복 멤버 409·권한 미충족 403·검증 422)로 실패하면, the
   system shall 공통 `ErrorResponse` 기반으로 오류를 표시하고 낙관적 반영을 되돌린다.
7. Where 계약에 멤버 목록 조회 엔드포인트가 없으므로, the system shall 권위 있는 멤버 전체 열거를 전제하지 않고,
   뮤테이션 응답(`MemberRead`)으로 확인된 멤버를 화면 상태로 관리하며 열거 한계를 사용자에게 명확히 드러낸다.

### Requirement 4: 워크스페이스 설정 (owner) — is_shareable · 보관 기간 · 삭제

**Objective:** As a 워크스페이스 owner, I want 워크스페이스 이름·공유 게이트(`is_shareable`)·휴지통 보관 기간을
편집하고 빈 워크스페이스를 삭제하기를, so that 워크스페이스 정책을 관리한다.

#### Acceptance Criteria

1. When owner가 설정 화면에서 이름·`is_shareable`·`trash_retention_days` 중 일부를 변경해 저장하면, the system
   shall `PATCH /workspaces/{id}`(`WorkspaceUpdate`: 선택적 `name`·`is_shareable`·`trash_retention_days`)로
   부분 갱신하고 성공 시 반환된 `WorkspaceRead`를 s16 `refresh()`로 현재 WS 컨텍스트에 반영한다.
2. The system shall `is_shareable` 게이트를 토글하는 UI를 단독 소유하며(s22는 이 플래그를 소비만), 현재 값을 s16
   컨텍스트의 `currentWorkspace.is_shareable`(또는 파생 `isShareable`)로 표시하고 토글 결과를 즉시 반영한다.
3. If `trash_retention_days`가 양의 정수(>0)가 아니면, the system shall 요청 전에 이를 막거나 서버 422 응답을
   사용자에게 오류로 표시한다.
4. When owner가 워크스페이스 삭제를 요청하면, the system shall `DELETE /workspaces/{id}`로 삭제하고 성공(204) 시
   s16 `refresh()`로 목록·현재 WS 컨텍스트에서 제외하며, 비어 있지 않아 409가 반환되면 "빈 워크스페이스만 삭제
   가능"을 안내한다.
5. The system shall 설정·삭제 UI 전체를 owner(및 admin override) 조건에서만 노출하며, 노출 판정을 s16 권한 게이팅
   유틸(요구 role = owner)로 수행한다(INV-1·2).
6. If 갱신·삭제가 오류(권한 403·미존재 404·검증 422·비-empty 409)로 실패하면, the system shall 공통
   `ErrorResponse` 기반으로 오류를 표시하고 현재 WS 컨텍스트를 손상시키지 않는다.

### Requirement 5: admin 사용자 콘솔 — 계정 생명주기

**Objective:** As a admin, I want 사용자 계정을 생성·조회하고 비활동/재활성화·삭제/복원하며 비밀번호를 재설정
하기를, so that 폐쇄형 서비스의 계정 생명주기를 관리한다.

#### Acceptance Criteria

1. When admin이 사용자 콘솔에 진입하면, the system shall `GET /admin/users`(`Page[UserRead]`)로 계정 목록을
   로드하여 표시하며(삭제·비활동 계정도 제외하지 않음) 각 계정의 상태(`is_admin`·`is_active`·`is_deleted`)를
   드러낸다.
2. When admin이 신규 계정을 생성하면, the system shall `POST /admin/users`(`UserCreate`: `login_id`·`password`·
   `name`·선택 `email`)로 생성하고 성공(201) 시 반환된 `UserRead`를 목록에 반영한다(`is_admin`·상태 flag는
   입력받지 않음).
3. When admin이 계정을 비활동/재활성화하거나 삭제/복원하면, the system shall `PATCH /admin/users/{id}`
   (`UserUpdate`: 선택적 `name`·`email`·`is_active`·`is_deleted`)로 갱신하며, `is_active`와 `is_deleted`를
   독립된 상태로 취급하여 각각 토글한다.
4. When admin이 대상 사용자의 비밀번호를 재설정하면, the system shall `POST /admin/users/{id}/password`
   (`AdminPasswordResetRequest`: `new_password`)로 재설정하고 성공(204)을 사용자에게 확인한다.
5. If 단일 admin 계정을 비활동/삭제하려다 서버가 409를 반환하면, the system shall "마지막 admin은 비활동·삭제할
   수 없음"을 안내하고 목록 상태를 되돌린다.
6. The system shall 사용자 콘솔 전체를 admin 세션에서만 노출·라우팅하며, 노출 판정을 s16 `RequireAdmin`(세션
   컨텍스트의 `is_admin` 단일 출처, INV-3)으로 수행하고 비-admin 진입 시 접근을 차단한다(게이트 재구현 금지).
7. If 계정 생성·수정·재설정이 오류(중복 login_id 409·미존재 404·검증 422·권한 403)로 실패하면, the system shall
   공통 `ErrorResponse` 기반으로 오류를 표시한다.

### Requirement 6: admin 워크스페이스 소유권 변경 (INV-3 admin override)

**Objective:** As a admin, I want 임의 워크스페이스의 owner를 지정 사용자로 변경하기를, so that 소유자 부재·이관
상황을 관리한다.

#### Acceptance Criteria

1. When admin이 대상 워크스페이스와 새 owner(`new_owner_user_id`)를 지정해 소유권 변경을 요청하면, the system
   shall `POST /admin/workspaces/{id}/owner`(`OwnerChangeRequest`: `new_owner_user_id`)로 변경하고 성공(200) 시
   반환된 `WorkspaceRead`를 반영한다.
2. The system shall 소유권 변경 UI를 admin 세션에서만 노출하며, 노출 판정을 s16 `RequireAdmin`(세션 컨텍스트의
   `is_admin`, INV-3 admin override)으로 수행하고, 이 조작이 워크스페이스 role 위계가 아닌 admin 전용 경로임을
   반영한다.
3. If `new_owner_user_id`가 누락되거나 대상 WS·사용자가 미존재(404)·권한 미충족(403)으로 실패하면, the system
   shall 공통 `ErrorResponse` 기반으로 오류를 표시한다.

### Requirement 7: 권한·admin 기반 UI 노출 게이팅 (s16 유틸 경유)

**Objective:** As a 프론트 유지보수자, I want owner 전용·admin 전용 UI 노출이 s16 공통 게이팅 유틸/세션 컨텍스트
단일 경로로만 결정되기를, so that 역할 비교 로직이 컴포넌트마다 흩어져 드리프트하지 않는다.

#### Acceptance Criteria

1. The system shall owner 전용 UI(멤버 관리·WS 설정·삭제)의 노출을 s16 `hasWorkspaceRole`/`<RequireRole>`
   (요구 role = owner, 현재 role은 s16 현재 WS 컨텍스트에서 주입)로만 판정하고, 컴포넌트에서 role 문자열을 직접
   비교하지 않는다.
2. The system shall admin 전용 UI(사용자 콘솔·소유권 변경)의 노출을 s16 `<RequireAdmin>`(세션 컨텍스트의
   `is_admin` 단일 출처)으로만 판정하며, 이 게이트를 재구현하지 않는다(INV-3).
3. If 현재 사용자가 admin이면, the system shall 워크스페이스 멤버 여부·role과 무관하게 owner 전용 UI 판정도
   통과시킨다(admin override, s16 유틸이 `is_admin`으로 처리).
4. While viewer/editor 등 owner 미만 권한 사용자가 owner 전용 UI 대상이면, the system shall 해당 UI를 노출하지
   않는다(INV-2, 읽기/편집 범위 초과 조작 은닉).
5. The system shall 클라이언트 게이팅이 UI 노출 편의일 뿐 서버측 권한 강제(백엔드 403)를 대체하지 않음을 전제로
   하여, 게이팅으로 숨겼더라도 서버가 반환한 403을 항상 오류로 처리한다.

### Requirement 8: 공통 레이어 소비 및 도메인 API 결선 경계

**Objective:** As a 프론트 feature 구현자, I want 워크스페이스 도메인 화면이 s16 공통 레이어만을 통해 서버와
결선되고 등록되기를, so that base URL·세션 쿠키·401·에러 정규화·라우팅·현재 WS 컨텍스트가 중복 구현 없이
일관되게 처리된다.

#### Acceptance Criteria

1. The system shall 모든 백엔드 호출을 s16 공용 API 클라이언트(`apiClient`)를 통해 수행하고, 자체 `fetch`
   설정·base URL 상수·에러 파싱을 재구현하지 않으며, 공용 `Page<T>`(`{items,total}`)·`WorkspaceRead` 미러 타입을
   s16에서 import 한다(재정의 금지, limit/offset은 쿼리 파라미터).
2. The system shall 세션·admin 여부·본인 설정을 s16 `useSession()`에서, 현재 WS 경계·role·`isShareable`을 s16
   `useCurrentWorkspace()`에서 소비하고 별도 세션/현재 WS 컨텍스트를 만들지 않는다.
3. The system shall 워크스페이스 도메인 화면을 s16 라우트 등록 메커니즘(`RouteModule[]` export, 보호 슬롯)으로
   등록하며, `router.tsx`/`main.tsx`를 수기 편집하지 않고 라우팅 가드·전역 401 처리를 재구현하지 않는다(admin
   콘솔은 s16 `RequireAdmin` 게이트 하위에서만 노출).
4. When 도메인 요청이 오류로 실패하면, the system shall s16 `ApiError`/`ErrorMessage`(공통 `ErrorResponse`의
   `message`·`field_errors`)로 오류를 표시하고 자체 에러 표면을 새로 만들지 않는다.
5. The system shall 다른 feature(`src/features/*`)를 직접 import 하지 않고, 현재 WS 경계는 s16 앰비언트 컨텍스트를
   소비하며(컨텍스트 소유·재구현 금지), 이 spec의 상향 기여는 s16 role 주입 seam에 공급하는 단일 role 소스로만
   한정한다(feature 간 직접 결합 금지).
