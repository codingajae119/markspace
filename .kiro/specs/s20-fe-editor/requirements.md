# Requirements Document

## Introduction

`s20-fe-editor`는 문서 화면에서 **편집 모드**를 소유하는 프론트엔드 feature다. `s19-fe-document`가 확립한
읽기 전용 문서 뷰 위에 편집 레이어를 얹어, editor 이상 사용자가 편집 모드로 진입해 `s16-fe-foundation`의
Toast UI Editor 래퍼(`mode:"edit"`)로 본문을 편집하고, 편집 잠금을 획득/해제하며, 문서에서 이탈할 때 1회만
자동저장(버전 스냅샷 생성)하고, 저장 버전 이력을 열람하는 화면과 생명주기를 구현한다.

이 spec은 백엔드 `s09-lock-version`이 이미 구현한 잠금·저장·버전 엔드포인트를 소비하는 **얇은 소비 계층**이며,
공용 API 클라이언트·전역 401 인터셉터·권한 게이팅 유틸·라우터 셸·Toast UI Editor 래퍼는 모두 `s16` 공통
레이어를 재사용하고 재구현하지 않는다. 잠금 판정(멱등 재획득·타인 잠금 충돌)·저장 원자성(버전 생성·current
갱신·잠금 해제)·강제 해제 권한 등 도메인 판정은 **백엔드 엔진이 단독 소유**하며, 이 spec은 결과와 오류를
표면화만 한다(재판정하지 않는다).

검증 기준은 백엔드와 동일하게 `s01-contract-foundation`의 계약 단일 소스다. 소비 엔드포인트·응답 스키마는
실제 백엔드 라우터(`backend/app/lock_version/router.py`)와 계약 스키마(`backend/app/lock_version/schemas.py`)를
그대로 미러링한다: `POST /documents/{id}/lock`(→ `DocumentLockRead`), `POST /documents/{id}/save`
(`DocumentSaveRequest` → `DocumentVersionRead`), `POST /documents/{id}/cancel`(204),
`POST /documents/{id}/force-unlock`(204), `GET /documents/{id}/versions`(→ `Page[DocumentVersionRead]`).
새 API 형태를 발명하지 않으며, 특히 잠금 현재 상태를 조회하는 별도 엔드포인트나 과거 버전 **본문** 조회
엔드포인트는 계약에 존재하지 않으므로 이 spec도 이를 전제하지 않는다. 권한 위계(owner ≥ editor ≥ viewer +
admin bypass, INV-1·2·3)와 WS 격리(INV-6)는 백엔드가 강제하는 계약을 그대로 소비한다.

산출물 언어는 한국어이며, 상위 근거로 `s01-contract-foundation`·`s16-fe-foundation`·`s19-fe-document`의
requirements.md·design.md와 steering(`tech.md`·`structure.md`·`roadmap.md`)을 참조한다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - 편집 모드 진입/이탈 생명주기: 진입 시 편집 잠금 획득(`POST /documents/{id}/lock`), 이탈(라우트 전환·
    언마운트) 시 잠금 해제. 이 생명주기를 편집 화면의 마운트/언마운트에 바인딩한다.
  - 편집 잠금 UX: 자신의 잠금 보유 상태(획득 시각) 표시, 타인 보유 잠금으로 인한 획득 실패(409) 안내.
  - 이탈 시 1회 자동저장: 편집 세션에서 잠금을 보유한 채 문서에서 벗어나는 시점에 `POST /documents/{id}/save`를
    **정확히 1회** 호출한다(주기 타이머·키입력 debounce 저장 금지 — 버전 폭증 회피, `tech.md` 결정).
  - 편집 취소: `POST /documents/{id}/cancel`로 변경분을 저장하지 않고 잠금만 해제.
  - 강제 해제 UI: `POST /documents/{id}/force-unlock`를 제한된 대상(WS owner·admin, 그리고 잠금 보유자 본인의
    자기 잠금 해제)에게만 노출하며, 노출 판정은 `s16` 권한 게이팅 유틸을 경유한다(컴포넌트 역할 비교 금지).
  - 버전 이력 뷰어: `GET /documents/{id}/versions` 목록을 읽기 전용으로 표시(저장자·저장 시각 메타데이터,
    현재 버전 표시). rollback·복원 액션을 제공하지 않는다.
  - 편집 라우트 등록: 편집 화면을 `s16` 보호 라우트 프레임의 자식으로 등록(프레임·가드는 `s16` 소유).
- **Out of scope (다른 spec/백엔드가 소유)**:
  - 문서 트리·breadcrumb·CRUD·이동·읽기 전용 뷰어·휴지통 화면(`s19-fe-document`). 편집 진입점(버튼)은
    `s19` 뷰어가 노출하며, 이 spec은 그 진입이 도달하는 편집 화면·라우트·동작을 소유한다.
  - 첨부 붙여넣기/드롭 업로드·이미지 렌더·참조 소멸 placeholder(`s21-fe-attachment`). 이 spec이 노출하는
    편집 표면(에디터 pane)이 `s21`이 붙여넣기/드롭을 얹는 seam이며, 업로드 동작 자체는 소유하지 않는다.
  - 공유 링크 관리·게스트 읽기 뷰(`s22-fe-sharing`).
  - 공통 레이어(라우터 셸·전역 401·API 클라이언트·권한 게이팅 유틸·Toast UI Editor 래퍼·현재 WS 앰비언트
    컨텍스트 `useCurrentWorkspace()`·공용 `Page<T>`)의 **구현**(`s16`).
  - 현재 WS 선택 mutation·멤버십/권한(`role`) 데이터 조달(`s18-fe-workspace`). 현재 WS 앰비언트 컨텍스트
    자체는 `s16`이 단일 소유하며 이 spec은 그 `workspaceId`·`role`을 소비만 한다.
  - 잠금 판정(멱등 재획득·타인 잠금 충돌·강제 해제 권한)·저장 원자성(버전 생성·current 갱신·잠금 해제)·
    버전 무한 보관·rollback 부재: 백엔드 엔진 소유.
- **Adjacent expectations (인접 seam)**:
  - 편집 진입점은 `s19` `DocumentViewer`가 editor 이상에게 노출하며, 진입은 이 spec이 정의하는 편집 라우트로
    도달한다(진입 경로 규약은 cross-spec 리뷰에서 `s19`와 정합; 두 feature는 서로 직접 import 하지 않는다).
  - 현재 WS 식별자(`workspaceId`)와 현재 사용자의 WS role은 `s16`이 단일 소유하는 현재 WS 앰비언트 컨텍스트
    `useCurrentWorkspace()`의 최상위 `workspaceId`·`role`에서 **소비만** 한다(`role` 값은 s18 멤버십 경로로 주입).
    이 spec은 `s16`과 동명 훅을 재정의하지 않고 얇은 래퍼(`useEditorScope`)로만 결합한다. 현재 사용자 식별자
    (`user.id`)·`is_admin`은 `s16` `useSession()`에서 취득한다.
  - 권한에 따른 UI 노출(강제 해제 노출 여부 등)은 항상 `s16` 권한 게이팅 유틸(`hasWorkspaceRole`/`<RequireRole>`)을
    거쳐 결정하며, 컴포넌트마다 역할 비교를 흩뿌리지 않는다.
  - 편집·읽기 렌더는 `s16` 단일 Toast UI Editor 래퍼를 소비하며 자체 에디터 인스턴스를 구성하지 않는다
    (편집 뷰와 읽기 뷰의 렌더 경로 이원화 금지).
  - 모든 백엔드 호출은 `s16` 공용 API 클라이언트를 통해서만 수행하며 401 처리·에러 정규화를 재구현하지 않는다.
  - 편집 표면(에디터 pane)은 `s16` `EditorWrapper`가 문서화한 `onImagePaste`/`onFileDrop` 슬롯·
    `EditorHandle.insert`/`replaceRange`(s16 소유 계약)에 `s21` 붙여넣기/드롭 업로드가 얹히는 지점이다. 이 spec은
    s16 래퍼를 마운트해 그 계약을 노출만 하고 업로드 동작은 `s21`에 위임한다(자체 표면 API 발명 금지).

## Requirements

### Requirement 1: 편집 모드 진입 및 잠금 획득

**Objective:** As a editor 이상 권한 사용자, I want 문서 편집 모드로 진입할 때 편집 잠금이 자동으로 획득되기를,
so that 다른 사용자와의 동시 편집 충돌 없이 안전하게 본문을 편집할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 `s19` 문서 뷰어의 편집 진입점을 통해 편집 화면으로 진입하면, the 편집 세션 shall
   `POST /documents/{id}/lock`을 호출하여 편집 잠금 획득을 시도한다.
2. When 잠금 획득이 성공(200, `DocumentLockRead`)하면, the 편집 세션 shall 현재 사용자를 잠금 보유자로 확정하고
   `s16` Toast UI Editor 래퍼를 `mode:"edit"`(WYSIWYG 기본 + markdown 토글)로 마운트하여 본문 편집을 활성화한다.
3. When 편집 본문의 초기값이 필요하면, the 편집 세션 shall `GET /documents/{id}`로 현재 본문(`content`, markdown)을
   조회하여 래퍼의 초기 콘텐츠로 주입하며, 읽기 뷰와 별도의 렌더 경로를 만들지 않는다.
4. If 같은 사용자가 이미 잠금을 보유한 상태에서 재진입하면, the 편집 세션 shall 백엔드의 멱등 재획득(200) 결과를
   그대로 반영하여 편집을 계속할 수 있게 하며, 프론트에서 별도 재판정을 하지 않는다.
5. While viewer 권한만 가진 사용자이면, the 편집 세션 shall 편집 진입점을 노출하지 않으며(INV-2, `s16` 권한
   게이팅 경유) 편집 모드로 진입하지 않는다.
6. If 잠금 획득 요청이 권한 미달(403)·문서 부재(404)로 거부되면, the 편집 세션 shall 편집 래퍼를 마운트하지 않고
   `s16` 공통 `ErrorResponse` 기반 오류를 표시한다.

### Requirement 2: 편집 잠금 상태 UX

**Objective:** As a 워크스페이스 멤버, I want 문서 편집 잠금의 현재 상태(내가 보유 중인지, 타인이 보유하여 편집이
막히는지)를 명확히 알기를, so that 편집 가능 여부를 이해하고 불필요한 편집 시도를 피할 수 있다.

#### Acceptance Criteria

1. While 현재 사용자가 잠금을 보유한 편집 세션이 활성 상태이면, the 잠금 상태 표시 shall `DocumentLockRead`의
   `lock_acquired_at`(획득 시각)을 근거로 "내가 편집 중"임을 표시한다.
2. If 잠금 획득이 타인 보유로 인해 충돌(409)로 거부되면, the 편집 세션 shall 편집 래퍼를 마운트하지 않고 "다른
   사용자가 편집 중"임을 안내하며 읽기 화면으로 되돌아갈 수 있는 경로를 제공한다.
3. The 잠금 상태 표시 shall 타인 잠금 충돌 안내를 백엔드가 반환한 `ApiError`(code·message) 그대로 표면화하며,
   계약에 없는 보유자 식별 정보를 프론트에서 발명하지 않는다.
4. The 잠금 상태 표시 shall 잠금의 현재 상태를 조회하는 별도 엔드포인트가 계약에 없음을 전제로, 상태를
   `POST /documents/{id}/lock` 응답(200/409)으로부터만 파생하며 폴링/추측 조회를 하지 않는다.

### Requirement 3: 이탈 시 1회 자동저장

**Objective:** As a editor 권한 사용자, I want 편집을 마치고 문서에서 벗어날 때 변경분이 자동으로 1회 저장되기를,
so that 명시적 저장 조작 없이도 편집 결과가 버전 스냅샷으로 보존되되 버전이 과도하게 폭증하지 않는다.

#### Acceptance Criteria

1. When 잠금을 보유한 편집 세션이 라우트 전환·언마운트로 종료되면, the 자동저장 기능 shall 편집 래퍼의 현재
   본문(markdown)을 담아 `POST /documents/{id}/save`를 **정확히 1회** 호출한다.
2. The 자동저장 기능 shall 주기 타이머나 키입력 debounce 기반 저장을 수행하지 않으며, 저장 트리거를 오직 편집
   세션 이탈 시점 1회로 한정한다(버전 폭증 회피).
3. When 저장이 성공(200, `DocumentVersionRead`)하면, the 자동저장 기능 shall 백엔드가 버전 생성·`current_version_id`
   갱신·잠금 해제를 수행했음을 전제로 편집 세션을 저장 완료·잠금 해제 상태로 확정한다(프론트는 재판정하지 않는다).
4. If 저장이 비보유·타인 잠금(409)·유효성 오류(422)로 거부되면, the 자동저장 기능 shall 해당 `ApiError`를 표면화하고
   세션 종료 흐름을 사용자에게 알린다.
5. If 편집 세션이 명시적 취소(Req 4)로 이미 잠금을 해제한 상태이면, the 자동저장 기능 shall 이탈 시 저장을
   중복 호출하지 않는다(취소 후 자동저장 억제).
6. Where 편집 세션 진입 시 잠금 획득에 실패(409/403/404)하여 잠금을 보유하지 못했으면, the 자동저장 기능 shall
   이탈 시 저장을 호출하지 않는다(보유하지 않은 잠금에 대한 저장 금지).

### Requirement 4: 편집 취소 (저장 없이 잠금 해제)

**Objective:** As a editor 권한 사용자, I want 편집을 저장하지 않고 취소하기를, so that 변경분을 버리고 편집 잠금을
즉시 해제하여 다른 사용자가 편집할 수 있게 할 수 있다.

#### Acceptance Criteria

1. When 잠금을 보유한 사용자가 편집 취소를 실행하면, the 취소 기능 shall `POST /documents/{id}/cancel`을 호출하여
   변경분을 저장하지 않고 잠금을 해제한다.
2. When 취소가 성공(204)하면, the 취소 기능 shall 편집 세션을 해제 상태로 확정하고 읽기 화면으로 복귀시키며, 이후
   이탈 자동저장(Req 3.5)이 발생하지 않도록 한다.
3. The 취소 기능 shall 버전을 생성하지 않으며 본문 변경분을 서버로 전송하지 않는다.
4. If 취소가 타인 잠금(409)·문서 부재(404)로 거부되면, the 취소 기능 shall 해당 `ApiError`를 표면화한다.
5. The 취소 기능 shall 미잠금 상태에 대한 취소가 백엔드에서 멱등 no-op으로 처리됨을 전제로 결과만 반영하며,
   프론트에서 잠금 유무를 재판정하지 않는다.

### Requirement 5: 강제 해제 UI (제한 노출)

**Objective:** As a WS owner 또는 admin, I want 방치된 편집 잠금을 강제로 해제하기를, so that 잠금 자동 타임아웃이
없는 환경에서 다른 사용자가 보유한 채 방치된 잠금 때문에 문서 편집이 영구히 막히는 상황을 해소할 수 있다.

#### Acceptance Criteria

1. When 잠금 획득이 타인 보유로 충돌(409)한 상황에서 현재 사용자가 WS owner 또는 admin이면, the 강제 해제 UI shall
   강제 해제 조작을 노출하며, 노출 판정은 `s16` `hasWorkspaceRole`({minimum: OWNER})(admin bypass 포함)로만
   수행한다(컴포넌트 역할 비교 금지, INV-1·3).
2. When owner/admin이 강제 해제를 확인하면, the 강제 해제 기능 shall `POST /documents/{id}/force-unlock`을 호출하고,
   성공(204) 시 잠금 상태를 갱신하여 재획득(`POST /lock`)을 시도할 수 있게 한다.
3. While 현재 사용자가 자신이 보유한 잠금을 해제하려는 편집 세션 안에 있으면, the 편집 세션 shall 자기 잠금 해제를
   `POST /documents/{id}/cancel`(또는 이탈 시 저장, Req 3·4)로 처리하며, 자기 잠금 해제에 owner 권한을 요구하지
   않는다.
4. If 강제 해제가 권한 미달(403)·문서 부재(404)로 거부되면, the 강제 해제 기능 shall 해당 `ApiError`를 표면화한다.
5. While 현재 사용자가 owner/admin이 아닌 viewer/editor(잠금 비보유)이면, the 강제 해제 UI shall 강제 해제 조작을
   노출하지 않으며(INV-2), 서버측 OWNER 강제(403)가 최종 권한 경계임을 전제한다(클라이언트 게이팅은 보안 경계 아님).

### Requirement 6: 버전 이력 뷰어 (읽기 전용, rollback 없음)

**Objective:** As a 워크스페이스 멤버(viewer 이상), I want 문서의 저장 버전 이력을 열람하기를, so that 누가 언제
저장했는지 저장 이력을 확인할 수 있다.

#### Acceptance Criteria

1. When 사용자가 버전 이력을 열람하면, the 버전 이력 뷰어 shall `GET /documents/{id}/versions`(`Page[DocumentVersionRead]`)를
   조회하여 저장 버전 목록(각 버전의 `id`·`created_by`·`created_at`)을 최신 저장 순 메타데이터로 표시한다.
2. When 버전 목록이 페이지네이션(`limit`·`offset`)으로 나뉘어 있으면, the 버전 이력 뷰어 shall 후속 페이지를 이어
   받아 더 많은 버전을 표시할 수 있는 조작을 제공한다.
3. The 버전 이력 뷰어 shall 계약(`DocumentVersionRead`)에 본문(content) 필드가 없고 과거 버전 **본문**을 조회하는
   엔드포인트가 존재하지 않음을 전제로, 각 버전의 본문을 표시하려 하지 않고 저장자·저장 시각 메타데이터만
   읽기 전용으로 표시한다.
4. The 버전 이력 뷰어 shall rollback·복원 액션을 제공하지 않으며(`tech.md` rollback 미제공 결정), 버전을 되돌리는
   조작 UI를 노출하지 않는다.
5. Where 문서 상세(`DocumentRead.current_version_id`)가 확보되면, the 버전 이력 뷰어 shall 목록에서 현재 버전을
   구분 표시할 수 있다.
6. If 버전 목록 조회가 실패(403/404)하면, the 버전 이력 뷰어 shall 공통 `ErrorResponse` 기반 오류를 표시한다.

### Requirement 7: 공통 레이어 소비 · 권한 게이팅 · 현재 WS 컨텍스트 · 오류 표면화

**Objective:** As a 프론트엔드 사용자, I want 편집·잠금·저장·버전 조작이 공통 레이어와 현재 WS 컨텍스트·권한에
따라 일관되게 게이팅되고 백엔드 판정 결과가 정확히 표면화되기를, so that 권한 없는 조작이 UI에 노출되지 않고
백엔드 제약 위반이 명확한 오류로 전달된다.

#### Acceptance Criteria

1. The 편집 화면 shall 현재 WS 식별자(workspace_id)와 현재 사용자의 WS role을 `s18`이 소유하는 현재 WS 컨텍스트
   (‑ `s16` 세션/컨텍스트 레이어 경유)에서 소비하고 현재 사용자 식별자·`is_admin`을 `s16` `useSession()`에서
   취득하며, 스스로 WS 컨텍스트·세션을 구현하지 않는다.
2. The 편집 화면 shall 편집 진입·강제 해제 등 권한 성격 UI의 노출을 `s16` 권한 게이팅 유틸(`hasWorkspaceRole`/
   `<RequireRole>`, owner ≥ editor ≥ viewer + admin bypass)로만 판정한다(INV-1·2·3).
3. When 백엔드가 오류를 반환하면, the 편집 화면 shall `s16` 공용 API 클라이언트가 정규화한 `ApiError`
   (code·message·field_errors)를 그대로 표면화하며 자체 에러 형태를 발명하지 않는다.
4. If 인증이 만료(401)되면, the 편집 화면 shall 개별 처리를 하지 않고 `s16` 전역 401 인터셉터의 로그인
   리다이렉트(returnTo 보존)에 위임한다.
5. The 편집 화면 shall 모든 백엔드 호출을 `s16` 공용 API 클라이언트로만 수행하고, 편집·읽기 렌더는 `s16` 단일
   Toast UI Editor 래퍼만 소비하며, 다른 feature를 직접 import 하지 않는다.
6. The 편집 화면 shall 편집 라우트를 `s16` 보호 라우트 프레임의 자식으로 등록하며, 라우트 프레임·가드 로직을
   재구현하지 않는다.
7. The 편집 표면(에디터 pane) shall `s16` `EditorWrapper`가 문서화한 `onImagePaste`/`onFileDrop` 슬롯·
   `EditorHandle.insert`/`replaceRange`를 통해 `s21-fe-attachment`가 붙여넣기/드롭 업로드를 얹을 수 있도록 노출되며,
   이 spec은 자체 표면 API를 발명하지 않고 s16 래퍼 계약을 통과 노출하며 업로드 동작은 구현하지 않는다.
8. The 클라이언트 권한 게이팅 shall UI 노출 편의일 뿐이며 서버측 권한 강제(백엔드 403/409)를 대체하지 않음을
   전제한다.
