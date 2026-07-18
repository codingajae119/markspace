# Research Log — s21-fe-attachment

## Discovery Scope

- **Feature type**: Extension(공통 레이어 소비형 feature). greenfield 아님 — `s16-fe-foundation` 공통
  레이어(API 클라이언트·Toast UI Editor 래퍼)·`s19-fe-document` 문서 컨텍스트, 백엔드 `s12-attachment`
  실동작 엔드포인트 위에 얹는 첨부 UX 계층.
- **Discovery type**: Integration-focused(light). 신규 외부 기술 도입 없음. 계약·seam 정합, 낙관적 업로드
  UX, 인증 렌더 경로 결정이 핵심.

## Ground-Truth 계약 확인 (검증 기준 = s01 단일 소스)

실제 백엔드 라우터/스키마를 읽어 API 형태를 발명하지 않고 미러링했다.

- 첨부 라우터(`backend/app/attachment/router.py`):
  - 업로드 = **`POST /documents/{id}/attachments`** — multipart(`file` UploadFile + 선택 `kind` Form) →
    201 `AttachmentRead`. editor 이상 게이팅(s07 문서→WS 어댑터), 문서 부재→404, viewer/비멤버→403, admin
    bypass. `kind` 미지정 시 백엔드가 업로드 content-type 으로 image/file 추론(붙여넣기=image 경로 포함).
    크기 초과→422. (brief·상위 태스크의 `POST /attachments` 축약 표기 대신 **실제 WS-scoped 문서 경로**를
    채택 — "API 형태 발명 금지" 지시에 따라 라우터 ground-truth 우선.)
  - 조회 서빙 = **`GET /attachments/{id}`** — 바이너리 `StreamingResponse`. viewer 이상 게이팅(s12 첨부→WS
    어댑터), 첨부 부재→404, viewer 미만·비멤버→403, admin bypass. **보관(`is_archived`) 첨부는 role 무관
    404**(admin 포함, 8.10)를 서비스가 권한 판정 이전에 처리.
- 첨부 스키마(`backend/app/attachment/schemas.py`): `AttachmentKind`(str Enum: image|file),
  `AttachmentRead`(id·workspace_id·document_id·kind·original_name·is_archived·created_at·**url**).
  `url`은 ORM 컬럼이 아닌 서버 산정 파생값 `"/attachments/{id}"`이며 **문서 본문에서의 안정 참조 규약**이다.
- s01 API 카탈로그(design.md): 행 32 `POST /documents/{id}/attachments`(editor), 행 33
  `GET /attachments/{id}`(viewer), **행 37 `GET /public/{token}/attachments/{aid}`(공개)** = s14/s22 소유
  (이 spec 범위 밖).

## 소비 상위 계약 확인 (s16 · s19)

- `s16` `apiClient`: `post<T>(path, body)` 는 `body`가 FormData 이면 multipart 로 전송(RequestOptions.body =
  `FormData`), `responseType:"blob"` 로 바이너리 응답을 `Blob` 으로 수신. 401 전역 인터셉터·`ApiError`
  정규화 내장 → 첨부 호출은 이 단일 경로만 사용.
- `s16` `EditorWrapper`: 현재 계약은 `mode(edit|read)`·`initialContent`·`onReady(handle)`,
  `EditorHandle{ getMarkdown() }`. **붙여넣기/드롭 이벤트와 이미지 렌더 커스터마이즈 계약은 아직 노출되지
  않음** → 이 spec이 소비 계약(업로드/렌더 브리지 형태)을 정의하고 cross-spec 리뷰에서 s16(래퍼)·s20(에디터
  표면)과 정합(아래 결정 2·3).
- `s19`: 문서 뷰어(`DocumentViewer`)·선택 컨텍스트가 현재 문서 id 를 보유. 업로드 대상 `documentId` 는 이
  컨텍스트/`s20` 편집 표면에서 소비.

## 주요 설계 결정

### 1. 첨부 접근은 s16 apiClient 단일 경로 — 원시 `src` 삽입 금지
- 첨부는 WS 격리·인증(viewer+)·보관 차단(404) 대상이며, `<img src="/attachments/{id}">` 원시 삽입은 base URL
  누락·인증 쿠키 전송/CORS·404 감지 불가 문제가 있다.
- **결정**: 이미지·파일 모두 `apiClient.get(path, {responseType:"blob"})` 로 바이너리를 받아 **오브젝트 URL**
  로 렌더/다운로드한다. 이로써 (a) 인증·WS 격리를 백엔드가 강제, (b) 404/403 을 감지해 placeholder 폴백,
  (c) 401 전역 인터셉터·`ApiError` 정규화 재사용이 모두 단일 경로로 성립. 오브젝트 URL 은 언마운트 시 해제.

### 2. 업로드 진입점 = s16 `EditorWrapper` 이벤트 계약 소비 (s16 소유 계약)
- Toast UI Editor 는 이미지 붙여넣기/드롭에 대해 `addImageBlobHook(blob, callback)` 훅을, 그 외 파일 드롭은
  에디터 DOM drop 이벤트를 제공한다. 이 진입점은 **래퍼(s16)** 가 단일 소유하며 `EditorWrapper` 가
  `onImagePaste(file)`·`onFileDrop(file)` 이벤트 슬롯과 `onReady(handle)` 의 `EditorHandle.insert`/`replaceRange`
  로 **노출**한다(s16 design 확정).
- **결정**: 이 spec 의 `useEditorUploadBridge` 는 그 s16 계약을 **소비**한다 — `onImagePaste`/`onFileDrop` 핸들러가
  `File` 을 업로드 훅으로 넘기고, `EditorHandle.insert`/`replaceRange` 위에 자리표시자 삽입/치환(`InsertContext`)을
  구현한다. 자체 에디터 인스턴스나 별도 렌더 경로를 만들지 않는다(steering 렌더 이원화 금지). 계약은 s16 소유이며
  이 spec 은 소비 어댑터만 두므로, s16 `EditorWrapper` 인터페이스 변경이 s21 재검증 트리거다(더 이상 미확정 seam 아님).

### 3. 렌더 통합 = 래퍼의 이미지 렌더 커스터마이즈 계약 경유
- 콘텐츠의 `![alt](/attachments/{id})` 는 Toast UI 가 기본적으로 `<img src>` 로 렌더 → 인증 우회·깨짐 발생.
- **결정**: 이 spec 이 첨부 참조 resolver(`/attachments/{id}` → 인증 렌더 컴포넌트) 와 렌더 컴포넌트
  (`AttachmentImage`·`AttachmentFileLink`·`AttachmentPlaceholder`) 를 소유하고, s16 `EditorWrapper` 의 `renderers`
  슬롯(`customImageRenderer`·`customHTMLRenderer`, edit·read 양 모드 공통)에 넘길 `CustomRenderers` 를 구성해
  결선한다. 계약(`renderers`)은 s16 소유이며 이 spec 은 소비한다. 편집·읽기(s19/s22) 뷰 모두 동일 래퍼를 소비하므로
  렌더 경로가 이원화되지 않는다.

### 4. 낙관적 자리표시자 + 고유 id 로 동시 업로드 추적
- **결정**: 업로드 시작 시 고유 `uploadId` 로 자리표시자 토큰을 삽입하고, 성공 시 실제 참조(이미지/링크)로,
  실패 시 안전한 오류 표시로 교체한다. 동시 업로드는 `uploadId` 로 독립 추적해 자리표시자 혼동을 방지. 교체는
  순수 함수(참조 markdown 조립)와 래퍼 브리지의 토큰 치환으로 분리해 테스트 용이성 확보.

### 5. 참조 소멸·서빙 불가는 관측만 — 404/403 → placeholder
- 8.6(완전삭제 반응 보관)·8.7(저장 참조 소멸 아카이브)·8.10(보관 비노출, admin 포함 404)은 백엔드 단독 소유.
- **결정**: 프론트는 첨부 상태를 재판정하지 않고 **서빙 응답(404/403)** 이라는 관측 가능한 결과만 근거로
  placeholder 로 폴백한다. `unavailable`(404/403 → placeholder 안정 표현) 과 `error`(일시 오류) 를 구분.

### 6. 종류(kind) → 참조 형태
- **결정**: 업로드 응답 `kind` 로 콘텐츠 삽입 참조 형태만 결정한다 — image → 이미지 참조(`![name](url)`),
  file → 다운로드 링크(`[name](url)`). 종류 확정 자체는 백엔드(content-type 추론) 소유이므로 프론트는 응답
  값을 신뢰만 한다.

## 리스크 및 완화
- **s16 래퍼 이벤트/렌더 계약(해소됨)**: s16 `EditorWrapper` 가 `onImagePaste`/`onFileDrop`·`EditorHandle.insert`/
  `replaceRange`·`renderers.customImageRenderer`/`customHTMLRenderer` 를 노출하여 미확정 리스크가 해소됐다. 이 spec
  은 그 계약을 브리지 모듈(`useEditorUploadBridge`·`AttachmentRenderBridge`) 1곳에 소비 어댑터로 캡슐화해 변경 파급을
  국소화하고, s16 `EditorWrapper` 인터페이스 변경을 revalidation trigger 로 표기한다.
- **오브젝트 URL 누수**: 렌더/다운로드용 오브젝트 URL 을 훅(`useAttachmentResource`) 단일 지점에서 생성·해제
  (언마운트·참조 변경 시 revoke) 하여 누수 방지.
- **동시 업로드 자리표시자 정합**: `uploadId` 로 독립 추적하고 교체/오류 로직을 업로드 훅 단일 지점에 두어
  자리표시자 혼동을 방지.
- **업로드 경로 문서 id 부재**: `documentId` 미확보 시 업로드 진입점을 비활성화(방어)하고, s19/s20 컨텍스트에서
  주입되는 단일 seam 으로 소비.
