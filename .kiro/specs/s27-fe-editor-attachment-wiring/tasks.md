# Implementation Plan

> 조립 갭(assembly gap) 해소 스펙. 신규 파일 0(테스트 신규 1). 기존 `EditorPane.tsx`·`DocumentEditPage.tsx` 두 파일만 확장하고, s21 브리지·s16 래퍼·백엔드 s12 는 무수정으로 소비만 한다. 태스크 순서는 의존 방향(EditorPane 슬롯 확장 → DocumentEditPage 결선 → 조립 통합 테스트)을 따른다.

- [ ] 1. EditorPane 통과 배선 확장 (renderers + 복합 onReady)

- [x] 1.1 EditorPane 에 renderers 통과 prop 과 복합 onReady 합성 추가
  - `EditorPane` prop 계약에 선택적 `renderers`(첨부 렌더러)와 선택적 `onEditorReady`(브리지 준비 콜백)를 추가한다. 타입은 `@/shared/editor/EditorWrapper` 의 `CustomRenderers`·`EditorHandle` 에서 import 한다(신규 타입 발명 금지).
  - 기존 직접 결선(`onReady={session.bindHandle}`)을 내부 합성 콜백으로 대체한다: 준비된 단일 `EditorHandle` 을 `session.bindHandle`(자동저장 경로)과 `onEditorReady`(업로드 브리지 경로) **양쪽**에 동일 참조로 분배한다(D1).
  - `renderers` 를 `EditorWrapper` 로 그대로 통과시켜 렌더 경로를 이원화하지 않는다. `onEditorReady` 미주입 시 `bindHandle` 만 결선해 기존 소비처와 하위 호환을 유지한다.
  - 편집당 Toast 인스턴스는 정확히 1개만 마운트하고 포크하지 않으며, `session.document === null` 이면 기존대로 마운트하지 않는다.
  - 관찰 가능한 완료: EditorPane 이 `renderers`·`onEditorReady` 를 받아 `EditorWrapper` 로 통과하고, `onReady` 1회 호출 시 동일 `EditorHandle` 이 `bindHandle`·`onEditorReady` 둘 다에 전달되며, 기존 EditorPane 소비 코드가 컴파일·동작을 유지한다.
  - _Requirements: 1.4, 1.5, 2.3, 5.1, 5.3, 6.3_
  - _Boundary: EditorPane_

- [x] 1.2 EditorPane 단위 테스트 확장
  - `renderers` 로 주입한 객체가 `EditorWrapper` prop 에 **동일 참조**로 도달함을 단언한다(R2.3).
  - `EditorWrapper` stub 이 `onReady(mockHandle)` 를 발화하면 `session.bindHandle`·`onEditorReady` 가 **동일 handle** 로 각 1회 호출됨을 단언한다(D1 단일 handle 공유, R5.1).
  - `onEditorReady` 미주입 시 `bindHandle` 만 결선되고 오류가 없음(하위 호환)을 단언한다.
  - 관찰 가능한 완료: `EditorPane.test.tsx` 에 위 3개 단언이 추가되어 통과하고, 기존 EditorPane 테스트가 그대로 통과한다.
  - _Requirements: 2.3, 5.1, 5.3_
  - _Boundary: EditorPane 테스트_
  - _Depends: 1.1_

- [ ] 2. DocumentEditPage 브리지·게이팅·렌더러 결선

- [ ] 2.1 (P) DocumentEditPage 에서 업로드 브리지 호출·canUpload 도출·uploadDocumentId 정규화·렌더러 주입
  - `@/features/attachment` 배럴에서 `useEditorUploadBridge`·`buildAttachmentRenderers` 를 인가된 소비 seam 으로 import 한다(D2). attachment 외 다른 feature 는 import 하지 않는다.
  - `canUpload` 를 s16 공통 게이팅 유틸 `hasWorkspaceRole({ currentRole: scope.role, isAdmin: scope.isAdmin, minimum: Role.MEMBER })` 단일 경로로 도출한다 — 자체 role 비교 로직을 흩뿌리지 않는다(R4.5).
  - 브리지용 `uploadDocumentId` 를 `number | null` 로 정규화(비수치 `:id` → null)한다. 기존 세션·배너용 `documentId = Number(id)` 계약은 유지하고 브리지용 값만 추가한다(R4.3).
  - `useEditorUploadBridge({ documentId: uploadDocumentId, canUpload })` 를 렌더 트리 안에서 무조건 호출하고, `buildAttachmentRenderers()` 를 `useMemo(..., [])` 로 안정화한다(EditorWrapper effect 재실행 방지).
  - EditorPane 에 `onImagePaste={bridge.onImagePaste}`·`onFileDrop={bridge.onFileDrop}`·`renderers={renderers}`·`onEditorReady={bridge.onReady}` 를 전달한다.
  - 관찰 가능한 완료: 편집 권한자(member↑/admin) 진입 시 `canUpload=true` 로 브리지에 주입되고 네 슬롯이 EditorPane 에 결선되며, role=viewer/null 또는 비수치 id 에서는 브리지 입력이 각각 `canUpload=false`·`documentId=null` 로 도출된다.
  - _Requirements: 1.1, 1.2, 2.1, 2.2, 4.1, 4.2, 4.3, 4.5, 5.1, 6.1_
  - _Boundary: DocumentEditPage_
  - _Depends: 1.1_

- [ ] 2.2 DocumentEditPage 단위 테스트 확장
  - `scope.role`(member/owner/null)·`isAdmin` 조합별로 `canUpload` 도출 결과가 브리지 입력·진입점 활성에 반영됨을 단언한다(R4.1·4.2·4.5).
  - 비수치 라우트 `:id` 에서 브리지 `documentId` 가 null 로 정규화됨을 단언한다(R4.3).
  - EditorPane 목킹 상태에서 `onImagePaste`·`onFileDrop`·`renderers`·`onEditorReady` 네 prop 이 브리지·렌더러 값으로 결선됨을 단언한다.
  - 관찰 가능한 완료: `DocumentEditPage.test.tsx` 에 canUpload 도출·id 정규화·브리지 prop 결선 단언이 추가되어 통과하고 기존 테스트가 유지된다.
  - _Requirements: 4.1, 4.2, 4.3, 4.5_
  - _Boundary: DocumentEditPage 테스트_
  - _Depends: 2.1_

- [ ] 3. 조립 레벨 통합 테스트 (결선 갭 회귀 방지)

- [ ] 3.1 붙여넣기/드롭 → 업로드 → 자리표시자 치환 종단 통합 테스트 신규 작성
  - `DocumentEditPage`+`EditorPane`+s21 브리지를 실제로 마운트하고 `@/shared/editor/EditorWrapper` 와 attachment API(`apiClient`)만 목킹한다. `EditorWrapper` stub 은 수신 props 를 기록하고 `onReady(mockHandle)`·`onImagePaste(file)`·`onFileDrop(file)` 를 발화한다.
  - 붙여넣기 종단(R1.1·3.1): `onImagePaste(file)` 발화 → `handle.insert(placeholder)` 호출 + `POST /attachments` 발생 단언.
  - 성공 치환(R3.2): 201 mock → `handle.replaceRange` 가 `/attachments/{id}` 참조로 치환 단언. 실패 치환(R3.3): 4xx mock → `handle.replaceRange` 가 오류 마커로 치환 단언.
  - 드롭 종류 미지정(R1.2): `onFileDrop(file)` → `startUpload` 에 `kind` 미포함(백엔드 추론 위임) 단언.
  - 렌더러 결선(R2.1·2.2 배선 검증): `buildAttachmentRenderers()` 산출물이 EditorWrapper `renderers` 에 도달함을 단언한다. **라이브 blob DOM 실렌더 검증은 D3 `.outerHTML` 직렬화 seam 한계로 유보**함을 테스트에 명시적 주석으로 남긴다.
  - canUpload 게이팅 종단(R4.2): role=null 이면 `onImagePaste(file)` 발화가 no-op(`POST` 미발생)임을 단언한다.
  - 관찰 가능한 완료: `DocumentEditPage.integration.test.tsx` 신규 파일이 페이지→pane→래퍼 slot 결선 경로를 관측하며 위 시나리오를 모두 통과해, 소비처 0 조립 갭 회귀를 고정한다.
  - _Requirements: 1.1, 1.2, 2.1, 2.2, 3.1, 3.2, 3.3, 3.5, 4.2, 6.4_
  - _Boundary: DocumentEditPage 통합 테스트_
  - _Depends: 1.1, 2.1_
