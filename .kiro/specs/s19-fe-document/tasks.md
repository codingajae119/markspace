# Implementation Plan

> 프론트엔드 문서 도메인 feature(`frontend/src/features/document`). 모든 태스크는 `s16` 공통 레이어
> (`apiClient`·`ApiError`·`Role`/`hasWorkspaceRole`/`RequireRole`·`EditorWrapper`·router shell·`useSession`·
> `useCurrentWorkspace`·`Page<T>`·공용 UI)를 **소비**하며 재구현하지 않는다. 현재 WS 컨텍스트는 `s16` 앰비언트
> 컨텍스트 `useCurrentWorkspace()`(최상위 `workspaceId`·`role`)에서 소비한다(형제 s18 의존 없음). 문서
> status·묶음 전이 판정은 백엔드 엔진 소유이며 UI는 결과·오류만 표면화한다.
> 각 태스크는 단일 책임 경계 안에서 검증 가능한 산출물을 남긴다.

- [ ] 1. 도메인 타입·API·인접 seam 기반
- [ ] 1.1 계약 미러링 타입 정의 (P)
  - `src/features/document/types.ts`에 백엔드 계약을 미러링: `DocumentStatus`·`DocumentRead`·`DocumentCreate`·
    `DocumentUpdate`·`DocumentMoveRequest`·`TrashMemberRead`·`TrashBundleRead`와 프론트 파생 타입
    `DocumentNode`·`DropPosition`. `Page<T>`는 `s16` 공용 타입(`@/shared/types/page`)에서 import(재정의 금지).
    `sort_order`는 불투명 정렬 키(문자열)로 취급
  - 관찰 가능한 완료: 타입이 실제 백엔드 스키마(`document/schemas.py`·`trash/schemas.py`·`schemas/base.py`)와
    필드 1:1로 일치하고 `tsc --noEmit`이 통과함(새 필드 발명 없음)
  - _Requirements: 1.1, 2.1, 3.1, 4.1, 5.1, 6.1, 7.1, 8.1_
  - _Boundary: DocumentTypes_
- [ ] 1.2 문서/휴지통 API 모듈 및 페이지 병합 loader 구현
  - `src/features/document/api/documentApi.ts`에 8개 엔드포인트 호출(`s16` `apiClient` 소비): 생성/목록은
    `/workspaces/{workspace_id}/documents`, 상세/수정/이동/삭제는 `/documents/{id}`(+`/move`), 휴지통은
    `/workspaces/{id}/trash`·`/trash/{bundleId}(/restore)`. `loadAllActiveDocuments`는 `Page.total`까지
    offset 순회로 전체 active 문서 병합
  - 관찰 가능한 완료: 각 메서드가 올바른 경로·본문으로 `apiClient`를 호출하고, `loadAllActiveDocuments`가
    다중 페이지를 하나의 배열로 병합함(단위 테스트로 확인). 오류는 `ApiError`로 전파됨
  - _Requirements: 1.1, 1.2, 3.1, 4.1, 5.1, 6.1, 7.1, 8.1, 8.3, 8.4, 9.6_
  - _Boundary: DocumentApi_
  - _Depends: 1.1_
- [ ] 1.3 문서 스코프 선택자(useDocumentScope) 구현 (P)
  - `src/features/document/hooks/useDocumentScope.ts`에 `s16` 앰비언트 컨텍스트 `useCurrentWorkspace()`를 감싼
    얇은 선택자를 구현: 최상위 접근자 `status`·`workspaceId`(string|null)·`role`만 재노출하고, `isAdmin`은 `s16`
    `useSession()`에서 취득. 중첩 필드(`currentWorkspace` 등) 접근 금지, 컨텍스트 재구현·`useCurrentWorkspace`
    이름 재정의 금지(이름 충돌·드리프트 방지)
  - 관찰 가능한 완료: 선택자가 `{status, workspaceId, role, isAdmin}`를 반환하고 `s16` 최상위 형태에 정확히
    바인딩함(형제 s18 의존 없음). `tsc --noEmit` 통과
  - _Requirements: 9.1, 9.2_
  - _Boundary: useDocumentScope_
  - _Depends: 1.1_

- [ ] 2. 순수 트리·이동 로직 (lib)
- [ ] 2.1 buildTree 순수 함수 구현 (P)
  - `src/features/document/lib/buildTree.ts`에 평면 `DocumentRead[]` → `{roots, nodeById}` 변환: `parent_id`로
    부모-자식 연결, 형제를 `sort_order`(불투명 키) 오름차순 정렬. 프론트 정렬 값 재계산 금지
  - 관찰 가능한 완료: 다층 계층이 올바른 루트 배열로 조립되고 형제 순서가 `sort_order`를 따름(단위 테스트로 확인)
  - _Requirements: 1.1, 1.7_
  - _Boundary: buildTree_
  - _Depends: 1.1_
- [ ] 2.2 resolveAncestors 순수 함수 구현 (P)
  - `src/features/document/lib/resolveAncestors.ts`에 `parent_id` 체인을 루트까지 거슬러 조상 경로
    (루트→현재) 반환. 순환 방지 상한. 별도 API 호출 없음
  - 관찰 가능한 완료: 깊은 노드가 루트→현재 순서 조상 배열을 반환하고 루트 문서는 단일 경로를 반환함(단위 테스트로 확인)
  - _Requirements: 2.1, 2.3, 2.4_
  - _Boundary: resolveAncestors_
  - _Depends: 1.1_
- [ ] 2.3 computeMoveTarget 순수 함수 구현 (P)
  - `src/features/document/lib/computeMoveTarget.ts`에 `DropPosition`(inside/before/after/root)을
    `DocumentMoveRequest`(`new_parent_id`·`before_sibling_id`·`after_sibling_id`)로 매핑. 순환·제약 판정 없음(서버 위임)
  - 관찰 가능한 완료: inside→부모 지정, before/after→대상 부모+형제 기준, root→`new_parent_id=null` 매핑이
    단위 테스트로 확인됨
  - _Requirements: 6.1, 6.2_
  - _Boundary: computeMoveTarget_
  - _Depends: 1.1_

- [ ] 3. 상태 훅 (트리·변이·휴지통)
- [ ] 3.1 useDocumentTree 로드·트리·선택·조상 훅 구현
  - `src/features/document/hooks/useDocumentTree.ts`에서 `loadAllActiveDocuments` → `buildTree`로 트리 구성,
    `status`(loading|ready|error)·`roots`·`nodeById`·`selectedId`·`expandedIds`·`error` 상태와 `reload`·
    `select`·`toggleExpand`·`ancestorsOf`(resolveAncestors 위임)·`applyLocal`(낙관 반영) 노출
  - 관찰 가능한 완료: 로드 성공 시 트리 준비·선택/펼침 토글 동작, 실패 시 error 상태, 빈 WS는 빈 roots가
    통합 테스트로 확인됨
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3, 2.4, 7.1_
  - _Boundary: useDocumentTree_
  - _Depends: 1.2, 1.3, 2.1, 2.2_
- [ ] 3.2 useDocumentMutations 변이 훅 구현
  - `src/features/document/hooks/useDocumentMutations.ts`에 `create`·`rename`·`remove`·`move`를 구현:
    낙관적 반영(`tree.applyLocal`) → `documentApi` 호출 → 성공 확정(이동은 서버 `sort_order` 반영, 삭제는
    `tree.reload`로 묶음 캐스케이드 반영) / 실패 시 원복 + `ApiError`를 `state.error`로 표면화(자체 에러 형태 발명 금지)
  - 관찰 가능한 완료: move가 409/422에서 원복+오류 노출·200에서 서버 반영, remove가 204 후 재조회로 하위
    캐스케이드 반영함이 통합 테스트로 확인됨
  - _Requirements: 3.1, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5, 9.3, 9.4_
  - _Boundary: useDocumentMutations_
  - _Depends: 1.2, 2.3, 3.1_
- [ ] 3.3 useTrash 휴지통 훅 구현 (P)
  - `src/features/document/hooks/useTrash.ts`에 `listTrash` 로드(`Page[TrashBundleRead]`, 페이지네이션)·
    `restore`·`purge`(각 204 후 `reload`)·404 시 오류 표면화+재조회를 구현. 복구 위치·묶음 규칙 판정 없음
  - 관찰 가능한 완료: 목록 로드·복구/완전삭제 후 재조회·404 오류 표면화가 통합 테스트로 확인됨
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.7_
  - _Boundary: useTrash_
  - _Depends: 1.2, 1.3_

- [ ] 4. 트리·breadcrumb·툴바 화면
- [ ] 4.1 DocumentTree·DocumentTreeNode(펼침/접힘·선택·DnD) 구현
  - `src/features/document/components/DocumentTree.tsx`·`DocumentTreeNode.tsx`에서 재귀 트리 렌더·펼침/접힘·
    선택을 구현하고, HTML5 native DnD로 드롭 위치를 `DropPosition`으로 산정해 `onMove` 호출. `canEdit`가
    거짓(viewer)이면 드래그 비활성
  - 관찰 가능한 완료: 노드 토글/선택이 동작하고, editor가 노드를 드롭하면 `computeMoveTarget` 기반 이동이
    호출되며, viewer 컨텍스트에서 드래그가 비활성임이 UI 테스트로 확인됨
  - _Requirements: 1.3, 1.4, 1.5, 1.6, 6.1, 6.3, 6.7_
  - _Boundary: DocumentTree, DocumentTreeNode_
  - _Depends: 3.1, 3.2_
- [ ] 4.2 Breadcrumb 구현 (P)
  - `src/features/document/components/Breadcrumb.tsx`에서 `useDocumentTree.ancestorsOf(selectedId)`로 조상
    경로(루트→현재)를 표시하고 항목 클릭 시 `select`로 전환. 루트 문서는 단일 항목
  - 관찰 가능한 완료: 선택 문서의 조상 경로가 순서대로 표시되고 조상 클릭 시 선택이 전환됨(UI 테스트로 확인)
  - _Requirements: 2.1, 2.2, 2.3_
  - _Boundary: Breadcrumb_
  - _Depends: 3.1_
- [ ] 4.3 ConfirmDialog(파괴적 조작 확인) 구현 (P)
  - `src/features/document/components/ConfirmDialog.tsx`에 삭제·완전삭제 확인 다이얼로그를 구현. 완전삭제는
    **되돌릴 수 없음**을 명시(백엔드 OpenAPI 비가역 계약과 정합). 공용 UI 프리미티브 재사용
  - 관찰 가능한 완료: 확인/취소가 동작하고 완전삭제 변형이 비가역 경고 문구를 표시함(UI 테스트로 확인)
  - _Requirements: 5.1, 8.4_
  - _Boundary: ConfirmDialog_
  - _Depends: 1.1_
- [ ] 4.4 DocumentToolbar(생성·이름변경·삭제, RequireRole 게이팅) 구현
  - `src/features/document/components/DocumentToolbar.tsx`에서 생성(부모 지정)·이름변경·삭제 조작을
    `<RequireRole minimum={EDITOR} currentRole=... >`로 감싸 viewer에게 미노출하고, 각 조작을
    `useDocumentMutations`에 결선. 삭제는 `ConfirmDialog` 경유
  - 관찰 가능한 완료: editor/admin에게만 조작이 노출되고 viewer에게는 숨겨지며, 생성/이름변경/삭제가 변이
    훅을 호출함이 UI 테스트로 확인됨
  - _Requirements: 3.1, 3.6, 4.1, 4.5, 5.1, 5.6, 9.2_
  - _Boundary: DocumentToolbar_
  - _Depends: 3.2, 4.3_

- [ ] 5. 읽기 전용 뷰어
- [ ] 5.1 DocumentViewer(EditorWrapper read 재사용 + 편집 진입 seam) 구현
  - `src/features/document/components/DocumentViewer.tsx`에서 `documentApi.getDocument(id)` 조회 후 `s16`
    `EditorWrapper`를 `mode:"read"`·`initialContent=content`(markdown)로 렌더(자체 에디터 인스턴스 금지,
    `content_html` 미사용으로 렌더 경로 이원화 금지). editor 이상에게만 편집 진입 진입점(버튼) 노출(동작은
    `s20` 위임). 실패 시 `ErrorMessage`
  - 관찰 가능한 완료: 동일 `EditorWrapper(read)`로 문서가 렌더되고, editor에게만 편집 진입 버튼이 노출되며
    viewer는 읽기 전용, 조회 실패 시 오류 표시가 UI 테스트로 확인됨
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_
  - _Boundary: DocumentViewer_
  - _Depends: 1.2_

- [ ] 6. 휴지통 화면
- [ ] 6.1 TrashBundleItem(묶음 행·복구·완전삭제) 구현 (P)
  - `src/features/document/components/TrashBundleItem.tsx`에서 묶음 루트·구성원 요약(`members`: id·parent_id·
    title)·`member_count`·`expires_at`을 표시하고 복구/완전삭제 조작을 노출. 완전삭제는 `ConfirmDialog`(비가역) 경유
  - 관찰 가능한 완료: 묶음 구성원과 만료 예정이 표시되고 복구/완전삭제 콜백이 호출됨이 UI 테스트로 확인됨
  - _Requirements: 8.2, 8.4_
  - _Boundary: TrashBundleItem_
  - _Depends: 4.3_
- [ ] 6.2 TrashList(editor+ 게이팅 목록 화면) 구현
  - `src/features/document/components/TrashList.tsx`에서 `useTrash`로 묶음 목록을 로드해 `TrashBundleItem`
    으로 렌더하고 화면 전체를 `<RequireRole minimum={EDITOR}>`로 게이팅. 복구/완전삭제를 훅에 결선, 빈/로딩/
    오류 상태 표시
  - 관찰 가능한 완료: editor/admin에게만 휴지통 화면이 노출되고 viewer는 접근 불가, 복구/완전삭제 후 목록이
    재조회됨이 통합/UI 테스트로 확인됨
  - _Requirements: 8.1, 8.5, 8.6, 8.7_
  - _Boundary: TrashList_
  - _Depends: 3.3, 6.1_

- [ ] 7. 페이지 조립·라우트 등록·검증
- [ ] 7.1 문서 메인/휴지통 페이지 조립 및 라우트 등록 (통합)
  - `src/features/document/pages/DocumentWorkspacePage.tsx`(트리+breadcrumb+뷰어+툴바 조립)·`TrashPage.tsx`
    (휴지통)와 `src/features/document/routes.tsx`를 구현하고, 문서/휴지통 라우트를 `RouteModule[]`
    (`scope: "protected"`)로 export 하여 `s16` `composeRouter`가 보호 슬롯에 합성하게 함(`router.tsx` 수기 편집
    금지). `useDocumentScope`(s16 `useCurrentWorkspace()`
    래핑)로 workspaceId·role 주입, 401은 전역 인터셉터 위임
  - 관찰 가능한 완료: 보호 라우트 하위에서 문서 화면(트리·breadcrumb·뷰어)과 휴지통 화면이 렌더되고 현재 WS
    컨텍스트가 조작에 연결됨(수동/통합 확인)
  - _Requirements: 7.1, 8.1, 9.1, 9.5, 9.6_
  - _Boundary: DocumentRoutes, DocumentWorkspacePage, TrashPage_
  - _Depends: 4.1, 4.2, 4.4, 5.1, 6.2_
- [ ]* 7.2 단위·통합·UI 테스트 작성
  - `buildTree`·`resolveAncestors`·`computeMoveTarget`·`loadAllActiveDocuments`(단위), `useDocumentTree`·
    `useDocumentMutations`(낙관/복원)·`useTrash`(통합), 권한 게이팅(viewer 미노출/editor·admin 노출)·
    `DocumentViewer` read 렌더·DnD 이동·완전삭제 비가역 확인(UI) 테스트를 추가
  - 관찰 가능한 완료: 위 테스트 스위트가 모두 통과함
  - _Requirements: 1.1, 1.2, 1.7, 2.1, 2.3, 2.4, 3.6, 4.5, 5.2, 5.4, 5.6, 6.1, 6.4, 6.7, 7.2, 7.3, 7.4, 8.1, 8.4, 8.6, 9.2, 9.3, 9.4_
  - _Boundary: Testing_
  - _Depends: 7.1_
- [ ] 7.3 타입체크·빌드 검증
  - `frontend/`에서 `tsc --noEmit`(strict)와 `vite build`를 실행하여 문서 feature가 오류 없이 타입 통과·
    번들됨을 확인(계약 미러링·`any` 금지)
  - 관찰 가능한 완료: 타입체크와 프로덕션 빌드가 오류 없이 완료됨
  - _Requirements: 1.1_
  - _Boundary: Scaffold_
  - _Depends: 7.1_
