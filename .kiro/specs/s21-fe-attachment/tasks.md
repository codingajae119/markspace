# Implementation Plan

> 프론트엔드 첨부 UX feature(`frontend/src/features/attachment`). 모든 태스크는 `s16` 공통 레이어
> (`apiClient` multipart/blob·`ApiError`·`EditorWrapper` 계약[`onImagePaste`/`onFileDrop`·`onReady`가 주는
> `EditorHandle.insert`/`replaceRange`·`renderers.customImageRenderer`/`customHTMLRenderer`]·`Role`/
> `hasWorkspaceRole`/`RequireRole`·공용 UI·`useSession`)를 **소비**하며 재구현하지 않는다. 래퍼 이벤트/렌더
> 계약은 `s16` 소유이며 이 feature는 소비 어댑터만 둔다. 업로드 대상 `documentId`는 `s19`/`s20` 인접 seam(동일
> wave 병렬 생성이라 spec 파일 미참조)에서 소비하고, `s20` 편집 표면이 래퍼를 마운트해 이 feature의 브리지
> 핸들러·렌더러를 바인딩한다. 첨부 저장·격리·아카이브(8.6·8.7·8.10)는 백엔드 `s12` 소유이며 이 feature는 서빙
> 결과(404/403)만 관측해 placeholder로 폴백한다. 각 태스크는 단일 책임 경계 안에서 검증 가능한 산출물을 남긴다.

- [ ] 1. 도메인 타입·API 기반
- [x] 1.1 계약 미러링 타입 정의 (P)
  - `src/features/attachment/types.ts`에 백엔드 계약을 미러링: `AttachmentKind`(image|file)·`AttachmentRead`
    (id·workspace_id·document_id·kind·original_name·is_archived·created_at·url)와 프론트 파생 상태 타입
    `UploadItem`·`UploadStatus`·`AttachmentResourceState`. `url`은 서버 산정 참조 규약(`/attachments/{id}`)으로
    취급(재구성 금지)
  - 관찰 가능한 완료: 타입이 실제 백엔드 스키마(`backend/app/attachment/schemas.py`)와 필드 1:1로 일치하고
    `tsc --noEmit`이 통과함(새 필드 발명 없음)
  - _Requirements: 1.1, 2.1, 3.1, 5.1, 7.1_
  - _Boundary: AttachmentTypes_
- [x] 1.2 첨부 API 모듈(업로드 multipart·서빙 blob) 구현
  - `src/features/attachment/api/attachmentApi.ts`에 `uploadAttachment(documentId, file, fileName, kind?)`
    (`POST /documents/{documentId}/attachments`, `FormData`에 file+선택 kind 담아 multipart, 201 `AttachmentRead`)와
    `fetchAttachmentBlob(attachmentId)`(`GET /attachments/{id}`, `responseType:"blob"`, 200 `Blob`)를 `s16`
    `apiClient` 소비로 구현. 자체 fetch·에러 파싱·base URL 하드코딩 금지
  - 관찰 가능한 완료: 업로드가 올바른 경로·FormData로, 서빙이 blob 응답 타입으로 `apiClient`를 호출하고 오류는
    `ApiError`로 전파됨이 단위 테스트로 확인됨
  - _Requirements: 1.1, 3.1, 4.1, 6.1, 6.2_
  - _Boundary: AttachmentApi_
  - _Depends: 1.1_

- [ ] 2. 순수 참조 로직 (lib)
- [x] 2.1 attachmentReference 순수 함수 구현 (P)
  - `src/features/attachment/lib/attachmentReference.ts`에 `buildReferenceMarkdown(att)`(image→`![name](url)`,
    file→`[name](url)`, `url`은 응답값 그대로)·`buildPlaceholderToken(uploadId)`·`replacePlaceholder(content,
    uploadId, replacement)`·`buildErrorMarker(uploadId)`와 참조 파서 `resolveAttachmentReference(href)`
    (`/attachments/{id}`→`{attachmentId}`, 비대상→null)를 구현. 부수효과·첨부 상태 판정 없음
  - 관찰 가능한 완료: kind별 참조 조립, 자리표시자 토큰 생성/치환(동시 다중 토큰 비침범), 참조 파싱이 단위
    테스트로 확인됨
  - _Requirements: 1.3, 2.1, 2.2, 2.3, 3.5, 7.2_
  - _Boundary: attachmentReference_
  - _Depends: 1.1_

- [ ] 3. 리소스·업로드 훅
- [x] 3.1 useAttachmentResource(서빙 blob→오브젝트 URL·상태·해제) 구현
  - `src/features/attachment/hooks/useAttachmentResource.ts`에서 `fetchAttachmentBlob(id)`로 바이너리를 받아
    `URL.createObjectURL`로 오브젝트 URL 생성, 상태를 `loading→ready`로 전이하고 언마운트·id 변경 시
    `revokeObjectURL`로 해제. 404→`unavailable(not_found)`·403→`unavailable(forbidden)`·5xx/네트워크→`error`로
    매핑(첨부 상태 재판정 없음, 401은 `apiClient` 전역 위임)
  - 관찰 가능한 완료: 200 blob에서 유효 오브젝트 URL·언마운트 시 revoke, 404/403에서 `unavailable`, 5xx에서
    `error` 상태가 통합 테스트로 확인됨
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 4.1, 4.4, 5.1, 5.2, 5.4, 6.2, 6.3, 6.4_
  - _Boundary: useAttachmentResource_
  - _Depends: 1.2_
- [x] 3.2 useAttachmentUpload(낙관 자리표시자·업로드·교체/오류·동시추적) 구현
  - `src/features/attachment/hooks/useAttachmentUpload.ts`에서 업로드 1건마다 `uploadId` 생성→`InsertContext`로
    진행 자리표시자 삽입→`uploadAttachment` 호출→201에서 `buildReferenceMarkdown`으로 참조 치환·실패에서
    `buildErrorMarker`로 안전 오류 표시 치환+`ApiError` 표면화. `Map<uploadId, UploadItem>`으로 동시 업로드 독립
    추적. 종류 확정·크기 한도·저장 판정은 백엔드 위임(자체 에러 형태 발명 금지)
  - 관찰 가능한 완료: 시작 시 자리표시자 삽입→201 참조 치환·`AttachmentRead` 반환, 422/404/403에서 오류 표시
    치환+`ApiError` 노출, 동시 업로드 `uploadId` 독립 추적이 통합 테스트로 확인됨
  - _Requirements: 1.1, 1.3, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 6.4_
  - _Boundary: useAttachmentUpload_
  - _Depends: 1.2, 2.1_
- [x] 3.3 useEditorUploadBridge(s16 EditorWrapper 이벤트/EditorHandle 소비 브리지) 구현
  - `src/features/attachment/hooks/useEditorUploadBridge.ts`에서 `s16` `EditorWrapper` 계약을 **소비**: 반환하는
    `onImagePaste(file)`/`onFileDrop(file)` 핸들러가 수신 `File`(`file.name`)을 `useAttachmentUpload.startUpload`로
    연결(붙여넣기는 `kind:"image"`, 드롭은 백엔드 추론)하고, `onReady(handle)`로 받은 `EditorHandle.insert`/
    `replaceRange` 위에 `InsertContext`(자리표시자 삽입→성공/실패 치환, 삽입 range 추적)를 구현. `documentId`는
    `s19`/`s20` seam에서 소비(미확보 시 방어적 비활성), viewer면 `hasWorkspaceRole`/`RequireRole` 경유로 업로드
    진입점 비활성. `EditorHandle`·이벤트 슬롯 타입은 `s16` `EditorWrapper`에서 import(계약 소유는 s16, 이 훅은
    소비 어댑터)
  - 관찰 가능한 완료: 붙여넣기/드롭 이벤트가 업로드로 연결되고, viewer 컨텍스트·documentId 미확보 시 업로드가
    비활성됨이 통합/UI 테스트로 확인됨
  - _Requirements: 1.1, 1.2, 1.4, 1.6, 6.5, 7.5_
  - _Boundary: useEditorUploadBridge_
  - _Depends: 3.2_

- [ ] 4. 렌더·다운로드·placeholder 컴포넌트
- [x] 4.1 AttachmentPlaceholder(안전 placeholder) 구현 (P)
  - `src/features/attachment/components/AttachmentPlaceholder.tsx`에 `uploading`·`error`·`unavailable` 변형의
    안전 placeholder를 구현(깨진 이미지/링크 아님). 공용 UI 프리미티브(`Spinner`·`ErrorMessage`) 재사용, 내부
    세부정보 과다 노출 없음
  - 관찰 가능한 완료: 세 변형이 각각 진행/오류/사용 불가 상태를 안전하게 표시함이 UI 테스트로 확인됨
  - _Requirements: 2.1, 5.2_
  - _Boundary: AttachmentPlaceholder_
  - _Depends: 1.1_
- [x] 4.2 AttachmentImage(인증 이미지 렌더 + placeholder 폴백) 구현
  - `src/features/attachment/components/AttachmentImage.tsx`에서 `useAttachmentResource(id)`로 오브젝트 URL을
    받아 `<img>` 렌더(원시 `src` 삽입 금지). `loading`이면 `Spinner`, `unavailable`(404/403)이면
    `AttachmentPlaceholder`. admin 포함 보관 첨부는 백엔드 404→placeholder
  - 관찰 가능한 완료: 오브젝트 URL로 이미지가 렌더되고 원시 src를 삽입하지 않으며, 서빙 404/403·admin 보관
    첨부에서 placeholder가 표시됨이 UI 테스트로 확인됨
  - _Requirements: 3.1, 3.3, 5.1, 5.2, 5.5_
  - _Boundary: AttachmentImage_
  - _Depends: 3.1, 4.1_
- [x] 4.3 AttachmentFileLink(파일 다운로드 링크 + placeholder 폴백) 구현 (P)
  - `src/features/attachment/components/AttachmentFileLink.tsx`에서 파일 첨부를 이미지와 구분되는 다운로드
    링크로 표시하고, 활성화 시 `useAttachmentResource`/`fetchAttachmentBlob`로 blob 취득 후 오브젝트 URL +
    `download=original_name`으로 다운로드 트리거. 취득 실패는 오류 표시, 404/403은 `AttachmentPlaceholder`
  - 관찰 가능한 완료: 다운로드가 `original_name`으로 트리거되고, 이미지와 구분된 링크 표시·취득 실패 시
    오류/placeholder가 UI 테스트로 확인됨
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.1_
  - _Boundary: AttachmentFileLink_
  - _Depends: 3.1, 4.1_
- [x] 4.4 AttachmentRenderBridge(참조 resolver + s16 renderers 결선) 구현
  - `src/features/attachment/components/AttachmentRenderBridge.tsx`에서 `s16` `EditorWrapper`의 `renderers` 슬롯에
    넘길 `CustomRenderers`(`customImageRenderer`·`customHTMLRenderer`, edit·read 양 모드 공통)를 구성:
    `customImageRenderer(ref)`가 `resolveAttachmentReference`로 `/attachments/{id}`를 파싱해 인증 blob 기반
    `AttachmentImage`를 마운트한 `HTMLElement` 반환(원시 `src` 금지), 파일 링크는 `customHTMLRenderer`로
    `AttachmentFileLink`에 라우팅(편집·읽기 뷰 렌더 경로 이원화 금지). `CustomRenderers` 타입은 `s16`
    `EditorWrapper`에서 import(계약 소유는 s16). 첨부 상태(보관·소멸)는 서빙 결과(404/403)만 관측
  - 관찰 가능한 완료: 콘텐츠의 첨부 참조가 인증 렌더 컴포넌트로 연결되고 참조 소멸·서빙 불가가 placeholder로
    폴백됨이 UI 테스트로 확인됨
  - _Requirements: 3.5, 5.3, 7.2, 7.5_
  - _Boundary: AttachmentRenderBridge_
  - _Depends: 4.2, 4.3_

- [ ] 5. 소비 진입점·검증
- [ ] 5.1 feature 소비 진입점(index.ts) 및 브리지 소비 계약 통합
  - `src/features/attachment/index.ts`에 업로드/렌더 브리지(`useEditorUploadBridge`·`AttachmentRenderBridge`)와
    렌더 컴포넌트를 배럴 export하여 `s20` 편집 표면·`s19`/`s22` 읽기·공유 뷰가 소비할 진입점을 제공. 다른
    feature를 직접 import 하지 않고, 첨부 저장·아카이브(s12)·공유 경로 서빙(s22)을 소유하지 않음을 경계 주석으로
    명시. 401은 전역 인터셉터 위임
  - 관찰 가능한 완료: 소비 진입점이 브리지·컴포넌트를 노출하고, feature 간 직접 import가 없으며 경계(s12/s20/s22
    비소유)가 주석으로 확인됨
  - _Requirements: 6.6, 7.3, 7.4, 7.5_
  - _Boundary: AttachmentRenderBridge, useEditorUploadBridge_
  - _Depends: 3.3, 4.4_
- [ ]* 5.2 단위·통합·UI 테스트 작성
  - `attachmentReference`(참조 조립·자리표시자 치환·참조 파싱)·`attachmentApi`(단위), `useAttachmentResource`
    (200/404/403/5xx·오브젝트 URL 해제)·`useAttachmentUpload`(자리표시자→교체/오류·동시추적)(통합), 업로드
    게이팅(viewer 미노출/editor·admin 노출)·`AttachmentImage` placeholder 폴백·`AttachmentFileLink` 다운로드·
    admin 보관 첨부 placeholder(UI) 테스트를 추가
  - 관찰 가능한 완료: 위 테스트 스위트가 모두 통과함
  - _Requirements: 1.1, 1.3, 1.6, 2.2, 2.3, 2.4, 3.1, 3.2, 3.4, 4.1, 4.2, 5.1, 5.2, 5.4, 5.5, 6.5, 7.2_
  - _Boundary: Testing_
  - _Depends: 5.1_
- [ ] 5.3 타입체크·빌드 검증
  - `frontend/`에서 `tsc --noEmit`(strict)와 `vite build`를 실행하여 첨부 feature가 오류 없이 타입 통과·번들됨을
    확인(계약 미러링·`any` 금지)
  - 관찰 가능한 완료: 타입체크와 프로덕션 빌드가 오류 없이 완료됨
  - _Requirements: 7.1_
  - _Boundary: Scaffold_
  - _Depends: 5.1_

## Implementation Notes
- 3.3 EditorPos 규약: Toast markdown 위치는 s16 EditorWrapper 소유(replaceRange→replaceSelection 그대로 전달). 브리지는 getMarkdown() 재조회로 토큰을 위치화하며(1-based line·0-based ch 가정), 실제 Toast line/ch base 검증은 jsdom 밖(E2E 하네스 없음)이라 s16 경계로 이연. s16 EditorHandle 형태 변경 시 이 브리지·4.4 렌더러 재검증.
- 4.4 s16 렌더 seam(UPSTREAM=s16 소유): EditorWrapper.toToastHTMLRenderer(EditorWrapper.tsx:134)가 customImageRenderer 반환 HTMLElement를 `.outerHTML`로 동기 직렬화 → createRoot 비동기 커밋된 live AttachmentImage/AttachmentFileLink가 Toast 통과 시 소실. s21은 buildAttachmentRenderers 계약을 격리 단위검증으로 이행(라우팅/resolver 재사용), s16 미수정. 진짜 e2e 인증 렌더는 s16이 반환 노드를 live 마운트(직렬화 대신)하도록 고쳐야 함 = s16 revalidation trigger. 5.3 검증서 상위 라우팅.
