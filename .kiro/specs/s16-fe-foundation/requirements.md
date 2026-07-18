# Requirements Document

## Introduction

`s16-fe-foundation`은 Notion-lite 프론트엔드 전체(하위 spec s17~s22)가 공유하는 **교차 관심사 공통 레이어**를
단일 소유한다. 백엔드가 `s01-contract-foundation`에서 공유 계약·공용 런타임 인프라를 단일 소스로 확정한 것과
대칭으로, 이 spec은 프론트엔드의 L0(upstream)로서 라우팅 셸·공용 API 클라이언트·전역 401 인터셉터·세션
컨텍스트·권한 게이팅 유틸·공용 UI 프리미티브·Toast UI Editor 래퍼를 **한 번만** 구현하고, 각 feature spec은
이를 소비만 한다.

이 레이어가 없으면 후속 feature마다 401 처리·역할 비교·API base URL·에디터 렌더 경로가 흩어져 드리프트가
발생한다. 따라서 이 spec은 실제 feature 화면(로그인 폼·워크스페이스·문서·편집기·첨부·공유 뷰)을 구현하지
않으며, 오직 그 화면들이 얹힐 **공통 골격과 소비 계약**만 확립한다.

검증 기준은 백엔드와 동일하게 `s01-contract-foundation`의 계약 단일 소스다. 특히 세션 부트스트랩은
`GET /auth/me`(→ `AuthUserRead`), 사용자 설정은 `GET/PATCH /me/settings`(→ `UserSettingsRead`), 오류 응답은
공통 `ErrorResponse`(code·message·field_errors), 인증 실패는 401 `unauthenticated`, 권한 위계는 권한 resolver
(owner ≥ editor ≥ viewer + admin bypass, INV-1·2·3)를 계약으로 재사용한다. API 형태를 새로 발명하지 않는다.

산출물 언어는 한국어이며, 상위 근거로 `s01-contract-foundation`의 requirements.md·design.md와 steering
(`tech.md`·`structure.md`·`roadmap.md`)를 참조한다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - `frontend/` React + Vite + Tailwind CSS 4 SPA 스캐폴드(TypeScript strict)와 단일 설정 파일
    (`src/config.ts`, API base URL 등)로의 환경 값 통일.
  - 라우터 셸: 보호 라우트 프레임(세션 필요)과 게스트 라우트 프레임(`/share/:token`, 인증 가드 없음)의
    **등록 지점**. 실제 화면 컴포넌트는 등록만 하고 구현은 하위 spec 소유.
  - 공용 API 클라이언트: 단일 base URL·세션 쿠키 전송·공통 `ErrorResponse` 파싱, 그리고 그 안에 내장된
    전역 401 인터셉터(`returnTo` 보존 후 로그인 리다이렉트).
  - 세션 컨텍스트: 앱 로드 시 `GET /auth/me`로 현재 사용자·admin 여부를 부트스트랩하고, `GET /me/settings`로
    본인 설정을 로드하여 컨텍스트로 노출.
  - 권한 게이팅 유틸: 워크스페이스 role(owner/editor/viewer) 위계 + admin override(INV-3)에 따른 UI 노출
    판정을 단일 유틸/컴포넌트로 제공.
  - 공용 UI 프리미티브, 전역 앱 레이아웃, 전역 에러 경계(ErrorBoundary).
  - Toast UI Editor 단일 래퍼: 편집=WYSIWYG + markdown 토글, 읽기=viewer mode(렌더 경로 이원화 금지).
    또한 s20(편집)·s21(첨부)이 인스턴스를 포크하지 않고 소비할 수 있도록 붙여넣기/드롭 이벤트 구독 훅·
    콘텐츠 삽입/치환 콜백·`/attachments/{id}` 참조를 인증 blob으로 렌더하는 커스텀 렌더러 오버라이드를
    래퍼 계약에 포함(정책 동작은 여전히 s20/s21 소유, 래퍼는 인터페이스만).
  - **현재 워크스페이스 앰비언트 컨텍스트**: 세션 컨텍스트와 대칭으로, 현재 사용자 스코프의 워크스페이스
    목록(`GET /workspaces` → `Page[WorkspaceRead]`)·현재 선택 WS·`workspaceId`·`role`·`isShareable`를
    읽기 표면으로 노출하는 Provider·`useCurrentWorkspace()` 훅·**단일 컨텍스트 타입**과, 현재 WS 선택의
    localStorage 영속. 컨슈머(s18/s19/s20/s22)는 이 단일 형태에 정확히 바인딩한다.
  - **feature 라우트/Provider 등록 메커니즘**: 각 feature가 `router.tsx`를 손으로 수정하지 않고 라우트
    설정(`RouteModule[]`)을 export 해 단일 취합 지점에서 합성하는 가산(additive) API와, 하위 Provider를
    앱 Provider 합성에 끼우는 명시적 슬롯.
  - **공용 `Page<T>` 타입**: 백엔드 `base.py` `Page` 를 정확히 미러링한 `{ items: T[]; total: number }`
    (limit/offset 없음)를 공통 타입으로 단일 정의하여 s18/s19/s20 이 재정의 없이 import.
  - **읽기 전용 prose 스타일**: 인증 읽기(`EditorWrapper(mode:'read')`)와 게스트 공개 뷰(s22의 sanitized
    `content_html`)가 동일하게 렌더되도록 공용 read/prose 스타일(또는 `ReadOnlyProse` 컨테이너)을 단일 제공.
- **Out of scope (하위 spec이 소유)**:
  - 로그인·로그아웃·본인 비밀번호 변경 화면과 세션 진입/복귀 폼(s17).
  - 워크스페이스 관리 **화면**(스위처 UI·멤버/권한 관리·설정·admin 콘솔)과 WS/멤버 CRUD API 호출(s18).
    s16은 현재 WS 앰비언트 **읽기 표면**(Provider/훅/타입 + 선택 영속)만 소유하고, s18은 그 컨텍스트를
    채우고(`refresh()`) 변경(`selectWorkspace`)하는 관리 화면과 mutation API를 소유한다(세션 컨텍스트=s16 /
    로그인 화면=s17 의 분업과 동형).
  - 문서 트리·CRUD·이동·뷰어·휴지통 화면(s19).
  - 편집 진입/이탈 생명주기·lock UX·강제해제·자동저장·버전 뷰어(s20).
  - 첨부 업로드·렌더/다운로드·참조 소멸 placeholder(s21).
  - 공유 링크 관리·게스트 읽기 뷰·링크 경유 첨부 접근(s22).
  - 백엔드 API의 **동작**(모든 엔드포인트 동작은 s01~s15 백엔드가 이미 소유·구현).
- **Adjacent expectations (하위 spec이 이 레이어에 기대하는 것)**:
  - 모든 하위 spec은 라우팅 정의·전역 401 처리·권한 게이팅·API 호출 진입점을 재구현하지 않고 이 레이어를
    통해서만 소비한다. feature는 다른 feature를 직접 import 하지 않는다.
  - 권한에 따른 UI 노출(편집 가능 여부·잠금 강제 해제 노출 등)은 항상 공통 권한 게이팅 유틸을 거쳐 결정하며,
    컴포넌트마다 역할 비교 로직을 흩뿌리지 않는다.
  - 문서 편집/읽기 뷰는 이 spec의 단일 Toast UI Editor 래퍼를 소비하며, 자체 에디터 인스턴스를 별도로
    구성하지 않는다.

## Requirements

### Requirement 1: 프론트엔드 스캐폴드 및 설정 단일화

**Objective:** As a 하위 프론트 feature 구현자, I want `frontend/` SPA가 단일 설정 지점 위에서 부팅되기를,
so that 모든 feature가 동일한 빌드·타입·환경 값 기반 위에서 화면을 구현하고 하드코딩 상수 분산이 방지된다.

#### Acceptance Criteria

1. When 개발자가 `frontend/`에서 개발 서버를 기동하면, the system shall React + Vite + Tailwind CSS 4 기반
   SPA를 부팅하고 루트 라우트를 렌더한다.
2. The system shall TypeScript strict mode(`strict: true`)를 활성화하여 타입 오류가 빌드/타입체크에서
   드러나도록 구성한다.
3. The system shall API base URL 등 환경별 값을 단일 설정 파일(`src/config.ts`) 또는 단일 Vite env 소스에서만
   읽도록 통일하고, 여러 파일에 흩어진 하드코딩 base URL 상수를 두지 않는다.
4. Where 새 환경 값이 필요한 경우, the system shall 별도 설정 파일 신설 없이 단일 설정 파일 확장만으로 수용
   가능한 구조를 제공한다.
5. The system shall 절대 import를 위한 경로 alias(`@/`)를 구성하여 공통 레이어(`src/app`·`src/shared`)를
   feature가 일관되게 참조할 수 있게 한다.

### Requirement 2: 라우터 셸 (보호/게스트 라우트 프레임)

**Objective:** As a 하위 프론트 feature 구현자, I want 보호 라우트와 게스트 라우트의 프레임이 공통 레이어에
단일 정의되기를, so that 각 feature가 라우팅 가드를 중복 구현하지 않고 자기 화면을 등록만 하면 된다.

#### Acceptance Criteria

1. The system shall 보호 라우트 프레임과 게스트 라우트 프레임을 공통 레이어(`src/app`)에 단일 정의하고,
   하위 spec이 자기 화면을 이 프레임에 등록할 수 있는 지점을 제공한다.
2. When 세션이 없는 사용자가 보호 라우트에 진입하면, the system shall 진입하려던 경로를 `returnTo`로 보존한
   뒤 로그인 경로로 리다이렉트한다.
3. When 로그인이 성공하여 세션이 확립되면, the system shall 보존된 `returnTo` 경로로 복귀시키고, 없으면
   기본 경로로 이동시킨다.
4. The system shall `/share/:token` 게스트 라우트를 세션·워크스페이스 권한과 독립된 경로로 등록하며 인증
   가드를 적용하지 않는다(뷰 구현은 s22 소유).
5. While 세션 부트스트랩이 아직 완료되지 않은 상태에서, the system shall 보호 라우트 판정을 유보하고 로딩
   상태를 표시하여 인증 여부 확정 전에 잘못된 리다이렉트가 발생하지 않게 한다.

### Requirement 3: 공용 API 클라이언트

**Objective:** As a 하위 프론트 feature 구현자, I want 단일 API 클라이언트가 base URL·세션·에러 파싱을
일괄 처리하기를, so that 각 feature가 fetch 설정과 에러 해석을 중복 구현하지 않는다.

#### Acceptance Criteria

1. The system shall 모든 백엔드 호출을 단일 설정의 API base URL을 기준으로 수행하는 공용 API 클라이언트를
   제공한다.
2. When API 요청이 전송되면, the system shall 서명 쿠키 세션이 함께 전송되도록 자격증명 포함(credentials)
   설정을 적용한다.
3. When 응답이 오류 상태(4xx/5xx)이면, the system shall 공통 `ErrorResponse`(code·message·field_errors) 형태로
   본문을 파싱하여 호출부가 단일 에러 계약으로 처리할 수 있는 형태로 변환한다.
4. If 오류 본문이 공통 에러 형태가 아니거나 파싱 불가하면, the system shall 내부 세부정보 노출 없이 안정적인
   기본 오류 형태로 정규화하여 반환한다.
5. When 성공 응답이 반환되면, the system shall 각 feature가 자기 도메인 타입으로 소비할 수 있도록 타입 안전한
   결과를 반환한다(에디터/첨부의 바이너리 응답 포함).

### Requirement 4: 전역 401 인터셉터

**Objective:** As a 사용자·하위 프론트 feature 구현자, I want 인증 만료(401)가 공통 레이어에서 일관되게
처리되기를, so that 각 호출부가 세션 만료 리다이렉트를 개별 구현하지 않고 사용자가 로그인 후 원래 위치로
복귀한다.

#### Acceptance Criteria

1. When 공용 API 클라이언트가 401 `unauthenticated` 응답을 받으면, the system shall 현재 경로를 `returnTo`로
   보존한 뒤 로그인 경로로 리다이렉트한다.
2. The system shall 401 처리를 공용 API 클라이언트 단일 지점에 두어 각 feature 호출부가 401을 개별적으로
   가로채 처리하지 않도록 한다.
3. While 사용자가 게스트 라우트(`/share/:token`)에서 공개 리소스에 접근하는 동안, the system shall 401이
   아닌 정상 흐름에 대해 보호 라우트용 로그인 리다이렉트를 강제하지 않는다.
4. If 이미 로그인 경로에 있거나 세션 부트스트랩 자체(`GET /auth/me`)가 401을 반환하는 상황이면, the system
   shall 리다이렉트 루프 없이 미인증 상태로 전이한다.

### Requirement 5: 세션 컨텍스트 (부트스트랩)

**Objective:** As a 하위 프론트 feature 구현자, I want 현재 세션·역할·본인 설정이 앱 로드 시 부트스트랩되어
컨텍스트로 노출되기를, so that 각 feature가 인증 상태와 admin 여부·설정을 중복 조회하지 않고 소비한다.

#### Acceptance Criteria

1. When 앱이 로드되면, the system shall `GET /auth/me`를 호출하여 현재 사용자(`AuthUserRead`: id·login_id·
   name·email·is_admin)를 확정하고 세션 컨텍스트로 노출한다.
2. When 세션이 확정되면, the system shall `GET /me/settings`로 본인 설정(`UserSettingsRead`, 예:
   autosave_enabled)을 로드하여 컨텍스트로 노출한다.
3. If `GET /auth/me`가 401을 반환하면, the system shall 사용자를 미인증 상태로 확정하고 보호 라우트 접근을
   차단한다(설정 로드는 건너뛴다).
4. The system shall 세션 컨텍스트에 로딩·인증됨·미인증의 상태를 구분해 노출하여 하위 feature가 상태별 UI를
   결정할 수 있게 한다.
5. When 로그인/로그아웃 등으로 세션이 변화하면, the system shall 세션 컨텍스트를 갱신(재부트스트랩)할 수 있는
   진입점을 제공한다(로그인/로그아웃 흐름 자체는 s17 소유).
6. The system shall `is_admin` 값을 세션 컨텍스트에 노출하여 권한 게이팅 유틸이 admin override(INV-3)를
   판정할 수 있게 한다.

### Requirement 6: 권한 게이팅 유틸 (INV-1·2·3)

**Objective:** As a 하위 프론트 feature 구현자, I want 워크스페이스 role 위계와 admin override 판정이 단일
유틸로 제공되기를, so that 편집 가능 여부·잠금 강제 해제 노출 등 UI 노출 결정을 컴포넌트마다 역할 비교로
흩뿌리지 않는다.

#### Acceptance Criteria

1. The system shall 권한 판정을 워크스페이스 단위 role(owner/editor/viewer)만으로 수행하며 문서별 개별 권한
   개념을 제공하지 않는다(INV-1).
2. When 어떤 UI 요소가 최소 요구 role을 명시하면, the system shall owner ≥ editor ≥ viewer 위계에 따라 현재
   사용자의 role이 요구 role을 충족하는지 판정하는 단일 유틸을 제공한다.
3. If 현재 사용자가 admin이면, the system shall 워크스페이스 멤버 여부·role과 무관하게 모든 role 판정을
   통과시킨다(INV-3, admin override).
4. While viewer 권한만 가진 사용자가 변경 성격의 UI(생성·수정·삭제·휴지통·강제 해제)를 대상으로 판정되면,
   the system shall 해당 UI를 노출하지 않도록 판정 결과를 거짓으로 반환한다(INV-2).
5. The system shall 판정 결과를 재사용 가능한 함수형 유틸과 선언형 게이팅 컴포넌트(요구 role을 파라미터로 받는
   형태) 양쪽으로 제공하되, 실제 현재 워크스페이스 role의 주입은 각 feature가 수행함을 전제한다.
6. The system shall 권한 게이팅을 UI 노출 결정에만 사용하고, 서버측 권한 강제(백엔드 resolver)를 대체하지
   않음을 계약으로 명시한다(클라이언트 게이팅은 편의이며 보안 경계가 아님).

### Requirement 7: 공용 UI 프리미티브 · 전역 레이아웃 · 에러 경계

**Objective:** As a 하위 프론트 feature 구현자, I want 공용 UI 프리미티브와 전역 레이아웃·에러 경계가 공통
레이어에 제공되기를, so that 각 feature가 기본 UI 요소와 오류 표면 처리를 일관되게 재사용한다.

#### Acceptance Criteria

1. The system shall 공용 UI 프리미티브(예: 버튼, 로딩 인디케이터, 빈/오류 상태 표시 등 최소 세트)를 공통
   레이어(`src/shared`)에 제공한다.
2. The system shall 인증된 영역에 공통으로 적용되는 전역 앱 레이아웃 프레임을 제공하여 하위 feature 화면이
   그 안에 렌더되게 한다.
3. When 렌더 중 처리되지 않은 예외가 발생하면, the system shall 전역 에러 경계가 이를 포착하여 앱 전체 크래시
   대신 복구 가능한 오류 화면을 표시한다.
4. The system shall 공통 `ErrorResponse`의 `message`·`field_errors`를 사용자에게 표시할 수 있는 공용 오류
   표시 유틸/컴포넌트를 제공한다.
5. The system shall Tailwind CSS 4 유틸리티를 통해 공용 UI의 스타일을 구성하고, 프리미티브가 라이트 기준
   일관된 시각 언어를 갖도록 한다.

### Requirement 8: Toast UI Editor 단일 래퍼

**Objective:** As a 하위 프론트 feature 구현자, I want 편집·읽기 렌더 경로가 단일 Toast UI Editor 래퍼로
통일되기를, so that 편집 뷰와 읽기 뷰(뷰어 권한·공유 링크)가 렌더 경로 이원화 없이 동일 컴포넌트를 소비한다.

#### Acceptance Criteria

1. The system shall Toast UI Editor를 감싸는 단일 래퍼 컴포넌트를 공통 레이어에 제공하고, 하위 feature는 자체
   에디터 인스턴스를 별도로 구성하지 않는다.
2. Where 편집 모드가 요청되면, the system shall WYSIWYG를 기본으로 하고 markdown 토글을 같은 컴포넌트에서
   제공한다.
3. Where 읽기 전용(뷰어 권한·공유 링크) 모드가 요청되면, the system shall 동일 래퍼의 viewer mode로 렌더하여
   편집 뷰와 읽기 뷰의 렌더 경로를 이원화하지 않는다.
4. The system shall 초기 콘텐츠 주입과 현재 콘텐츠 조회를 위한 안정적 인터페이스를 노출하여 하위 feature
   (s20 편집 생명주기·s19/s22 읽기 뷰)가 저장·표시 로직을 결선할 수 있게 한다.
5. The system shall 자동저장(문서 이탈 시 1회)·lock 생명주기 등 편집 정책의 **동작**을 이 래퍼에 구현하지 않고
   래퍼가 소비 가능한 인터페이스만 제공함을 계약으로 명시한다(정책 동작은 s20 소유).
6. The system shall 래퍼가 편집 인스턴스를 포크하지 않고도 s21이 업로드 브리지를 결선할 수 있도록,
   붙여넣기/드롭 이벤트 구독 훅(예: `onImagePaste(file)`·`onFileDrop(file)`)을 래퍼 계약에 포함한다.
7. The system shall `EditorHandle`에 콘텐츠 삽입/치환 콜백(예: `insert(text)`·`replaceRange(...)`)을 노출하여
   s21이 업로드 진행 placeholder를 최종 `/attachments/{id}` 참조로 치환할 수 있게 한다.
8. The system shall 첨부/이미지 커스텀 렌더러 오버라이드(예: `customImageRenderer`/`customHTMLRenderer`)를
   편집·읽기 **양 모드에서 동일하게** 소비 가능하게 노출하여 `/attachments/{id}` 참조가 인증 blob 로딩을
   거쳐 렌더되게 한다(렌더 경로 이원화 없이 단일 래퍼 유지, 실제 blob 로딩 동작은 s21 소유).

### Requirement 9: 현재 워크스페이스 앰비언트 컨텍스트 (s16 단일 소유)

**Objective:** As a 하위 프론트 feature 구현자, I want 현재 워크스페이스(현재 사용자 스코프 목록·현재 선택 WS·
`workspaceId`·현재 사용자의 WS role·`is_shareable`)가 세션 컨텍스트와 대칭으로 앰비언트하게 노출되기를,
so that s18/s19/s20/s22가 현재 WS 필드에 산발적으로 접근하지 않고 **단일 컨텍스트 형태**에 정확히 바인딩한다.

#### Acceptance Criteria

1. The system shall `CurrentWorkspaceProvider`와 `useCurrentWorkspace()` 훅, 그리고 컨슈머가 바인딩할
   **단일(freeze된) 컨텍스트 값 타입** `CurrentWorkspaceContextValue`를 공통 레이어에 단일 정의한다.
2. When 앱이 인증되면, the system shall `GET /workspaces`(→ `Page[WorkspaceRead]`)로 현재 사용자 스코프의
   워크스페이스 목록을 로드하고 `status`(loading|ready|empty)·`workspaces`를 컨텍스트로 노출한다.
3. The system shall 현재 선택 WS(`currentWorkspace: WorkspaceRead | null`)와 함께 최상위 편의 접근자
   `workspaceId: string | null`(=`String(currentWorkspace.id)`)·`role: Role | null`·`isShareable: boolean`
   (=`currentWorkspace?.is_shareable ?? false`)를 파생 노출하여 컨슈머가 중첩 필드에 일관되지 않게 접근하지
   않게 한다.
4. The system shall `selectWorkspace(id)`로 현재 WS를 선택하고 그 선택을 localStorage에 영속하며, 재로드 시
   복원한다. 목록이 비어 있으면 `status:'empty'`로 노출한다.
5. The system shall `refresh(): Promise<void>`를 노출하여 s18의 WS/멤버 mutation 이후 목록·현재 WS를
   재조회할 수 있게 한다(변경 API 호출·관리 화면은 s18 소유, s16은 읽기 표면·선택 영속만).
6. The system shall `role` 값을 s16의 기존 `Role` enum으로 노출하되, 백엔드 `WorkspaceRead`가 호출자 role을
   담지 않으므로(ground truth) 현재 사용자의 WS 멤버십 role은 s18이 소유하는 멤버십 데이터 경로로 주입됨을
   전제하고(=`RequireRole`의 `currentRole` 주입 seam과 동형), s16은 필드·형태·기본값(null)만 단일 소유한다.
   admin override는 `role`에 접합하지 않고 세션 `is_admin`으로 별도 판정한다(INV-3).

### Requirement 10: 라우트/Provider 등록 메커니즘 (s16 단일 소유)

**Objective:** As a 하위 프론트 feature 구현자, I want 추상적 "등록 지점"이 구체적 가산 API로 확정되기를,
so that s17~s22가 `router.tsx`를 손으로 편집하지 않고 라우트 설정을 export 하는 것만으로 라우트를 등록한다.

#### Acceptance Criteria

1. The system shall 각 feature가 라우트 설정 배열/객체(예: `RouteModule[]`)를 export 하고 s16의 `router.tsx`가
   **단일 취합 지점**에서 이를 합성하는 구체적 가산 API를 정의한다(수기 라우터 편집 금지).
2. The system shall 보호 라우트 등록 슬롯과 게스트 라우트(`/share/:token`) 등록 슬롯을 각각 명시적으로
   구분해 제공한다.
3. The system shall 하위 Provider(예: 그 자체가 컨텍스트를 도입하는 feature)를 앱 Provider 합성에 끼울 수 있는
   명시적 Provider 합성 슬롯을 `main.tsx`/`AppLayout` 조립부에 제공한다.
4. The system shall 등록 메커니즘의 형태(예: `RouteModule` 필드·취합 함수 시그니처)를 계약으로 문서화하여
   하위 spec이 안정적으로 소비하고, 그 변경이 재검증 트리거임을 명시한다.

### Requirement 11: 공용 `Page<T>` 타입 (s16 단일 소유)

**Objective:** As a 하위 프론트 feature 구현자, I want 목록 응답 엔벨로프 타입이 공통 레이어에 단일 정의되기를,
so that s18/s19/s20이 `Page<T>`를 재정의하지 않고 import 하여 백엔드 계약과 정확히 정렬한다.

#### Acceptance Criteria

1. The system shall 공용 타입 `Page<T> = { items: T[]; total: number }`를 공통 레이어(`src/shared`)에 정확히
   백엔드 `app/schemas/base.py`의 `Page`와 동일하게 단일 정의한다.
2. The system shall `Page<T>`에 `limit`·`offset` 등 백엔드 `Page`에 없는 필드를 추가하지 않는다(계약 미러링,
   발명 금지). 페이지네이션 쿼리 파라미터(limit/offset)는 요청 측 관심사이며 응답 엔벨로프 타입과 분리한다.

### Requirement 12: 읽기 전용 prose 스타일 (s16 단일 소유)

**Objective:** As a 하위 프론트 feature 구현자, I want 인증 읽기 뷰와 게스트 공개 뷰의 본문 렌더가 동일한
prose 스타일을 소비하기를, so that 로그인 사용자 읽기와 공유 링크 게스트 읽기가 시각적으로 동일하게 보인다.

#### Acceptance Criteria

1. The system shall 공용 read/prose 스타일(또는 `ReadOnlyProse` 컨테이너)을 공통 레이어에 단일 제공하여
   `EditorWrapper(mode:'read')`가 이를 소비한다.
2. The system shall s22의 공개 뷰가 에디터 인스턴스 없이 sanitized `content_html`을 렌더할 때에도 동일한 공용
   prose 스타일을 소비하도록 노출한다(에디터 인스턴스 부재는 허용된 예외이며 렌더 경로 포크가 아님 — 공용
   prose CSS를 공유해 동일 시각 언어 보장).

### Requirement 13: 권한 게이팅 표면 확정 (RequireRole·hasWorkspaceRole·RequireAdmin, s16 단일 소유)

**Objective:** As a 하위 프론트 feature 구현자, I want 워크스페이스 role 게이팅과 admin 라우트 게이팅이 모두
s16 표면으로 확정되기를, so that s18이 `RequireAdmin`을 재구현하지 않고 s16 게이팅 표면을 소비한다.

#### Acceptance Criteria

1. The system shall `hasWorkspaceRole()`·`<RequireRole>`(워크스페이스 role 위계 게이팅)을 s16-소유
   게이팅 표면으로 문서화하여 하위 spec이 재구현하지 않고 소비하게 한다.
2. The system shall admin 라우트/화면 게이팅을 위한 `<RequireAdmin>`을 제공하되, 판정을 세션 `is_admin`
   (INV-3)으로 수행하며 워크스페이스 role과 독립됨을 명시한다(admin 콘솔 화면 자체는 s18 소유).
3. The system shall 이 게이팅 표면(`RequireRole`·`hasWorkspaceRole`·`RequireAdmin`)이 클라이언트 UI 노출
   편의이며 서버측 권한 강제(백엔드 403)를 대체하지 않음을 계약으로 명시한다.
