# Requirements Document

## Project Description (Input)
문서 편집창(마크다운 모드)에서 첨부파일과 이미지를 drag&drop / 붙여넣기로 업로드하는 기능을 실제로 동작하게 조립한다.

### 배경 및 근본 원인 (직접 코드 조사로 확정)
- s21 첨부 feature의 업로드 브리지(`useEditorUploadBridge`)와 렌더 브리지(`buildAttachmentRenderers`)는 이미 완전히 구현·단위테스트되어 `frontend/src/features/attachment/index.ts`에서 export되고 있으나, 어떤 페이지·컴포넌트에서도 소비되지 않는다(소비처 0).
- s20 편집 조립부 `frontend/src/features/editor/pages/DocumentEditPage.tsx:112`가 `<EditorPane session={session} />`를 렌더하면서 `onImagePaste`/`onFileDrop`/`renderers`를 전달하지 않는다.
- `frontend/src/shared/editor/EditorWrapper.tsx`는 `onImagePaste`가 undefined면 Toast `addImageBlobHook`을 등록하지 않고(wireImagePaste, 209행), `onFileDrop`이 undefined면 루트 `el`의 DOM `drop` 리스너를 등록하지 않는다(wireFileDrop, 247·263행). 콜백이 안 오므로 두 캡처 경로 모두 비활성.
- 결과적으로 마크다운·위지윅 어느 모드에서도 drag&drop/붙여넣기 업로드가 작동하지 않으며, 사용자는 기본 진입 모드(마크다운)에서만 시도해 "마크다운 모드 한정 문제"로 인지했다.

### 기술적 사실 (Toast UI Editor v3.2.2 소스 검증)
- Toast의 `dropImage` ProseMirror 플러그인은 공용 `EditorBase.defaultPlugins`에 등록되어 마크다운·위지윅 두 표면 모두에서 image drop을 잡아 `addImageBlobHook`을 emit한다(마크다운 에디터도 v3에서 ProseMirror/ToastMark 기반). 비이미지 파일 drop은 stopPropagation을 하지 않아 EditorWrapper의 `el` drop 리스너로 버블링된다. 즉 캡처 경로는 모드 비의존적이다.
- 삽입/치환 seam(`locateToken` 1-based line/0-based ch + `EditorHandle.replaceRange`→Toast `replaceSelection`)은 `MdEditor.replaceSelection`이 `[line,ch]` 좌표를 정상 변환하므로 마크다운 모드에 최적화되어 있다. 반면 `WysiwygEditor.replaceSelection`은 배열 좌표를 받으면 현재 커서 위치에 잘못 삽입하는 결함이 있다(위지윅은 더 약한 경로). 따라서 마크다운 모드 지원에는 삽입 로직 수정이 사실상 불필요하다.

### 구현 범위 (조립 갭 해소가 핵심)
1. `DocumentEditPage.tsx`에서 `useEditorUploadBridge({ documentId, canUpload })`를 호출하고, `canUpload`는 `useEditorScope().role`에서 도출(viewer 제외; 실질적으로 self-lock 보유자는 편집 권한자). 클라이언트 게이팅은 UI 편의일 뿐 서버 403이 최종 경계임을 유지.
2. `EditorPane.tsx`에 현재 없는 `renderers` prop을 추가해 `EditorWrapper`로 통과 노출하고, `buildAttachmentRenderers()`(인증 blob 이미지 렌더 + /attachments/{id} 파일 링크 렌더)를 결선한다. `onImagePaste`/`onFileDrop` prop은 이미 존재하므로 브리지 핸들러를 바인딩.
3. 업로드 낙관 placeholder 삽입 → 성공 시 `/attachments/{id}` 참조 치환, 실패 시 에러 마커 치환이 마크다운 모드에서 종단 동작하도록 검증.

### 제약·경계
- s16 EditorWrapper 단일 소유 계약을 존중(Toast 인스턴스 포크 금지, 렌더 경로 이원화 금지). s20/s21의 기존 동결 소비 계약을 재발명하지 않고 그대로 소비.
- s21이 이미 소유한 업로드/blob 로딩/placeholder 치환 동작은 재구현하지 않고 조립만 한다.
- 기존 s21 단위테스트는 통과하지만 조립 갭을 못 잡았으므로, DocumentEditPage/EditorPane 조립 레벨 통합 테스트를 추가해 회귀를 방지한다.
- 백엔드(s12 첨부 저장·격리·서빙)는 무수정.

## Introduction
이 스펙은 새 기능을 만드는 것이 아니라, 이미 구현·단위테스트 완료되었으나 **소비처가 0인** s21 첨부 브리지(`useEditorUploadBridge`·`buildAttachmentRenderers`)를 s20 편집 표면(`DocumentEditPage`→`EditorPane`→s16 `EditorWrapper`)에 실제로 결선하는 **조립 갭(assembly gap) 해소** 스펙이다. 결선이 빠져 있어 편집 권한자가 마크다운 편집 모드에서 이미지·파일을 붙여넣거나 드롭해도 업로드가 전혀 일어나지 않는다.

사용자 관점의 목표는 단순하다: 편집 권한자가 마크다운 편집 모드에서 이미지를 붙여넣거나 파일을 드래그앤드롭하면 실제로 업로드되고, 업로드 진행·성공·실패가 편집 콘텐츠에 반영되며, `/attachments/{id}` 참조가 편집 표면에서 실제 이미지·파일 링크로 보인다. 모든 업로드/blob 로딩/치환 로직과 백엔드 저장·서빙은 이미 존재하므로 이 스펙은 **결선과 그 결선을 지키는 회귀 방지 테스트만** 소유한다.

## Boundary Context
- **In scope**:
  - 마크다운 편집 모드에서 drag&drop / 붙여넣기 업로드 진입점 활성화(브리지 핸들러를 편집 표면 슬롯에 바인딩).
  - 편집 표면의 첨부 렌더 결선(인증 blob 이미지 + `/attachments/{id}` 파일 링크)을 읽기 뷰와 동일 경로로 노출.
  - 업로드 낙관 자리표시자 삽입 → 성공 시 참조 치환 → 실패 시 오류 마커 치환의 마크다운 모드 종단 동작.
  - `canUpload` 를 현재 워크스페이스 role 에서 도출(viewer/비편집 권한 제외).
  - 단일 `EditorHandle` 을 자동저장 경로와 업로드 삽입 경로 양쪽에 공유(결선 충돌 방지).
  - 조립 레벨 통합 테스트 추가(단위테스트가 못 잡은 결선 갭 회귀 방지).
- **Out of scope**:
  - s21 이 소유한 업로드 요청·blob 로딩·자리표시자 치환 동작의 재구현.
  - 백엔드 s12 첨부 저장·격리·서빙 로직 수정.
  - 위지윅(WYSIWYG) 모드의 삽입 좌표(`replaceSelection`) 결함 수정 및 위지윅 종단 지원.
  - 새 편집 표면 API·별도 Toast 에디터 인스턴스 발명.
- **Adjacent expectations**:
  - s16 `EditorWrapper` 는 `onImagePaste`·`onFileDrop`·`renderers`·`onReady` 슬롯과 붙여넣기/드롭 캡처·렌더 위임을 단일 소유한다. 이 스펙은 그 슬롯을 소비만 한다.
  - s20 `useEditSession.bindHandle` 은 이탈 시 1회 자동저장(`getMarkdown`)을 위해 `EditorHandle` 을 요구한다.
  - s21 `useEditorUploadBridge`(반환: `onReady`·`onImagePaste`·`onFileDrop`)와 `buildAttachmentRenderers()` 는 동결 소비 계약이며 재정의하지 않는다.
  - 현재 워크스페이스 role(s18 멤버십/s24 복원 경로가 주입) 이 `canUpload` 도출의 원천이다.
  - 서버측 권한 강제(백엔드 403)가 최종 경계이며, 클라이언트 게이팅은 이를 대체하지 않는다.

## Requirements

### Requirement 1: 마크다운 편집 모드 업로드 진입점 결선
**Objective:** 편집 권한자로서, 마크다운 편집 모드에서 이미지·파일을 붙여넣기/드래그앤드롭으로 업로드하고 싶다, 그래야 별도 업로드 대화상자 없이 편집 중 바로 첨부를 삽입할 수 있다.

#### Acceptance Criteria
1. When 편집 권한자가 마크다운 편집 모드에서 이미지를 클립보드로 붙여넣으면, the 편집 화면 shall 해당 이미지를 이미지 종류 첨부로 업로드하기 시작한다.
2. When 편집 권한자가 편집 표면에 파일을 드래그앤드롭하면, the 편집 화면 shall 해당 파일을 업로드하기 시작하되 종류를 지정하지 않고 백엔드 추론에 위임한다.
3. When 편집 권한자가 편집 표면에 이미지 파일을 드래그앤드롭하면, the 편집 화면 shall 이미지 붙여넣기 업로드 경로로 처리한다.
4. The 편집 화면 shall 붙여넣기·드롭 업로드 진입점을 기본 진입 모드인 마크다운 편집 모드에서 활성 상태로 제공한다.
5. Where 편집 권한자가 편집 표면에 초점을 두지 않은 상태에서 파일을 드롭하더라도, the 편집 화면 shall 편집 표면 루트 영역에 대한 드롭을 업로드 진입점으로 인식한다.

### Requirement 2: 첨부 렌더 결선 (인증 이미지·파일 링크)
**Objective:** 편집 권한자로서, 편집 콘텐츠 안의 첨부 참조가 실제 이미지·다운로드 가능한 파일 링크로 보이길 원한다, 그래야 편집 중에 첨부 삽입 결과를 눈으로 확인할 수 있다.

#### Acceptance Criteria
1. When 편집 콘텐츠에 `/attachments/{id}` 이미지 참조가 존재하면, the 편집 표면 shall 인증된 blob 으로 이미지를 렌더한다.
2. When 편집 콘텐츠에 `/attachments/{id}` 파일(비이미지) 링크 참조가 존재하면, the 편집 표면 shall 다운로드 가능한 파일 링크로 렌더한다.
3. The 편집 표면 shall 문서 읽기 뷰와 동일한 첨부 렌더 경로를 사용하며 별도 렌더 경로를 만들지 않는다.
4. If 첨부 서빙이 실패(404/403)하면, then the 편집 표면 shall s21 렌더 컴포넌트가 정의한 대체 표시를 그대로 노출한다(첨부 상태를 재판정하지 않는다).

### Requirement 3: 업로드 낙관 자리표시자 종단 치환
**Objective:** 편집 권한자로서, 업로드의 진행·성공·실패가 편집 콘텐츠에 즉시 반영되길 원한다, 그래야 업로드 결과를 기다리며 편집 흐름이 끊기지 않는다.

#### Acceptance Criteria
1. When 업로드가 시작되면, the 편집 화면 shall 삽입 위치에 낙관 자리표시자 토큰을 삽입한다.
2. When 업로드가 성공하면, the 편집 화면 shall 해당 자리표시자 토큰을 `/attachments/{id}` 참조로 치환한다.
3. If 업로드가 실패하면, then the 편집 화면 shall 해당 자리표시자 토큰을 오류 마커로 치환한다.
4. While 편집 세션이 마크다운 모드이면, the 편집 화면 shall 콘텐츠 문자열에서 자리표시자 토큰의 실제 위치를 찾아 정확한 좌표로 치환한다.
5. If 자리표시자 토큰이 콘텐츠에서 발견되지 않으면, then the 편집 화면 shall 치환을 no-op 으로 안전 종료한다(에디터 상태를 손상시키지 않는다).

### Requirement 4: 업로드 권한 게이팅 (canUpload 도출)
**Objective:** 편집 권한자로서, 편집 권한이 있을 때만 업로드 진입점이 열리길 원하고, 시스템 운영자로서 클라이언트 게이팅이 서버 권한 강제를 대체하지 않길 원한다, 그래야 권한 경계가 서버에서 최종 결정된다.

#### Acceptance Criteria
1. While 현재 워크스페이스에서 사용자의 role 이 편집 권한(비-viewer)을 부여하면, the 편집 화면 shall `canUpload` 를 참으로 도출해 붙여넣기·드롭 업로드 진입점을 활성화한다.
2. While 사용자의 role 이 viewer 이거나 미확정(null)이면, the 편집 화면 shall 붙여넣기·드롭 업로드 진입점을 no-op 으로 비활성화한다.
3. If 업로드 대상 문서 식별자가 미확보 상태이면, then the 편집 화면 shall 업로드 진입점을 no-op 으로 처리한다.
4. The 편집 화면 shall 클라이언트 `canUpload` 게이팅을 UI 노출 편의로만 취급하고, 서버측 권한 강제(백엔드 403)를 첨부 업로드의 최종 권한 경계로 유지한다.
5. The 편집 화면 shall role 비교 판정을 s16 공통 권한 게이팅 유틸에 위임하고 자체 역할 비교 로직을 흩뿌리지 않는다.

### Requirement 5: 단일 EditorHandle 공유 (자동저장·업로드 삽입 공존)
**Objective:** 편집 권한자로서, 업로드로 삽입한 참조가 이탈 시 자동저장에 그대로 반영되길 원한다, 그래야 업로드 결선이 저장 결선을 덮어써 첨부가 유실되는 일이 없다.

#### Acceptance Criteria
1. When 편집 인스턴스가 준비되면, the 편집 화면 shall 동일한 `EditorHandle` 을 자동저장 경로(세션 저장)와 업로드 삽입 경로(브리지) 양쪽에 결선한다.
2. When 업로드가 자리표시자·참조를 삽입한 뒤 사용자가 편집을 이탈하면, the 편집 화면 shall 삽입 결과가 반영된 콘텐츠로 1회 자동저장한다.
3. The 편집 화면 shall 편집당 단일 Toast 에디터 인스턴스만 마운트하며 인스턴스를 포크하지 않는다.

### Requirement 6: 결선 경계 존중 및 조립 회귀 방지
**Objective:** 유지보수자로서, 이 스펙이 기존 소유 계약을 재구현하지 않고 조립만 하며 조립 갭 회귀를 테스트로 막길 원한다, 그래야 단위테스트가 못 잡은 결선 결함이 재발하지 않는다.

#### Acceptance Criteria
1. The 편집 화면 shall s21 이 소유한 업로드 요청·blob 로딩·자리표시자 치환 동작을 재구현하지 않고 결선만 한다.
2. The 시스템 shall 백엔드 첨부 저장·격리·서빙(s12) 코드를 수정하지 않는다.
3. The 편집 화면 shall s16 `EditorWrapper` 단일 소유 계약을 존중하며 Toast 인스턴스·래퍼 내부·렌더 경로를 소유하거나 이원화하지 않는다.
4. Where 조립 레벨 통합 테스트가 추가되면, the 테스트 shall `DocumentEditPage`/`EditorPane` 결선을 통해 붙여넣기·드롭 → 업로드 → 자리표시자 치환 및 첨부 렌더 경로를 검증한다.
5. The 이 스펙 shall 위지윅 모드의 삽입 좌표 결함 수정과 위지윅 종단 지원을 범위에서 제외하고 마크다운 편집 모드 종단 동작만 보장한다.
