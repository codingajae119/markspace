# Research Log — s19-fe-document

## Discovery Scope

- **Feature type**: Extension(공통 레이어 소비형 feature). greenfield 아님 — `s16-fe-foundation` 공통
  레이어와 백엔드 `s07-document-core`·`s10-trash` 실동작 엔드포인트 위에 얹는 문서 도메인 화면.
- **Discovery type**: Integration-focused(light). 신규 외부 기술 도입 최소화, 계약·seam 정합 중심.

## Ground-Truth 계약 확인 (검증 기준 = s01 단일 소스)

실제 백엔드 라우터/스키마를 읽어 API 형태를 발명하지 않고 미러링했다.

- 문서 라우터(`backend/app/document/router.py`): 경로는 **WS-scoped**다 — 생성/목록은
  `/workspaces/{workspace_id}/documents`, 상세/수정/이동/삭제는 `/documents/{id}`, 이동은
  `/documents/{id}/move`. (brief의 `POST /documents`·`GET /documents` 축약 표기 대신 실제 WS-scoped
  경로를 채택.) 게이팅: 조회/목록 VIEWER, 생성/수정/이동/삭제 EDITOR, admin bypass. DELETE는 204,
  엔진 `trash_document`(비active→409).
- 문서 스키마(`backend/app/document/schemas.py`): `DocumentCreate{title, parent_id?}`,
  `DocumentUpdate{title?}`, `DocumentMoveRequest{new_parent_id?, before_sibling_id?, after_sibling_id?}`,
  `DocumentRead`(TimestampedRead + workspace_id·parent_id·title·status·sort_order(Decimal)·
  current_version_id·created_by·content·content_html).
- 휴지통 라우터(`backend/app/trash/router.py`): `GET /workspaces/{id}/trash`(Page[TrashBundleRead]),
  `POST /trash/{bundleId}/restore`(204), `DELETE /trash/{bundleId}`(204, 비가역). 세 경로 모두 EDITOR+.
- 휴지통 스키마(`backend/app/trash/schemas.py`): `TrashBundleRead`(bundle_id=root_document_id·
  root_document_id·root_title·workspace_id·trashed_at·expires_at(파생)·member_count·members),
  `TrashMemberRead{id, parent_id, title}`.
- 공통 엔벨로프(`backend/app/schemas/base.py`): `Page{items, total}`.

## 주요 설계 결정

### 1. 조상(breadcrumb)·트리는 클라이언트 파생, 조상 전용 API 없음
- 계약에 조상/트리 전용 엔드포인트가 없다. 목록(`Page[DocumentRead]`)만 존재.
- **결정**: `loadAllActiveDocuments`로 `total`까지 페이지 병합 후 `buildTree`/`resolveAncestors`로 트리·
  조상 경로를 클라이언트에서 파생. 소규모 폐쇄형 협업 서비스 특성상 WS 문서 수가 크지 않아 전체 병합 로드가
  실용적(대안: 지연 로딩 트리 — 조상 파생 복잡·계약 미지원으로 기각).

### 2. sort_order는 불투명 정렬 키
- 백엔드 `sort_order`는 `Decimal`(중간값 부여 방식). pydantic v2 JSON 직렬화에서 문자열로 나올 수 있다.
- **결정**: 프론트는 `sort_order`를 **불투명 키**로 취급하고 산술·재계산하지 않는다. 정렬은 서버 값 기준
  비교만. 이동 시 새 순서 산정은 서버가 소유(프론트는 before/after 형제 id만 전달).

### 3. 뷰어는 s16 EditorWrapper(mode:"read") 재사용 — 렌더 경로 이원화 금지
- `DocumentRead`에 `content`(markdown)와 `content_html`(안전 렌더 HTML)이 모두 있다.
- **결정**: `content_html`로 별도 HTML 렌더 경로를 만들면 편집/공유 뷰와 이원화된다. steering `tech.md`·
  brief 제약("렌더 경로 이원화 금지")에 따라 `content`(markdown)를 `EditorWrapper(mode:"read")`로 렌더한다.
  이로써 뷰어(s19)·편집(s20)·공유(s22)가 단일 래퍼를 공유. XSS 표면도 축소.

### 4. 상태·묶음 전이는 백엔드 엔진 소유 — UI는 낙관 반영 + 오류 표면화
- 순환·동일 WS·묶음 원자성·복구 위치·비흡수(INV-10·11·12)는 `s07` 엔진이 단독 판정.
- **결정**: 이동/삭제/복구/완전삭제는 낙관적 반영 후 서버 판정(200/204 확정, 409/422/404 복원·표면화). 프론트
  제약 판정 재구현 금지. 삭제는 캐스케이드 범위를 서버가 결정하므로 성공 후 트리 재조회로 반영.

### 5. DnD = HTML5 native Drag and Drop
- **결정**: 트리 규모가 작고 요구가 단순(부모 변경 + 형제 사이 삽입)하여 외부 DnD 라이브러리(dnd-kit 등)를
  도입하지 않고 브라우저 HTML5 DnD로 구현. `computeMoveTarget` 순수 함수로 드롭 위치→요청 매핑을 분리해
  테스트 용이성 확보. (대안: dnd-kit — 의존성·번들 비용 대비 이득 낮아 보류. 필요 시 후속 도입 여지.)

### 6. 현재 WS 컨텍스트는 s16 앰비언트 컨텍스트 소비 (cross-spec 리뷰 반영)
- 문서/휴지통 엔드포인트는 WS-scoped이므로 현재 workspace_id·현재 사용자 role이 필요하다. cross-spec 리뷰
  결과, 현재 WS 앰비언트 컨텍스트(`useCurrentWorkspace()`·`CurrentWorkspaceContextValue`)는 `s16`이 단일
  소유하는 것으로 확정되었다(형제 s18 의존 제거, 단일 upstream `s16`로 수렴).
- **결정**: `s16` `useCurrentWorkspace()`의 **최상위 접근자**(`workspaceId: string|null`·`role`)만 소비하며
  중첩 필드에 접근하지 않는다. 얇은 선택자가 필요하면 `useDocumentScope`로 **이름을 달리하여** s16 훅을
  감싼다(`useCurrentWorkspace` 이름 재정의 금지 — 이름 충돌·드리프트 방지). `isAdmin`은 s16 `useSession()`
  에서 취득. `role` 조달 경로(s18 멤버십)는 s16이 내부 흡수하며, 컨텍스트 형태 변경은 revalidation trigger.

## 리스크 및 완화
- **s16 컨텍스트 형태 변경 리스크**: `CurrentWorkspaceContextValue`(최상위 `workspaceId`·`role`) 변경 시
  이 feature 재검증 → 소비를 `useDocumentScope` 1곳에 캡슐화해 변경 파급을 국소화.
- **대량 문서 시 전체 병합 로드 비용**: 서비스 범위상 WS당 문서 수가 크지 않으나, 필요 시 후속에서 지연
  로딩으로 전환 가능하도록 로더를 `documentApi`에 단일 캡슐화.
- **낙관적 반영 정합성**: 이동/생성 실패 복원 로직을 mutations 훅 단일 지점에 두고, 확정 상태는 트리
  재조회로 수렴시켜 드리프트 방지.
