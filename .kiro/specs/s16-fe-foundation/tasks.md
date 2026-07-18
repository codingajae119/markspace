# Implementation Plan

> 프론트엔드 공통 레이어(L0). 모든 태스크는 `frontend/` 하위에서 수행하며, feature 화면(s17~s22)은 이
> spec 범위 밖이다. 각 태스크는 단일 책임 경계 안에서 검증 가능한 산출물을 남긴다.
>
> **cross-spec 리뷰 반영(교차관심 단일 소유)**: 아래 태스크 중 현재 WS 앰비언트 컨텍스트(3.4)·라우트/Provider
> 등록 메커니즘(3.5)·`RequireAdmin`(4.3)·공용 `Page<T>`/WorkspaceRead 타입(5.3)·`ReadOnlyProse`(5.4)·
> EditorWrapper capability 확장(6.2)이 만드는 표면은 **s17~s22가 재구현 없이 소비**한다(roadmap "교차관심
> 단일 소유 정정"). 컨슈머는 각 컨텍스트/타입의 동결된 단일 형태에 정확히 바인딩한다.

- [ ] 1. 프론트엔드 스캐폴드 및 설정 단일화
- [ ] 1.1 Vite + React + Tailwind CSS 4 + TypeScript strict 스캐폴드 생성
  - `frontend/`에 `package.json`(dev/build/typecheck 스크립트)·`index.html`(root div)·`src/main.tsx` 최소
    부팅·`vite.config.ts`(`@vitejs/plugin-react` + `@tailwindcss/vite` + `@/` alias)·`tsconfig.json`(`strict: true`,
    path alias) 구성
  - 관찰 가능한 완료: `frontend/`에서 dev 서버가 기동되어 루트 화면이 렌더되고, `tsc --noEmit`이 오류 없이 통과
  - _Requirements: 1.1, 1.2, 1.5_
  - _Boundary: Scaffold_
- [ ] 1.2 단일 설정 파일과 Tailwind 전역 진입 구성
  - `src/config.ts`(`apiConfig.baseUrl`을 단일 Vite env `VITE_API_BASE_URL`에서 읽음)·`.env.example`·
    `src/index.css`(`@import "tailwindcss";`)를 생성하고 `main.tsx`에서 전역 CSS import
  - 관찰 가능한 완료: 하드코딩 base URL 상수가 코드 전역에 없고, `apiConfig.baseUrl`이 단일 지점에서만 노출되며,
    Tailwind 유틸 클래스가 화면에 적용됨
  - _Requirements: 1.3, 1.4_
  - _Boundary: AppConfig_
  - _Depends: 1.1_

- [ ] 2. 공용 API 클라이언트 및 에러 계약
- [ ] 2.1 ErrorResponse 타입·파싱·ApiError 구현 (P)
  - `src/shared/api/errors.ts`에 `ErrorCode`·`FieldError`·`ErrorResponse` 타입, `ApiError` 클래스,
    `parseErrorResponse(status, body)`를 구현(백엔드 계약 미러링, 새 코드/필드 발명 금지)
  - 관찰 가능한 완료: 정형 `ErrorResponse` 본문이 `ApiError`로 매핑되고, 비정형/파싱 불가 본문은 `internal`
    기본으로 정규화됨(단위 테스트로 확인)
  - _Requirements: 3.3, 3.4_
  - _Boundary: ApiErrors_
  - _Depends: 1.1_
- [ ] 2.2 401 인터셉터용 네비게이션 주입 seam 구현 (P)
  - `src/shared/api/navigation.ts`에 `setNavigator(nav)`·`redirectToLogin(currentPath)`를 구현(라우팅을 정적
    import 하지 않고 런타임 주입, `returnTo` 보존 포함)
  - 관찰 가능한 완료: 주입된 navigator가 없으면 안전하게 무시되고, 주입 후 `redirectToLogin` 호출 시 `returnTo`가
    보존된 로그인 경로로 이동 요청이 전달됨
  - _Requirements: 4.1, 4.2, 4.4_
  - _Boundary: NavSeam_
  - _Depends: 1.1_
- [ ] 2.3 공용 fetch 래퍼(apiClient) 구현
  - `src/shared/api/client.ts`에 `apiRequest<T>`/`apiClient`를 구현: `apiConfig.baseUrl` 기준 URL,
    `credentials:"include"`, json/blob 응답 분기, 오류 시 `ApiError` throw, 401(비-`skipAuthRedirect`,
    비-로그인경로)이면 `redirectToLogin` 호출
  - 관찰 가능한 완료: 2xx json/blob이 타입 안전하게 반환되고, 401 응답에서 `skipAuthRedirect` 여부에 따라
    리다이렉트가 호출/생략됨(단위 테스트로 확인)
  - _Requirements: 3.1, 3.2, 3.5, 4.1, 4.2, 4.3, 4.4_
  - _Boundary: ApiClient_
  - _Depends: 1.2, 2.1, 2.2_

- [ ] 3. 라우터 셸 및 세션 컨텍스트
- [ ] 3.1 라우트 경로 상수 및 returnTo 규약 구현 (P)
  - `src/app/routes.ts`에 `ROUTES`(login·root·share)·`RETURN_TO_PARAM`·`buildLoginPath`·`resolveReturnTo`를 구현
  - 관찰 가능한 완료: `buildLoginPath`가 인코딩된 `returnTo`를 붙이고 `resolveReturnTo`가 이를 복원하며, 없을 때
    기본 root를 반환(단위 테스트로 확인)
  - _Requirements: 2.2, 2.3_
  - _Boundary: Routes_
  - _Depends: 1.1_
- [ ] 3.2 세션 컨텍스트 부트스트랩(SessionProvider + useSession) 구현
  - `src/app/session/SessionProvider.tsx`·`useSession.ts`에서 `GET /auth/me`(`skipAuthRedirect:true`) →
    성공 시 `GET /me/settings` 부트스트랩, `SessionState`(loading|authenticated|unauthenticated) + `user`
    (is_admin 포함) + `settings` + `refresh()` 노출
  - 관찰 가능한 완료: 200이면 authenticated로 전이하며 settings가 채워지고, 401이면 리다이렉트 없이
    unauthenticated로 전이됨(통합 테스트로 확인)
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_
  - _Boundary: SessionProvider_
  - _Depends: 2.3_
- [ ] 3.3 보호/게스트 라우트 프레임 구현
  - `src/app/router.tsx`·`ProtectedRoute.tsx`에서 라우트 트리를 정의: 게스트 라우트(`/share/:token`, 가드 없음)와
    보호 영역(`ProtectedRoute` → loading 유보 / unauthenticated면 `returnTo` 보존 리다이렉트 / authenticated면
    `AppLayout`+자식). 하위 spec 화면 등록 지점 노출
  - 관찰 가능한 완료: 미인증 상태로 보호 경로 진입 시 `returnTo` 보존 로그인 리다이렉트, `/share/:token`은 세션
    없이 렌더, 부트스트랩 중에는 로딩 표시(통합 테스트로 확인)
  - _Requirements: 2.1, 2.2, 2.4, 2.5, 4.3_
  - _Boundary: Router, ProtectedRoute_
  - _Depends: 3.1, 3.2_
- [ ] 3.4 현재 워크스페이스 앰비언트 컨텍스트(CurrentWorkspaceProvider + useCurrentWorkspace) 구현
  - `src/app/workspace-context/`에 `types.ts`(동결된 `CurrentWorkspaceContextValue`)·`CurrentWorkspaceProvider.tsx`
    (`GET /workspaces`→`Page<WorkspaceRead>` 로드, 현재 WS 선택 localStorage 영속·복원, `workspaceId`·`role`·
    `isShareable` 파생 접근자, `selectWorkspace`·`refresh` 노출)·`useCurrentWorkspace.ts`를 구현. `role` 값은
    s18 멤버십 경로 주입 전제로 필드·기본값(null)만 소유(백엔드 `WorkspaceRead`에 호출자 role 없음)
  - 관찰 가능한 완료: 인증 후 목록이 로드되어 `status` ready/empty 확정, `selectWorkspace`가 선택을 영속하고
    재로드 시 복원되며, `useCurrentWorkspace()`가 단일 형태를 반환함(통합 테스트로 확인)
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_
  - _Boundary: CurrentWorkspaceProvider, useCurrentWorkspace_
  - _Depends: 3.2, 5.3_
- [ ] 3.5 라우트/Provider 등록 메커니즘(RouteModule 취합 + Provider 합성 슬롯) 구현 (P)
  - `src/app/routeModule.ts`(`RouteModule`{scope,routes} 타입 + `composeRouter(modules)` 취합, 보호/게스트 슬롯
    분류)·`src/app/providers.tsx`(`composeProviders` 합성 슬롯)를 구현. feature는 라우터/main 수기 편집 없이
    `RouteModule[]` export만으로 등록
  - 관찰 가능한 완료: 샘플 보호/게스트 `RouteModule`을 취합하면 각 슬롯에 배치되고, Provider 배열이 순서대로
    합성됨(단위 테스트로 확인)
  - _Requirements: 10.1, 10.2, 10.3, 10.4_
  - _Boundary: RouteRegistry, ProviderComposition_
  - _Depends: 3.1_

- [ ] 4. 권한 게이팅 유틸 (INV-1·2·3)
- [ ] 4.1 Role 위계 및 hasWorkspaceRole 순수 유틸 구현 (P)
  - `src/shared/auth/roles.ts`(`Role` VIEWER<EDITOR<OWNER)·`permissions.ts`(`hasWorkspaceRole({currentRole,
    isAdmin,minimum})`)를 구현: admin이면 항상 true, 아니면 위계 비교, currentRole=null이면 거부
  - 관찰 가능한 완료: viewer→editor 요구 거부, owner→editor 요구 통과, admin은 role 무관 통과가 단위 테스트로 확인됨
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.6_
  - _Boundary: RolePermissions_
  - _Depends: 1.1_
- [ ] 4.2 선언형 게이팅 컴포넌트 RequireRole 구현 (P)
  - `src/shared/auth/RequireRole.tsx`에서 `minimum`·`currentRole`·`fallback`·`children`을 받아 `hasWorkspaceRole`
    (isAdmin은 `useSession`에서 취득) 충족 시에만 children 렌더
  - 관찰 가능한 완료: viewer 컨텍스트에서 editor 요구 children 미노출, admin 컨텍스트에서 노출됨(UI 테스트로 확인)
  - _Requirements: 6.5_
  - _Boundary: RequireRole_
  - _Depends: 4.1, 3.2_
- [ ] 4.3 admin 라우트 게이팅 컴포넌트 RequireAdmin 구현 (P)
  - `src/shared/auth/RequireAdmin.tsx`에서 `useSession()`의 `is_admin`(INV-3)으로만 판정하여 admin 전용
    children을 게이팅(워크스페이스 role과 독립). `fallback` 미충족 시 대체. s18 admin 콘솔이 소비(재구현 금지)
  - 관찰 가능한 완료: is_admin=true 컨텍스트에서 children 노출, 비-admin에서 미노출/대체됨(UI 테스트로 확인)
  - _Requirements: 13.1, 13.2, 13.3_
  - _Boundary: RequireAdmin_
  - _Depends: 3.2_

- [ ] 5. 공용 UI·레이아웃·에러 경계
- [ ] 5.1 공용 UI 프리미티브 및 에러 표시 유틸 구현 (P)
  - `src/shared/ui/`에 `Button`·`Spinner`·`EmptyState`·`ErrorMessage`(ApiError의 message·field_errors 표시)와
    배럴 `index.ts`를 Tailwind 4로 구현
  - 관찰 가능한 완료: 각 프리미티브가 렌더되고 `ErrorMessage`가 `field_errors`를 목록으로 표시함(UI 테스트로 확인)
  - _Requirements: 7.1, 7.4, 7.5_
  - _Boundary: UiPrimitives_
  - _Depends: 1.2, 2.1_
- [ ] 5.2 전역 앱 레이아웃 및 에러 경계 구현 (P)
  - `src/app/AppLayout.tsx`(인증 영역 공통 프레임, children 슬롯)·`src/app/ErrorBoundary.tsx`(렌더 예외 포착 →
    복구 화면)를 구현
  - 관찰 가능한 완료: 자식에서 던진 렌더 예외가 앱 전체 크래시 없이 복구 화면으로 표시됨(UI 테스트로 확인)
  - _Requirements: 7.2, 7.3_
  - _Boundary: AppLayout, ErrorBoundary_
  - _Depends: 1.1_
- [ ] 5.3 공용 Page<T> 및 WorkspaceRead 미러 타입 구현 (P)
  - `src/shared/types/page.ts`(`Page<T> = { items: T[]; total: number }` — 백엔드 `base.py` 정확 미러, limit/
    offset 없음)·`src/shared/types/workspace.ts`(`WorkspaceRead` 미러: id·created_at·updated_at·name·
    is_shareable·trash_retention_days)를 구현. 필드 발명 금지
  - 관찰 가능한 완료: `Page<T>`가 items·total만 갖고 `tsc`가 통과하며, s18/s19/s20이 import할 단일 정의가 존재함
  - _Requirements: 9.1, 11.1, 11.2_
  - _Boundary: SharedTypes_
  - _Depends: 1.1_
- [ ] 5.4 읽기 전용 prose 스타일(ReadOnlyProse) 구현 (P)
  - `src/shared/editor/prose.css`(공용 prose 스타일)·`ReadOnlyProse.tsx`(html 또는 children을 공용 prose로
    감쌈)를 구현하여 `EditorWrapper(mode:'read')`와 s22 공개 `content_html` 뷰가 동일 스타일을 소비
  - 관찰 가능한 완료: `ReadOnlyProse`가 sanitized html/children을 공용 prose 스타일로 렌더하고, read 모드와
    게스트 뷰가 동일 시각 언어로 렌더됨(UI 테스트로 확인)
  - _Requirements: 12.1, 12.2_
  - _Boundary: ReadOnlyProse_
  - _Depends: 1.2_

- [ ] 6. Toast UI Editor 단일 래퍼
- [ ] 6.1 EditorWrapper(edit/read 단일 진입점) 구현
  - `src/shared/editor/EditorWrapper.tsx`에서 `mode:"edit"|"read"`·`initialContent`·`onReady(handle)`를 받아
    edit면 Toast Editor(WYSIWYG 기본 + markdown 토글)·read면 Toast Viewer를 내부 선택하고, `EditorHandle.
    getMarkdown()`을 노출. Toast UI CSS import를 이 래퍼가 단일 소유(자동저장/lock 동작은 미구현)
  - 관찰 가능한 완료: 동일 컴포넌트로 mode=edit는 WYSIWYG+markdown 토글, mode=read는 viewer 렌더가 확인되고
    `onReady` 핸들의 `getMarkdown()`이 현재 콘텐츠를 반환함(UI 테스트로 확인). read 모드는 `ReadOnlyProse` 소비
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
  - _Boundary: EditorWrapper_
  - _Depends: 1.2, 5.4_
- [ ] 6.2 EditorWrapper capability 확장(붙여넣기/드롭 훅·삽입/치환·커스텀 렌더러) 구현
  - `EditorWrapper`에 `onImagePaste(file)`·`onFileDrop(file)` 이벤트 구독 슬롯, `EditorHandle.insert`/
    `replaceRange`(업로드 placeholder→최종 참조 치환), `renderers.customImageRenderer`/`customHTMLRenderer`
    오버라이드(edit·read 양 모드 공통)를 추가. 실제 업로드·blob 인증 로딩 동작은 미구현(s21 소비 계약만)
  - 관찰 가능한 완료: 붙여넣기/드롭 시 콜백이 파일과 함께 호출되고, `insert`/`replaceRange`가 콘텐츠를 변경하며,
    커스텀 이미지 렌더러가 양 모드에서 호출됨(UI 테스트로 확인). Toast 인스턴스 포크 없이 단일 래퍼 유지
  - _Requirements: 8.6, 8.7, 8.8_
  - _Boundary: EditorWrapper_
  - _Depends: 6.1_

- [ ] 7. 앱 조립 및 검증
- [ ] 7.1 부트스트랩 조립 및 navigator 주입 (통합)
  - `src/main.tsx`에서 `ErrorBoundary` → `SessionProvider` → `CurrentWorkspaceProvider` → (`composeProviders`
    Provider 합성 슬롯) → `RouterProvider`(`composeRouter(RouteModule[])`) 순으로 조립하고, 라우터 준비 시
    `setNavigator`로 네비게이션 핸들을 주입하여 401 인터셉터가 실제 라우팅으로 결선되게 함. 현재 WS 앰비언트
    컨텍스트는 `SessionProvider` 하위에 마운트
  - 관찰 가능한 완료: 앱 로드 시 세션·현재 WS 부트스트랩이 실행되고, 임의 보호 API 호출의 401이 로그인
    리다이렉트로 이어지며, 라우트/Provider가 등록 메커니즘으로 합성됨(수동/통합 확인)
  - _Requirements: 2.1, 4.1, 4.2, 5.1, 9.2, 10.1, 10.3_
  - _Boundary: Bootstrap(app)_
  - _Depends: 2.3, 3.2, 3.3, 3.4, 3.5, 5.2_
- [ ]* 7.2 공통 레이어 단위·통합·UI 테스트 작성
  - `parseErrorResponse`·`hasWorkspaceRole`·`buildLoginPath`/`resolveReturnTo`·`apiClient` 401 분기·
    `composeRouter`/`composeProviders` 취합(단위), SessionProvider·CurrentWorkspaceProvider 부트스트랩·
    ProtectedRoute 판정·게스트 라우트(통합), `RequireRole`·`RequireAdmin`·`EditorWrapper` mode 분기 및
    붙여넣기/드롭·`insert`/`replaceRange`·커스텀 렌더러·`ReadOnlyProse`(UI) 테스트를 추가
  - 관찰 가능한 완료: 위 테스트 스위트가 모두 통과함
  - _Requirements: 2.2, 2.4, 2.5, 3.3, 3.4, 4.4, 5.1, 5.3, 6.3, 6.4, 8.2, 8.3, 8.6, 8.7, 8.8, 9.2, 9.4, 10.1, 12.1, 13.2_
  - _Boundary: Testing_
  - _Depends: 7.1, 4.2, 4.3, 6.1, 6.2, 5.4_
- [ ] 7.3 타입체크·빌드 검증
  - `tsc --noEmit`(strict)와 `vite build`를 실행하여 공통 레이어가 오류 없이 타입 통과·번들됨을 확인
  - 관찰 가능한 완료: 타입체크와 프로덕션 빌드가 오류 없이 완료됨
  - _Requirements: 1.1, 1.2_
  - _Boundary: Scaffold_
  - _Depends: 7.1_
