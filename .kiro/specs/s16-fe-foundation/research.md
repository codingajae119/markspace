# Research & Design Decisions — s16-fe-foundation

## Summary
- **Feature**: `s16-fe-foundation`
- **Discovery Scope**: New Feature (greenfield 프론트엔드 L0 공통 레이어)
- **Key Findings**:
  - `frontend/`는 아직 존재하지 않음 → 스캐폴드부터 시작하는 순수 greenfield. 백엔드(s01~s15)는 전체 GO.
  - 소비 계약은 이미 백엔드 라우터에 실체로 존재: `GET /auth/me → AuthUserRead{id,login_id,name,email,
    is_admin}`, `GET/PATCH /me/settings → UserSettingsRead{autosave_enabled}`, 공통 `ErrorResponse
    {code,message,field_errors}`, 401=`unauthenticated`. API 형태를 발명하지 않고 이 계약을 그대로 소비한다.
  - 세션은 Starlette `SessionMiddleware` 서명 쿠키(same_site=lax) → 프론트는 `credentials: "include"`로
    쿠키를 실어보내고 토큰/헤더 관리가 불필요. 401은 백엔드가 세션 무효/비활동/삭제에서 일괄 산출.
  - 권한은 워크스페이스 단위 role(owner≥editor≥viewer)만 + admin bypass(INV-1·2·3). 프론트 게이팅은
    백엔드 resolver 판정을 미러링하는 **UI 편의**일 뿐 보안 경계가 아님 → 서버가 최종 강제.

## Research Log

### 백엔드 소비 계약(단일 소스) 확인
- **Context**: FE 공통 레이어가 무엇을 부트스트랩·파싱해야 하는지 확정 필요.
- **Sources Consulted**: `s01-contract-foundation/design.md`(§API Catalog·§Errors·§SessionAuth·
  §PermissionResolver), `backend/app/auth/router.py`, `backend/app/user_settings/router.py`,
  `backend/app/auth/schemas.py`, `backend/app/user_settings/schemas.py`.
- **Findings**:
  - `/auth/me`·`/auth/logout`·`/auth/password`는 `get_current_user`로 보호(미인증·비활동·삭제 → 401).
    `/auth/login`은 공개. 세션 부트스트랩은 `/auth/me` 200/401로 인증 여부를 확정한다.
  - `AuthUserRead`는 `is_admin`을 포함 → 프론트 admin override 판정 근거로 그대로 사용.
  - `ErrorResponse`는 `code`(ErrorCode enum: unauthenticated/forbidden/validation_error/not_found/
    conflict/unprocessable/internal)·`message`·`field_errors[]`. 전 엔드포인트 단일 형태.
  - 첨부 서빙(`GET /attachments/{id}`, `GET /public/{token}/attachments/{aid}`)은 바이너리 응답 →
    API 클라이언트가 JSON 외 응답도 다룰 수 있어야 함.
- **Implications**: API 클라이언트는 (1) base URL 단일화, (2) `credentials:"include"`, (3) 공통
  `ErrorResponse` 파싱+정규화, (4) 401 전역 가로채기, (5) JSON/바이너리 응답 분기를 담당한다. 세션
  컨텍스트는 `/auth/me`(→ `/me/settings`) 부트스트랩만 담당하고 로그인 write는 s17.

### 라우팅 라이브러리 선택
- **Context**: 보호/게스트 라우트 프레임과 `returnTo` 보존·복귀가 필요.
- **Findings**: React Router(v6+ `createBrowserRouter`/`<Navigate>`/`useLocation`)가 SPA 표준이며
  중첩 라우트 레이아웃·로더·리다이렉트를 기본 제공. `returnTo`는 로그인 리다이렉트 시 `location.pathname
  + search`를 쿼리/state로 보존하고 로그인 성공 후 복원하는 패턴이 표준.
- **Implications**: 보호 라우트는 세션 컨텍스트 확정 전 로딩을 표시(잘못된 리다이렉트 방지), 확정 후
  미인증이면 `returnTo` 보존 리다이렉트. 게스트 라우트(`/share/:token`)는 가드 밖 최상위 라우트로 등록.

### Toast UI Editor 단일 래퍼(편집=WYSIWYG+markdown, 읽기=viewer)
- **Context**: steering 결정 — 편집/읽기 렌더 경로 이원화 금지.
- **Sources Consulted**: `.kiro/steering/tech.md`(Editor·Frontend 결정), Toast UI Editor React 통합
  (`@toast-ui/editor` + `@toast-ui/react-editor`의 `Editor`/`Viewer`).
- **Findings**: Toast UI Editor는 편집기(`initialEditType: "wysiwyg"`, 툴바로 markdown 토글)와 별도
  `Viewer`(읽기 전용 렌더러)를 제공. "렌더 경로 이원화 금지"는 **feature가 직접 두 컴포넌트를 선택·구성
  하지 못하게 한다**는 의미 → 공통 래퍼가 `mode`(edit|read) 단일 진입점으로 내부에서 Editor/Viewer를
  선택하고 동일 콘텐츠 계약을 노출한다.
- **Implications**: 래퍼는 `mode`·`initialContent`·현재 콘텐츠 getter(ref/`getMarkdown`)를 노출하고,
  자동저장/lock 등 정책 동작은 넣지 않는다(s20 소비). CSS import(`@toast-ui/editor/dist/toastui-editor.css`
  등)는 래퍼가 단일 소유.

### Tailwind CSS 4 + Vite 통합
- **Context**: steering이 Tailwind CSS 4 명시.
- **Findings**: Tailwind CSS 4는 Vite 플러그인(`@tailwindcss/vite`)과 CSS 진입점의 `@import "tailwindcss";`
  방식을 사용(구버전 `tailwind.config.js` + PostCSS 대비 설정 최소화). 단일 전역 CSS에서 import.
- **Implications**: 스캐폴드 태스크에서 Vite 플러그인·전역 CSS 진입점을 공통 레이어가 단일 구성.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 공통 레이어 캡슐화(`src/app`+`src/shared`) + feature 폴더 | 교차 관심사를 공통 레이어가 단일 소유, feature는 소비 | steering 정렬, 드리프트 차단, 백엔드 s01 대칭 | 초기 스캐폴드 비용 | **채택** |
| feature별 자체 API/가드/에디터 | 각 feature가 자기 것 구현 | 초기 자유도 | 401·역할·base URL·에디터 경로 분산(브리프가 금지한 드리프트) | 기각 |
| 상태관리 라이브러리(Redux 등) 전면 도입 | 전역 스토어로 세션·권한 관리 | 대규모에 유리 | L0 범위 과설계, 소규모 폐쇄형에 과함 | 기각(React Context로 충분) |

## Design Decisions

### Decision: 세션 상태를 React Context로 관리(전용 상태관리 라이브러리 미도입)
- **Context**: 세션·admin·설정을 앱 전역에 노출해야 하나 규모가 작다.
- **Alternatives Considered**: 1) Redux/Zustand 전역 스토어  2) React Context + 커스텀 훅
- **Selected Approach**: `SessionProvider` + `useSession()` Context. `/auth/me`→`/me/settings` 부트스트랩,
  `status: loading|authenticated|unauthenticated`, `user`, `settings`, `refresh()` 노출.
- **Rationale**: 소규모 폐쇄형 서비스에 Context로 충분하며 의존성·보일러플레이트 최소화. 재부트스트랩은
  `refresh()`로 s17 로그인/로그아웃이 트리거.
- **Trade-offs**: 대규모 상태 파생에는 불리하나 본 범위에서는 이점(단순성)이 우세.
- **Follow-up**: 리다이렉트 루프 방지(부트스트랩 `/auth/me` 401은 미인증 전이일 뿐 재리다이렉트 아님).

### Decision: 401 인터셉터를 API 클라이언트에 내장(라우터가 아닌 데이터 계층)
- **Context**: 모든 호출부가 401을 개별 처리하면 드리프트.
- **Selected Approach**: 공용 API 클라이언트가 응답 401(`unauthenticated`)을 단일 지점에서 가로채
  `returnTo` 보존 후 로그인으로 라우팅. 라우터 네비게이션 핸들을 클라이언트에 주입해 결선.
- **Rationale**: 호출부 무관하게 일관 처리, 브리프의 "호출부 개별 처리 금지" 충족.
- **Trade-offs**: 클라이언트가 라우팅에 의존 → 네비게이션 주입 seam으로 결합도 관리. 부트스트랩
  `/auth/me` 자체 401은 인터셉터의 리다이렉트 대상에서 제외(미인증 전이).

### Decision: 프론트 권한 게이팅은 UI 편의, 서버 강제 대체 금지
- **Context**: INV-1·2·3을 프론트에서 미러링하되 보안 경계는 서버.
- **Selected Approach**: `hasWorkspaceRole(current, min)` 순수 함수 + `<RequireRole>` 선언형 컴포넌트.
  admin이면 항상 통과. role 데이터는 feature가 주입(현재 WS 멤버십은 s18이 소유).
- **Rationale**: 백엔드 resolver 계약 미러링, 컴포넌트별 역할 비교 산발 방지. 최종 강제는 백엔드 403.
- **Trade-offs**: 클라이언트 게이팅과 서버 판정의 이중 정의 → 위계 규칙(owner≥editor≥viewer)을 단일
  유틸에만 두어 프론트 내부 드리프트를 차단.

## Risks & Mitigations
- 세션 부트스트랩 미완료 중 보호 라우트 판정 → 로딩 상태로 유보(Req 2.5·5.4)로 잘못된 리다이렉트 방지.
- 401 리다이렉트 루프(로그인 경로/부트스트랩 401) → 인터셉터 예외 처리(Req 4.4)로 차단.
- Toast UI Editor 렌더 경로 이원화 유혹 → 단일 래퍼 `mode` 진입점으로만 노출, feature의 직접 Editor/Viewer
  접근 금지(Req 8.1·8.3).
- 클라이언트 게이팅을 보안으로 오인 → 계약 문구로 "서버 강제 대체 아님" 명시(Req 6.6).

## References
- `.kiro/specs/s01-contract-foundation/design.md` — API Catalog·ErrorResponse·SessionAuth·PermissionResolver(INV-1·2·3).
- `.kiro/specs/s01-contract-foundation/requirements.md` — 세션 의존성·권한 resolver·에러 모델 요구.
- `backend/app/auth/router.py`, `backend/app/user_settings/router.py` — 부트스트랩 엔드포인트 실체.
- `.kiro/steering/tech.md`·`structure.md`·`roadmap.md` — Frontend 결정(단일 레이어·라우팅·에디터·설정 단일화).
