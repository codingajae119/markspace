# Research Log — s22-fe-sharing

## Discovery Scope
- 유형: Extension(공통 레이어 `s16`·게이트 `s18`·문서 뷰 `s19` 위에 얹히는 최상위 프론트 feature).
- 검증 기준: `s01-contract-foundation` 단일 소스(카탈로그 행 34~37, `ShareLinkRead`/`ShareLinkUpdate`/
  `PublicDocumentRead`/`PublicDocumentNode`, `ErrorResponse`, INV-8·§4.5 재발급 통일).
- Ground-truth API: `backend/app/sharing/router.py`·`schemas.py`·`service.py`·`public_service.py`(s14-sharing GO).
- 소비 대상: `s16`(apiClient·skipAuthRedirect·게스트 라우트 프레임·권한 게이팅·UI·config), `s18`(is_shareable·role),
  `s19`(문서 표면·status 신호, render 경로 미이원화).

## 계약 공백/seam (발명 대신 seam 처리)
- **S1 — 문서 현재 공유 링크 조회 GET 없음**: 카탈로그는 발급 POST·토글 PATCH·공개 GET만. 관리 UI는 cold load
  시 사전 링크를 열거 불가 → 뮤테이션 응답(`ShareLinkRead`)으로 확인된 링크만 세션 상태로 관리. GET 발명 금지.
- **S2 — 공개 렌더는 content_html만(markdown content 미노출)**: `PublicDocumentNode`는 최소 노출(id·title·
  content_html·children). `s16 EditorWrapper(mode:"read")`는 markdown 입력이라 그대로 재사용 불가. 결정: 게스트
  뷰는 서버 산정 안전 HTML을 읽기 전용 표시하고 **에디터 인스턴스를 만들지 않는다** — tech.md "렌더 경로
  이원화 금지"는 "읽기용 편집기 별도 구성 금지"이며, 에디터 미사용은 위반이 아님. 인증 뷰어와 시각 언어만 일관화.
- **S3 — 공개 렌더 HTML의 첨부 참조가 상대 경로**: 백엔드가 `/attachments/{id}`를 `/public/{token}/attachments/{id}`로
  이미 재작성. 그러나 브라우저는 이를 프론트 origin 기준으로 해석 → 백엔드 서빙 미도달. 결정: `apiConfig.baseUrl`
  기준 절대 경로로 origin만 접두 재작성(순수, id 경계 보존). 범위·격리·보관 판정은 백엔드 소유(재구현 금지).
- **S4 — 관리 UI 마운트 표면·문서 status 신호는 s19 소유**: 관리 패널을 `documentId`+관찰 신호를 받는 자족
  컴포넌트로 설계, 마운트 지점은 cross-spec 리뷰에서 정합. s19 render 경로 수정·이원화 금지.

## 설계 결정
- **관리/게스트 경로 이원화**: 관리(인증·게이팅·`credentials`) vs 게스트(무가드·`skipAuthRedirect`)를 폴더 내부에서
  `shareApi`/`useShareManager`/`ShareLinkPanel` vs `publicApi`/`usePublicDocument`/`PublicDocumentView`로 분리.
- **프론트 링크 vs 공개 API 경로**: 게스트가 여는 링크는 `origin + /share/{token}`(SPA 게스트 라우트)이며,
  백엔드 `share_url`(`/public/{token}` 공개 API)과 구분. `buildShareUrl(token)` 순수 규약으로 구성.
- **무효화 안내(INV-8)**: 무효화 판정·retire는 서버 소유. 프론트는 관찰 신호(문서 status·is_shareable)만 표면화하고
  이전 토큰이 토글로 되살아난다고 오도하지 않음. 발급/재발급은 항상 새 토큰(재발급 시 이전 링크 무효 안내).
- **공개 404 통일**: 무효/미존재/보관/게이트 off를 단일 `unavailable`로 매핑(존재 추정 차단).
- **XSS**: 서버 nh3 새니타이즈 `content_html`만 표시, 프론트 원시 HTML 미생성, 첨부 참조 origin 접두만 수행.

## 대안 비교(요약)
- *공개 뷰에 EditorWrapper 재사용*: 계약이 markdown을 안 주므로 불가(HTML을 markdown으로 오해석). 기각 → content_html 직접 표시.
- *백엔드 share_url을 복사 링크로 사용*: `/public/{token}`은 API 경로라 SPA 게스트 라우트가 아님. 기각 → 프론트 링크 구성.
- *공유 링크 GET 엔드포인트 발명*: 계약 위반(새 API 발명 금지). 기각 → S1 seam(세션 상태 관리).
