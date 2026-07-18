# Research Log — s20-fe-editor

## Discovery Scope

- **Feature type**: Extension(공통 레이어 소비형 feature). greenfield 아님 — `s16-fe-foundation` 공통 레이어와
  `s19-fe-document` 읽기 뷰, 백엔드 `s09-lock-version` 실동작 엔드포인트 위에 얹는 편집 도메인 화면.
- **Discovery type**: Integration-focused(light). 신규 외부 기술 도입 없음. 계약·seam 정합과 편집 세션
  생명주기 설계 중심.

## Ground-Truth 계약 확인 (검증 기준 = s01 단일 소스)

실제 백엔드 라우터/스키마를 읽어 API 형태를 발명하지 않고 미러링했다.

- 잠금/버전 라우터(`backend/app/lock_version/router.py`): `POST /documents/{id}/lock`(200 DocumentLockRead,
  EDITOR+), `POST /documents/{id}/save`(200 DocumentVersionRead, EDITOR+), `POST /documents/{id}/cancel`(204,
  EDITOR+), `POST /documents/{id}/force-unlock`(204, **OWNER+**), `GET /documents/{id}/versions`
  (200 Page[DocumentVersionRead], VIEWER+). 게이팅은 s07 어댑터 `ws_role_for_document`로 문서→WS 매핑,
  판정은 s01 resolver. 타인 잠금→409, 비보유 저장/취소→409, 문서 부재→404, 미인증→401은 서버 소유.
- 잠금/버전 스키마(`backend/app/lock_version/schemas.py`): `DocumentSaveRequest{content:str}`(빈 문자열 허용),
  `DocumentLockRead{document_id, lock_user_id, lock_acquired_at}`, `DocumentVersionRead{id, document_id,
  created_by, created_at}` — **content 필드 없음**(rollback·본문 조회 미제공). 목록은 `Page[DocumentVersionRead]`.
- 문서 상세(`backend/app/document/schemas.py::DocumentRead`): 편집 초기 콘텐츠(`content`, markdown)·
  `current_version_id`를 여기서 취득(GET /documents/{id}). 편집에 필요한 부분집합만 소비.
- 공통 엔벨로프(`backend/app/schemas/base.py`): `Page{items, total}`.

## 주요 설계 결정

### 1. 자동저장 = 이탈 시 1회, 언마운트 cleanup 바인딩 (버전 폭증 회피)
- 백엔드 저장 계약상 `POST /save` = 버전 스냅샷 생성. 주기/‑debounce 저장은 버전 폭증을 유발한다(`tech.md`
  명시 결정).
- **결정**: 편집 세션(`useEditSession`)의 언마운트/라우트 전환 cleanup에서 `saveDocument`를 **정확히 1회**
  호출한다. 중복 방지 플래그(`saved`/`released`)로 세션당 최대 1회 보장. 명시적 취소(`/cancel`) 후·진입 시
  잠금 미획득 시에는 저장을 억제한다(보유하지 않은 잠금 저장 금지). 대안(주기 타이머·keystroke debounce)은
  steering 결정으로 기각.

### 2. 편집 생명주기 = 전용 편집 라우트(마운트=획득, 언마운트=저장/해제)
- brief: 생명주기를 "라우트 전환·언마운트"에 바인딩.
- **결정**: 편집을 전용 라우트(`/documents/:id/edit`, s16 보호 프레임 자식)로 두어 진입=마운트→잠금 획득,
  이탈=언마운트→이탈 저장 1회+해제로 자연스럽게 결선. 읽기 뷰(s19)에서 편집 진입점→편집 라우트로 navigate.
  대안(같은 화면 내 상태 토글)은 언마운트 시점이 모호해 생명주기 결선이 취약 → 기각.

### 3. 잠금 상태는 /lock 응답에서만 파생 — 별도 조회 엔드포인트 없음
- 계약에 잠금 현재 상태를 조회하는 엔드포인트가 없다. `DocumentRead`에도 lock 필드가 노출되지 않는다.
- **결정**: 잠금 상태(`self`/`other`)를 `POST /lock` 응답(200 `DocumentLockRead` | 409 `ApiError`)에서만
  파생(`resolveLockState` 순수 함수). 폴링·추측 조회를 하지 않으며, 409에서 계약에 없는 보유자 식별 정보를
  발명하지 않고 `ApiError` 메시지만 표면화.

### 4. 강제 해제 노출 = hasWorkspaceRole(OWNER) 단일 경로, 자기 잠금은 cancel
- 백엔드 `/force-unlock`은 **OWNER** 강제. brief의 노출 대상은 "잠금 보유 editor 본인·WS owner·admin".
- **결정**: `/force-unlock`(타인 잠금 강제 해제)은 `s16` `hasWorkspaceRole({minimum: OWNER})`(admin bypass
  포함)로만 노출 판정(컴포넌트 역할 비교 금지). "잠금 보유 editor 본인"의 자기 잠금 해제는 owner 권한이
  불필요하므로 `/cancel`(EDITOR 접근) 경로로 처리한다 — 이렇게 분리하면 비-owner 보유자가 `/force-unlock`을
  호출해 확정적 403을 맞는 UX 결함을 피하면서 brief의 노출 의도를 모두 충족한다. 클라이언트 게이팅은 노출
  편의이며 서버측 OWNER 강제(403)가 최종 경계.

### 5. 버전 뷰어 = 메타데이터 읽기 전용, 본문/rollback 미제공 (계약 제약)
- `DocumentVersionRead`에 content 필드가 없고 과거 버전 **본문**을 조회하는 엔드포인트도 없다. `tech.md`는
  rollback 미제공.
- **결정**: 버전 뷰어는 `GET /versions`의 메타데이터(id·created_by·created_at)만 읽기 전용으로 표시하고,
  `current_version_id`(문서 상세)로 현재 버전을 구분한다. 과거 본문 표시·rollback/복원 액션을 노출하지
  않는다(계약에 없는 기능을 발명하지 않음). brief의 "과거 버전 스냅샷 열람"은 계약 범위 내 메타데이터 열람으로
  해석·구현.

### 6. 편집 렌더 = s16 EditorWrapper(mode:"edit") 단일 래퍼 — 이원화 금지
- **결정**: 편집은 `content`(markdown)를 `EditorWrapper(mode:"edit")`(WYSIWYG+md)로 렌더하고 `EditorHandle.
  getMarkdown()`으로 저장 본문을 취득. `content_html` 미사용. s19 읽기·s22 공유와 렌더 경로를 공유(단일 래퍼).

### 7. 인접 seam 소비 (s18·s19·s21)
- 현재 WS(id·role)는 `s18` seam(‑ s16 세션/컨텍스트 경유), 현재 사용자 id·isAdmin은 s16 `useSession()`.
  편집 진입은 `s19` 진입점 seam, 편집 표면은 `s21` 붙여넣기/드롭 seam.
- **결정**: `useCurrentWorkspace` 어댑터로 WS 컨텍스트 소비 계약만 정의(제공자 s18). 편집 라우트 경로 규약을
  노출해 s19 진입점이 도달(경로 규약 cross-spec 정합). EditorPane 편집 표면을 s21이 얹는 seam으로 노출(업로드
  동작 미구현). 동일 wave 병렬 생성이라 s21 spec 파일은 미참조.

## 리스크 및 완화
- **이탈 저장 신뢰성(하드 언로드)**: SPA 라우트 전환·언마운트는 cleanup으로 확실히 저장하나, 탭 닫기·새로고침
  같은 하드 언로드는 fetch 완료가 보장되지 않는다 → 1차 범위는 SPA 이탈 저장으로 한정하고 하드 언로드는
  best-effort로 표기(계약상 저장은 명시 저장 흐름이 우선).
- **중복 저장 리스크**: 취소 후 언마운트, 저장 후 재언마운트 등에서 중복 `/save` 위험 → `useEditSession` 단일
  지점의 `saved`/`released` 플래그로 세션당 최대 1회 보장.
- **s18/s19/s21 seam 미확정**: 소비 계약을 어댑터·경로 규약·표면 seam 각 1곳에 캡슐화해 파급을 국소화하고
  cross-spec 리뷰에서 정합, revalidation trigger로 표기.
- **force-unlock 권한 오해**: OWNER 강제와 brief의 "보유 editor 본인" 노출을 cancel/force-unlock 경로 분리로
  해소(결정 4)해 확정적 403 UX 결함을 방지.
