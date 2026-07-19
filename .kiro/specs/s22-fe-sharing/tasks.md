# Implementation Plan

> 프론트엔드 공유 도메인 feature(`src/features/sharing`). 모든 태스크는 `frontend/` 하위에서 수행하며 `s16`
> 공통 레이어·`s16` 현재 WS 앰비언트 컨텍스트(`useCurrentWorkspace().isShareable`·`role`)·`s19` 문서 표면을
> 소비/관찰만 한다(재구현 금지; 게이트 토글 UI는 s18). 관리 측(인증·게이팅)과
> 게스트 측(공개·무가드) 경로를 분리해 구현한다. 각 태스크는 단일 책임 경계 안에서 검증 가능한 산출물을 남긴다.

- [ ] 1. 계약 미러 타입 및 도메인 API 어댑터
- [x] 1.1 공유·공개 계약 미러 타입 정의 (P)
  - `src/features/sharing/api/types.ts`에 `ShareLinkRead`(id·created_at·updated_at·document_id·token·is_enabled·
    share_url)·`ShareLinkUpdate`(is_enabled)·`PublicDocumentNode`(id·title·content_html·children)·
    `PublicDocumentRead`(root)를 백엔드 스키마 형태로만 미러링(새 필드 발명 금지)
  - 관찰 가능한 완료: 4개 타입이 `backend/app/sharing/schemas.py`와 1:1 정합하고 `any` 없이 컴파일됨
  - _Requirements: 2.1, 3.1, 6.3, 8.4_
  - _Boundary: SharingTypes_
- [x] 1.2 공유 링크 관리 어댑터(shareApi) 구현
  - `src/features/sharing/api/shareApi.ts`에 `issueLink(documentId)`(`POST /documents/{id}/share`)·
    `toggleLink(documentId, body)`(`PATCH /documents/{id}/share`)를 `s16` `apiClient`로 결선(자체 fetch 금지)
  - 관찰 가능한 완료: 두 호출이 카탈로그 행 34·35 경로·메서드와 일치하고 `ShareLinkRead`를 반환하며 오류는
    `apiClient`가 `ApiError`로 정규화함(단위 테스트로 확인)
  - _Requirements: 2.1, 3.1, 8.1_
  - _Boundary: shareApi_
  - _Depends: 1.1_
- [x] 1.3 공개 렌더 어댑터(publicApi) 구현
  - `src/features/sharing/api/publicApi.ts`에 `getPublicDocument(token)`(`GET /public/{token}`,
    `apiClient.get(..., { skipAuthRedirect: true })`)·`buildAttachmentUrl(token, id)`(절대 API base URL 기반 공개
    서빙 URL)을 구현(공개 호출은 전역 401 리다이렉트 제외)
  - 관찰 가능한 완료: `getPublicDocument`가 `skipAuthRedirect`로 호출되고 `PublicDocumentRead`를 반환하며,
    `buildAttachmentUrl`이 `apiConfig.baseUrl` 기준 절대 경로를 만듦(단위 테스트로 확인)
  - _Requirements: 6.2, 7.1, 8.1, 8.3_
  - _Boundary: publicApi_
  - _Depends: 1.1_

- [ ] 2. 순수 라이브러리(링크 구성·참조 재작성)
- [x] 2.1 프론트 게스트 링크 구성(buildShareUrl) 구현 (P)
  - `src/features/sharing/lib/buildShareUrl.ts`에 `buildShareUrl(token)`을 구현: `` `${origin}${ROUTES.share.replace(":token", token)}` ``
    (`/share/{token}`)로 프론트 게스트 링크를 만들고(s16 `ROUTES.share`는 정적 문자열 `"/share/:token"`이므로 s22가
    `:token`을 치환; 경로 빌더 함수 가정 금지) 백엔드 `share_url`(`/public/{token}`)은 노출하지 않음
  - 관찰 가능한 완료: `buildShareUrl("abc")`가 `<origin>/share/abc`를 반환하고 공개 API 경로를 포함하지 않음(단위 테스트)
  - _Requirements: 2.2, 4.1_
  - _Boundary: buildShareUrl_
  - _Depends: 1.1_
- [x] 2.2 첨부 참조 절대 경로 재작성(rewriteAttachmentRefs) 구현 (P)
  - `src/features/sharing/lib/rewriteAttachmentRefs.ts`에 `rewriteAttachmentRefs(html, token, baseUrl)`을 구현:
    `/public/{token}/attachments/{id}` 참조를 `${baseUrl}/public/{token}/attachments/{id}`로 접두 재작성(숫자 id
    경계 보존, 판정·격리 재구현 금지)
  - 관찰 가능한 완료: `/public/{token}/attachments/5`와 `/attachments/50`이 서로 오염되지 않고 base URL이 접두됨(단위 테스트)
  - _Requirements: 7.1, 7.5_
  - _Boundary: rewriteAttachmentRefs_
  - _Depends: 1.1_

- [ ] 3. 공유 링크 관리(관리 측)
- [x] 3.1 공유 관리 오케스트레이션 훅(useShareManager) 구현
  - `src/features/sharing/hooks/useShareManager.ts`에 발급(`issue`)·토글(`toggle`)·세션 링크 상태
    (`ShareManagerState`)·`buildShareUrl` 결선·무효화 신호 파생(문서 status·`s16` `useCurrentWorkspace().isShareable`)·
    재발급 플래그(INV-8)를 구현(문서 링크 조회 GET 부재 S1로 뮤테이션 응답만 상태화)
  - 관찰 가능한 완료: 발급 200 시 `link`·`frontShareUrl` 반영, 재발급 시 `reissued=true`, 실패 시 상태 불변이며
    status != active 또는 `isShareable`=false에서 `invalidated=true` 파생(통합 테스트로 확인)
  - _Requirements: 1.3, 1.4, 2.1, 2.3, 2.4, 3.1, 3.2, 3.3, 5.1, 5.2, 5.3_
  - _Boundary: useShareManager_
  - _Depends: 1.2, 2.1_
- [x] 3.2 무효화·재발급 안내(InvalidationNotice) 구현 (P)
  - `src/features/sharing/components/InvalidationNotice.tsx`에 관찰 신호(`invalidated`·`reissued`) 기반 안내를
    구현: 무효화 가능·재발급(새 토큰) 필요·이전 토큰은 토글로 미복원(INV-8)을 표시(판정 없음, 신호 표면화만)
  - 관찰 가능한 완료: `invalidated=true`면 재발급 필요 안내가 노출되고, `reissued=true`면 이전 링크 무효 안내가 노출됨
  - _Requirements: 3.4, 5.1, 5.3_
  - _Boundary: InvalidationNotice_
  - _Depends: 1.1_
- [ ] 3.3 링크 복사 버튼(CopyLinkButton) 구현 (P)
  - `src/features/sharing/components/CopyLinkButton.tsx`에 `navigator.clipboard`로 절대 게스트 링크 복사·성공
    피드백·실패 시 선택/복사 폴백·활성 링크 없으면 비활성을 구현
  - 관찰 가능한 완료: 복사 실행 시 클립보드에 `frontShareUrl`이 담기고 성공 피드백이 표시되며, 링크가 null이면
    버튼이 비활성임(UI 테스트로 확인)
  - _Requirements: 4.1, 4.2, 4.3, 4.4_
  - _Boundary: CopyLinkButton_
  - _Depends: 2.1_
- [ ] 3.4 공유 관리 패널(ShareLinkPanel) 구현·게이팅 결선
  - `src/features/sharing/components/ShareLinkPanel.tsx`에 `<RequireRole minimum={EDITOR} currentRole={useCurrentWorkspace().role}>`
    게이팅·`s16` `useCurrentWorkspace().isShareable` 반영(off면 발급/활성화 비활성 + 안내)·발급/토글/복사/안내 결선·`ErrorMessage`
    표면화를 구현(역할 문자열 직접 비교 금지)
  - 관찰 가능한 완료: viewer 컨텍스트에서 패널 미노출, editor/admin에서 노출, `isShareable`=false면 발급 비활성 +
    게이트 off 안내, 발급/토글 오류가 `ErrorMessage`로 표시됨(UI 테스트로 확인)
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 2.2, 3.3, 5.1_
  - _Boundary: ShareLinkPanel_
  - _Depends: 3.1, 3.2, 3.3_

- [ ] 4. 게스트 읽기 전용 뷰(공개 측)
- [ ] 4.1 공개 렌더 로드 훅(usePublicDocument) 구현
  - `src/features/sharing/hooks/usePublicDocument.ts`에 `publicApi.getPublicDocument(token)`(skipAuthRedirect)
    호출·`rewriteAttachmentRefs`로 content_html 절대화·상태(`loading|ready|unavailable|error`)를 구현(404는 사유
    미구분 `unavailable`로 통일)
  - 관찰 가능한 완료: 200 시 참조 재작성된 트리(`ready`), 404 시 `unavailable`(무리다이렉트), 그 외 오류 시
    `error`로 전이됨(통합 테스트로 확인); 게이트 off·문서 trashed로 404가 통일되면 문서·첨부가 함께 접근 불가로 반영됨
  - _Requirements: 5.4, 6.2, 6.3, 6.5, 7.1, 7.4_
  - _Boundary: usePublicDocument_
  - _Depends: 1.3, 2.2_
- [ ] 4.2 공개 문서 재귀 노드(PublicDocumentNodeView) 구현 (P)
  - `src/features/sharing/components/PublicDocumentNodeView.tsx`에 서버 산정 안전 `content_html`을 `s16`
    `ReadOnlyProse` 공용 prose 스타일로 읽기 전용 표시(에디터 인스턴스 미구성·자체 prose 스타일 정의 없이 s16 스타일
    재사용, S2)·`children` 재귀 렌더를 구현(이미지·다운로드는 재작성된 절대 공개 서빙 경로로 로딩)
  - 관찰 가능한 완료: content_html이 읽기 전용으로 표시되고 자식 노드가 중첩 렌더되며 이미지 참조가 절대 공개
    서빙 경로를 가리킴(UI 테스트로 확인)
  - _Requirements: 6.6, 7.2, 7.3_
  - _Boundary: PublicDocumentNodeView_
  - _Depends: 1.1_
- [ ] 4.3 게스트 뷰 컨테이너(PublicDocumentView) 구현
  - `src/features/sharing/components/PublicDocumentView.tsx`에 `usePublicDocument` 상태별 렌더(loading Spinner·
    unavailable EmptyState "링크 사용 불가"·error ErrorMessage·ready 트리)를 구현(변경 조작 일절 없음, `s16`
    `ReadOnlyProse` 공용 prose 소비로 인증 뷰어와 시각 일관)
  - 관찰 가능한 완료: 각 상태가 대응 UI로 렌더되고 편집/이동/삭제 조작이 존재하지 않음(UI 테스트로 확인)
  - _Requirements: 6.1, 6.4, 6.5, 6.6_
  - _Boundary: PublicDocumentView_
  - _Depends: 4.1, 4.2_
- [ ] 4.4 게스트 페이지 및 게스트 라우트 등록(SharePage·SharingRoutes)
  - `src/features/sharing/pages/SharePage.tsx`(`useParams` token 추출 → `PublicDocumentView`)와
    `src/features/sharing/routes.tsx`를 구현하고, `frontend/src/app/router.tsx`(s16) 게스트 라우트(`/share/:token`)
    프레임에 등록만 연결(프레임·가드 없음 규약은 s16 소유·미변경)
  - 관찰 가능한 완료: 세션 없이 `/share/{token}` 진입 시 `SharePage`가 렌더되고 보호 리다이렉트가 강제되지 않음(라우팅 테스트로 확인)
  - _Requirements: 6.1, 8.3_
  - _Boundary: SharingRoutes_
  - _Depends: 4.3_

- [ ] 5. 통합·격리·타입 검증
- [ ] 5.1 관리 패널 문서 표면 마운트 정합(s19 seam)
  - `ShareLinkPanel`을 `documentId`+문서 status 신호를 받는 자족 컴포넌트로 문서 뷰 표면에 마운트하고, s19 render
    경로를 수정·이원화하지 않음(마운트 지점은 cross-spec 리뷰에서 정합, S4)
  - 관찰 가능한 완료: 선택 문서에 대해 관리 패널이 노출되고 문서 status 변화가 무효화 안내에 반영되며, s19 뷰어
    render 경로가 변경되지 않음
  - _Requirements: 1.1, 5.1_
  - _Boundary: ShareLinkPanel_
  - _Depends: 3.4_
- [ ] 5.2 오류 표면화·공개 무리다이렉트·feature 격리 통합 검증
  - 발급/토글의 401(전역 인터셉터)·403·404·409 표면화, 공개 호출의 `skipAuthRedirect`, 다른 feature 직접 import
    부재를 통합적으로 검증
  - 관찰 가능한 완료: 관리 401이 로그인 리다이렉트, 공개 401 미리다이렉트, 403/404/409가 `ErrorMessage`로 표시되고
    `src/features/*` 간 직접 import가 없음
  - _Requirements: 8.1, 8.2, 8.3, 8.5_
  - _Boundary: shareApi, publicApi_
  - _Depends: 3.4, 4.4_
- [ ]* 5.3 단위·통합 테스트 및 타입체크
  - `buildShareUrl`·`rewriteAttachmentRefs`·`shareApi`/`publicApi`·`useShareManager`·`usePublicDocument` 테스트와
    `tsc --noEmit`(strict)·`vite build`를 수행
  - 관찰 가능한 완료: 지정 테스트가 통과하고 strict 타입체크·빌드가 `any` 없이 성공함
  - _Requirements: 2.1, 3.1, 4.1, 6.2, 7.1, 8.4_
  - _Boundary: SharingTypes, shareApi, publicApi, buildShareUrl, rewriteAttachmentRefs_
  - _Depends: 5.2_

## Implementation Notes

> 구현 시작 전 부모 컨트롤러가 코드베이스에서 검증한 s16 소비 계약·백엔드 ground-truth·컨벤션. 각 태스크는 이를 전제로 소비만 하며 재구현하지 않는다.

### s16 공통 레이어 소비 계약 (검증됨 — 경로·시그니처 정확)
- `@/config` → `apiConfig.baseUrl: string`.
- `@/shared/api/client` → `apiClient.{get,post,patch,del}<T>(path, [body], options?)`. `RequestOptions`: `{method, body, responseType?: "json"|"blob", signal?, skipAuthRedirect?: boolean}`. 2xx→`T`(json) 또는 `Blob`; 그 외→`ApiError` throw. 401(비-skip·비-로그인경로)이면 전역 리다이렉트. **테스트에서 `vi.mock("@/shared/api/client", () => ({ apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() } }))` 로 모킹**(s21 attachmentApi.test.ts 패턴).
- `@/shared/api/errors` → `class ApiError`(`.status`·`.code`·`.message`·`.fieldErrors: FieldError[]`·`.raw?`), `ErrorResponse`·`ErrorCode`·`FieldError`·`parseErrorResponse`.
- `@/app/routes` → `ROUTES`(`{login:"/login", root:"/", share:"/share/:token"}` `as const`). **`ROUTES.share` 는 정적 문자열 `"/share/:token"` — 경로 빌더 함수 아님**(buildShareUrl 이 `:token` 치환).
- `@/app/routeModule` → `interface RouteModule { scope: "protected"|"guest"; routes: RouteObject[] }` (react-router-dom `RouteObject`). feature 는 `RouteModule[]` export 만 하면 main.tsx 취합. 게스트 프레임에 동일 path(`/share/:token`) 등록 시 s16 플레이스홀더가 **치환**됨(router.tsx override 로직).
- `@/shared/auth/roles` → `enum Role { VIEWER=1, EDITOR=2, OWNER=3 }`.
- `@/shared/auth/permissions` → `hasWorkspaceRole({currentRole: Role|null, isAdmin: boolean, minimum: Role}): boolean`.
- `@/shared/auth/RequireRole` → `RequireRole` 컴포넌트, props `{minimum: Role, currentRole: Role|null, fallback?, children}`. **admin override 는 내부에서 `useSession()` 으로 자체 판정**(호출자는 `currentRole` 만 주입, `useCurrentWorkspace().role`).
- `@/shared/editor/ReadOnlyProse` → `ReadOnlyProse` 컴포넌트, props `{html?: string, children?: ReactNode}`. `html` 은 **이미 sanitize 된 신뢰 HTML** 가정(컨테이너는 sanitize 안 함). 백엔드 `content_html` 은 nh3 sanitize 됨 → 그대로 `html` prop 으로 전달 안전.
- `@/app/workspace-context/useCurrentWorkspace` → `useCurrentWorkspace(): CurrentWorkspaceContextValue`(`{status, workspaces, currentWorkspace, workspaceId: string|null, role: Role|null, isShareable: boolean, selectWorkspace, refresh}`). Provider 밖 호출 시 throw.
- `@/shared/ui` (배럴) → `Button`·`Spinner`·`EmptyState`·`ErrorMessage` + prop 타입.

### 백엔드 ground-truth (backend/app/sharing/schemas.py·router.py — 1:1 미러, 발명 금지)
- `ShareLinkRead`: `id:number`·`created_at:string`·`updated_at:string|null`(컬럼 부재로 항상 null)·`document_id:number`·`token:string`·`is_enabled:boolean`·`share_url:string`(서버 산정 `/public/{token}`).
- `ShareLinkUpdate`: `is_enabled:boolean`.
- `PublicDocumentNode`: `id:number`·`title:string`·`content_html:string`(nh3 sanitize)·`children:PublicDocumentNode[]`.
- `PublicDocumentRead`: `root:PublicDocumentNode`.
- 라우트: `POST /documents/{id}/share`→ShareLinkRead(401,403,404,409); `PATCH /documents/{id}/share`(body ShareLinkUpdate)→ShareLinkRead(401,403,404,409); `GET /public/{token}`(skipAuthRedirect)→PublicDocumentRead(404); 첨부 서빙 `GET /public/{token}/attachments/{aid}`(binary, 브라우저 직접).

### 컨벤션 (검증됨)
- TS strict + `verbatimModuleSyntax`(타입은 `import type`/`export type` 분리) + `noUnusedLocals` + `noUnusedParameters`. **`any` 금지**.
- 컴포넌트 파일 PascalCase, 훅/유틸 camelCase. 경로 alias `@`→src, 같은 feature 내부는 상대 import. **다른 feature 폴더(`src/features/*`) 직접 import 금지**.
- 테스트: vitest globals(`describe/it/expect/vi`), jsdom, `@testing-library/react`(+`user-event`·`jest-dom`). setup `src/test/setup.ts`.
- 문서 주석·UI 텍스트 한국어(spec language=ko), 코드 식별자 영어.
- 검증 명령: `npm test`(vitest run) / `npm run typecheck`(tsc --noEmit) / `npm run build`. 시작 baseline **614 tests passing / 90 files**(무회귀 기준).
