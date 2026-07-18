# Requirements Document

## Introduction

`s19-fe-document`는 현재 워크스페이스(WS) 안에서 문서를 계층 트리로 탐색하고, breadcrumb으로 위치를
파악하며, 문서를 생성·이름변경·삭제하고, 드래그앤드롭으로 이동/재정렬하며, 읽기 전용으로 열람하는 화면과
휴지통(목록·복구·완전삭제) 화면을 소유한다. 이 spec은 백엔드 `s07-document-core`·`s10-trash`가 이미
구현한 WS-scoped 문서/휴지통 엔드포인트를 소비하는 **프론트엔드 feature**이며, `s16-fe-foundation` 공통
레이어(공용 API 클라이언트·전역 401 인터셉터·권한 게이팅 유틸·라우터 셸·Toast UI Editor 래퍼)를 재사용한다.

편집(잠금·자동저장·버전 뷰어)은 `s20-fe-editor`가, 첨부(업로드·렌더)는 `s21-fe-attachment`가, 공유
링크는 `s22-fe-sharing`이 이 문서 화면 위에 얹으므로 이 spec의 범위 밖이다. 문서 상태(status)·묶음(bundle)
전이 판정(순환·동일 WS·묶음 원자성·복구 위치)은 **백엔드 엔진이 단독 소유**하며, 이 spec은 그 결과와
오류를 낙관적으로 표면화만 한다(재판정하지 않는다).

검증 기준은 백엔드와 동일하게 `s01-contract-foundation`의 계약 단일 소스다. 특히 소비 엔드포인트와 응답
스키마는 실제 백엔드 라우터(`backend/app/document/router.py`·`backend/app/trash/router.py`)와 계약 스키마
(`DocumentCreate`/`DocumentUpdate`/`DocumentMoveRequest`/`DocumentRead`, `TrashBundleRead`/`TrashMemberRead`,
`Page[T]`, 공통 `ErrorResponse`)를 그대로 미러링하며 새 API 형태를 발명하지 않는다. 권한 위계
(owner ≥ editor ≥ viewer + admin bypass, INV-1·2·3)와 WS 격리(INV-6)·묶음 규칙(INV-10·11·12)은
백엔드가 강제하는 계약을 그대로 소비한다.

산출물 언어는 한국어이며, 상위 근거로 `s01-contract-foundation`·`s16-fe-foundation`의 requirements.md·
design.md와 steering(`tech.md`·`structure.md`·`roadmap.md`)을 참조한다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - 현재 WS의 active 문서 계층을 트리로 표시하고, 노드 펼침/접힘·선택을 지원하는 문서 트리 네비게이션.
  - 선택된 문서의 조상 경로를 표시하고 조상으로 이동하게 하는 breadcrumb.
  - 문서 생성(부모 지정 포함)·이름변경(제목 PATCH)·삭제(DELETE → 휴지통, 묶음 캐스케이드 관찰).
  - 드래그앤드롭 기반 문서 이동/재정렬(`POST /documents/{id}/move`), 순환·동일 WS·비active·잘못된 형제
    참조 등 제약 위반을 백엔드 오류로 표면화(낙관적 반영 후 복원).
  - 읽기 전용 문서 뷰어: `s16` Toast UI Editor 래퍼를 `mode:"read"`(viewer mode)로 재사용하여 렌더
    (편집 경로와 이원화 금지). 편집 진입 진입점(버튼)은 노출하되 실제 편집 동작은 `s20`에 위임.
  - 휴지통 화면: 묶음(bundle)별 목록·구성원 요약·만료 예정 표시, 복구, 완전삭제(비가역 확인), editor 이상
    WS 전체 접근(권한 게이팅은 `s16` 유틸 경유).
- **Out of scope (다른 spec/백엔드가 소유)**:
  - 편집 진입/이탈 생명주기·lock UX·강제 해제·이탈 시 1회 자동저장·버전 뷰어(`s20-fe-editor`).
  - 첨부 업로드·렌더/다운로드·참조 소멸 placeholder(`s21-fe-attachment`).
  - 공유 링크 관리·게스트 읽기 뷰(`s22-fe-sharing`).
  - 공통 레이어(라우터 셸·전역 401·API 클라이언트·권한 게이팅 유틸·Toast 래퍼)의 **구현**(`s16`).
  - 현재 WS 앰비언트 컨텍스트(`useCurrentWorkspace`)의 **구현**(`s16-fe-foundation` 단일 소유), 현재 WS 선택 관리
    화면·멤버십/권한 데이터 조달(`s18-fe-workspace`). 이 spec은 `s16` 컨텍스트를 소비만 한다.
  - 문서 status·묶음 전이 **판정**(순환·동일 WS·묶음 원자성·복구 위치·보관 타이머): 백엔드 엔진 소유.
- **Adjacent expectations (인접 seam)**:
  - 현재 WS 식별자(`workspaceId`)와 현재 사용자의 WS role(`role`)은 `s16-fe-foundation` 앰비언트 컨텍스트
    `useCurrentWorkspace()`의 **최상위 접근자**에서 **소비만** 한다(중첩 필드 접근 금지, 형제 s18 의존 없음). 이
    spec은 WS 컨텍스트를 스스로 구현하지 않으며 `useCurrentWorkspace`라는 이름을 재정의하지 않는다. `role` 값의
    조달 경로(s18 멤버십)는 `s16`이 내부적으로 흡수한다.
  - 권한에 따른 UI 노출(생성·수정·삭제·이동·휴지통 노출 여부)은 항상 `s16` 권한 게이팅 유틸
    (`hasWorkspaceRole`/`<RequireRole>`)을 거쳐 결정하며, 컴포넌트마다 역할 비교를 흩뿌리지 않는다.
  - 문서 뷰어·향후 편집/공유 뷰는 `s16` 단일 Toast UI Editor 래퍼를 소비하며 자체 에디터 인스턴스를
    구성하지 않는다.
  - 모든 백엔드 호출은 `s16` 공용 API 클라이언트를 통해서만 수행하며 401 처리·에러 정규화를 재구현하지
    않는다. feature는 다른 feature를 직접 import 하지 않는다.

## Requirements

### Requirement 1: 문서 트리 네비게이션

**Objective:** As a 워크스페이스 멤버, I want 현재 WS의 문서 계층을 트리로 보고 펼침/접힘·선택하기를,
so that 문서 구조를 파악하고 원하는 문서로 이동할 수 있다.

#### Acceptance Criteria

1. When 사용자가 문서 화면에 진입하면, the 문서 트리 뷰 shall 현재 WS의 active 문서 목록
   (`GET /workspaces/{workspace_id}/documents`)을 조회하여 `parent_id`와 `sort_order` 기준으로 계층 트리를
   구성해 표시한다.
2. When 조회 결과가 페이지네이션(`Page[DocumentRead]`)으로 나뉘어 있으면, the 문서 트리 뷰 shall `total`에
   도달할 때까지 후속 페이지(`offset`)를 이어 받아 전체 active 문서로 트리를 완성한다.
3. When 사용자가 하위 노드를 가진 트리 노드의 펼침/접힘 토글을 조작하면, the 문서 트리 뷰 shall 해당
   노드의 하위 표시 상태를 전환한다.
4. When 사용자가 트리 노드를 선택하면, the 문서 트리 뷰 shall 해당 문서를 현재 선택 문서로 확정하고 그
   상세 뷰로 이동시킨다.
5. While 문서 목록 조회가 진행 중인 동안, the 문서 트리 뷰 shall 로딩 상태를 표시하고, 조회가 실패하면
   공통 `ErrorResponse` 기반 오류 표시로 사용자에게 알린다.
6. Where 현재 WS에 active 문서가 하나도 없으면, the 문서 트리 뷰 shall 빈 상태(안내)를 표시한다.
7. The 문서 트리 뷰 shall 노드의 표시 순서를 백엔드가 반환한 `sort_order`에 따르며, 정렬 값을 프론트에서
   재계산하지 않는다.

### Requirement 2: Breadcrumb 경로 표시·이동

**Objective:** As a 워크스페이스 멤버, I want 현재 문서의 조상 경로를 breadcrumb으로 보고 조상으로
이동하기를, so that 깊은 계층에서도 현재 위치를 파악하고 상위로 빠르게 되돌아갈 수 있다.

#### Acceptance Criteria

1. When 어떤 문서가 선택되면, the breadcrumb shall 로드된 트리에서 `parent_id` 체인을 루트까지 거슬러
   올라가 조상 경로(루트 → … → 현재 문서)를 순서대로 표시한다.
2. When 사용자가 breadcrumb의 조상 항목을 선택하면, the breadcrumb shall 해당 조상 문서를 현재 선택
   문서로 전환한다.
3. Where 현재 문서가 루트 문서(부모 없음)이면, the breadcrumb shall 그 문서 하나만 경로로 표시한다.
4. The breadcrumb shall 조상 경로를 로드된 문서 트리로부터 파생하며, 별도의 조상 조회 API를 호출하지
   않는다(계약에 조상 전용 엔드포인트가 없음).

### Requirement 3: 문서 생성 (부모 지정)

**Objective:** As a editor 이상 권한 사용자, I want 루트 또는 특정 부모 밑에 새 문서를 만들기를,
so that 필요한 위치에 문서를 추가할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 생성 조작을 실행하고 제목과 선택적 부모를 지정하면, the 문서 생성 기능 shall
   `POST /workspaces/{workspace_id}/documents`에 `DocumentCreate`(`title`, `parent_id`)를 전송한다.
2. Where 부모를 지정하지 않으면, the 문서 생성 기능 shall `parent_id`를 비워 루트 문서로 생성 요청한다.
3. When 생성이 성공(201, `DocumentRead`)하면, the 문서 생성 기능 shall 새 문서를 트리에 반영하고 이를
   선택 문서로 확정한다.
4. If 제목이 공백이거나 유효하지 않으면, the 문서 생성 기능 shall 요청 전 또는 422 응답을 받아 사용자에게
   입력 오류를 표시한다.
5. If 부모가 존재하지 않거나(404) 비active·타 WS 부모(409) 등 백엔드 제약에 걸리면, the 문서 생성 기능
   shall 해당 오류를 사용자에게 표면화하고 트리를 원상 유지한다.
6. While 사용자가 viewer 권한만 가지면, the 문서 생성 기능 shall 생성 조작 UI를 노출하지 않는다(INV-2,
   `s16` 권한 게이팅 경유).

### Requirement 4: 문서 이름변경 (제목 수정)

**Objective:** As a editor 이상 권한 사용자, I want 문서 제목을 바꾸기를, so that 문서를 알아보기 쉽게
관리할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 문서 이름변경을 확정하면, the 이름변경 기능 shall
   `PATCH /documents/{id}`에 `DocumentUpdate`(`title`)를 전송한다.
2. When 이름변경이 성공(200, `DocumentRead`)하면, the 이름변경 기능 shall 트리·breadcrumb·상세 뷰의 해당
   제목 표시를 갱신한다.
3. If 제목이 공백이면, the 이름변경 기능 shall 요청 전 또는 422 응답을 받아 입력 오류를 표시하고 기존
   제목을 유지한다.
4. If 문서가 존재하지 않으면(404), the 이름변경 기능 shall 해당 오류를 표면화한다.
5. While 사용자가 viewer 권한만 가지면, the 이름변경 기능 shall 이름변경 조작 UI를 노출하지 않는다(INV-2).
6. The 이름변경 기능 shall 본문·버전 저장을 다루지 않으며 제목 메타데이터만 갱신한다(본문 저장은 `s20`
   소유).

### Requirement 5: 문서 삭제 (휴지통 이동, 묶음 캐스케이드 관찰)

**Objective:** As a editor 이상 권한 사용자, I want 문서를 삭제(휴지통으로 이동)하기를, so that 더 이상
필요 없는 문서와 그 하위를 정리하되 필요 시 복구할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 문서 삭제를 실행하면, the 삭제 기능 shall 파괴적 성격을 알리는 확인 절차를
   거친 뒤 `DELETE /documents/{id}`를 호출한다.
2. When 삭제가 성공(204)하면, the 삭제 기능 shall 대상 문서와 그 시점 active 하위가 트리에서 사라지도록
   목록을 갱신(재조회)한다.
3. The 삭제 기능 shall 하위까지 묶음 단위로 함께 휴지통으로 이동함을 사용자에게 안내하되, 어떤 문서가
   묶음에 포함되는지의 판정은 백엔드 엔진 결과를 그대로 반영하며 프론트에서 재계산하지 않는다
   (INV-10·11·12 관찰).
4. If 대상이 이미 비active여서 삭제할 수 없으면(409), the 삭제 기능 shall 해당 오류를 표면화한다.
5. If 문서가 존재하지 않으면(404), the 삭제 기능 shall 해당 오류를 표면화한다.
6. While 사용자가 viewer 권한만 가지면, the 삭제 기능 shall 삭제 조작 UI를 노출하지 않는다(INV-2).

### Requirement 6: 문서 이동/재정렬 (드래그앤드롭)

**Objective:** As a editor 이상 권한 사용자, I want 트리에서 문서를 드래그앤드롭으로 다른 부모 밑으로
옮기거나 형제 사이 순서를 바꾸기를, so that 문서 구조를 직접 재구성할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 트리 노드를 다른 위치로 드롭하면, the 이동 기능 shall 드롭 위치로부터 새
   부모(`new_parent_id`)와 삽입 기준 형제(`before_sibling_id`·`after_sibling_id`)를 산정하여
   `POST /documents/{id}/move`에 `DocumentMoveRequest`로 전송한다.
2. Where 문서를 루트로 옮기면, the 이동 기능 shall `new_parent_id`를 비워 루트 이동으로 요청한다.
3. When 드롭이 발생하면, the 이동 기능 shall 이동 결과를 트리에 낙관적으로 먼저 반영한 뒤 서버 응답으로
   확정한다.
4. If 이동이 순환·동일 WS 위반·비active 대상(409) 또는 잘못된 형제 참조(422)로 거부되면, the 이동 기능
   shall 낙관적 반영을 원상 복원하고 해당 백엔드 오류를 사용자에게 표면화한다.
5. When 이동이 성공(200, `DocumentRead`)하면, the 이동 기능 shall 서버가 확정한 부모·`sort_order`를 트리에
   반영한다.
6. The 이동 기능 shall 순환·동일 WS·묶음 등의 제약을 프론트에서 판정하지 않고 백엔드 엔진 판정에
   위임하며, 오직 결과와 오류만 표면화한다.
7. While 사용자가 viewer 권한만 가지면, the 이동 기능 shall 드래그앤드롭 이동을 비활성화한다(INV-2).

### Requirement 7: 읽기 전용 문서 뷰어

**Objective:** As a 워크스페이스 멤버(viewer 이상), I want 문서를 읽기 전용으로 열람하기를, so that 편집
권한 없이도 문서 내용을 안전하게 확인할 수 있다.

#### Acceptance Criteria

1. When 사용자가 문서를 선택하면, the 문서 뷰어 shall `GET /documents/{id}`로 상세(`DocumentRead`,
   `content`·`content_html` 포함)를 조회한다.
2. When 상세가 로드되면, the 문서 뷰어 shall `s16` Toast UI Editor 래퍼를 `mode:"read"`(viewer mode)로
   재사용하여 `content`(markdown)를 렌더하며, 편집 뷰와 렌더 경로를 이원화하지 않는다.
3. The 문서 뷰어 shall 자체 Toast UI Editor 인스턴스를 별도로 구성하지 않고 `s16` 단일 래퍼만 소비한다.
4. Where 사용자가 editor 이상 권한을 가지면, the 문서 뷰어 shall 편집 진입 진입점(버튼)을 노출하되, 실제
   편집 모드 동작(lock·자동저장·버전)은 `s20`에 위임한다(이 spec은 진입 seam만 제공).
5. While viewer 권한만 가진 사용자가 문서를 열람하면, the 문서 뷰어 shall 편집 진입 진입점을 노출하지
   않고 읽기 전용으로만 표시한다(INV-2).
6. If 상세 조회가 실패(404/403 등)하면, the 문서 뷰어 shall 공통 `ErrorResponse` 기반 오류를 표시하고
   본문 렌더를 하지 않는다.

### Requirement 8: 휴지통 화면 (목록/복구/완전삭제)

**Objective:** As a editor 이상 권한 사용자, I want WS 휴지통의 묶음 목록을 보고 복구하거나 완전삭제하기를,
so that 삭제된 문서를 되살리거나 영구히 제거할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 휴지통 화면에 진입하면, the 휴지통 목록 shall
   `GET /workspaces/{id}/trash`(`Page[TrashBundleRead]`)를 조회하여 묶음별(루트 문서·구성원 요약·`trashed_at`·
   `expires_at`) 목록을 표시한다.
2. The 휴지통 목록 shall 각 묶음의 `member_count`와 구성원 요약(`members`: id·parent_id·title)을 계층
   파악이 가능하도록 표시하고, `expires_at`(보관 만료 예정)을 함께 노출한다.
3. When 사용자가 어떤 묶음의 복구를 실행하면, the 휴지통 복구 기능 shall `POST /trash/{bundleId}/restore`를
   호출하고, 성공(204) 시 목록을 갱신(재조회)한다.
4. When 사용자가 어떤 묶음의 완전삭제를 실행하면, the 휴지통 완전삭제 기능 shall **되돌릴 수 없음**을 알리는
   확인 절차를 거친 뒤 `DELETE /trash/{bundleId}`를 호출하고, 성공(204) 시 목록을 갱신한다.
5. If 복구/완전삭제 대상 묶음이 유효하지 않으면(404), the 휴지통 기능 shall 해당 오류를 표면화하고 목록을
   재조회한다.
6. The 휴지통 화면 shall editor 이상에게만 접근을 노출하며(WS 전체 접근), viewer/비멤버에게는 노출하지
   않는다(INV-2, `s16` 권한 게이팅 경유; 서버측 403이 최종 강제).
7. The 휴지통 기능 shall 복구 위치·묶음 원자성·비흡수 규칙을 프론트에서 판정하지 않고 백엔드 결과만
   반영한다(INV-10·11·12).

### Requirement 9: 권한 게이팅 · 낙관적 반영 · 오류 표면화 · 현재 WS 컨텍스트 소비

**Objective:** As a 프론트엔드 사용자, I want 문서/휴지통 조작이 현재 WS 컨텍스트와 권한에 따라 일관되게
게이팅되고 백엔드 판정 결과가 정확히 표면화되기를, so that 권한 없는 조작이 UI에 노출되지 않고 백엔드
제약 위반이 명확한 오류로 전달된다.

#### Acceptance Criteria

1. The 문서/휴지통 화면 shall 현재 WS 식별자(`workspaceId`)와 현재 사용자의 WS role(`role`)을 `s16` 앰비언트
   컨텍스트 `useCurrentWorkspace()`의 최상위 접근자에서 소비하며(중첩 필드 접근·형제 s18 의존 없음), 스스로 WS
   컨텍스트를 구현하지 않는다.
2. The 문서/휴지통 화면 shall 생성·수정·삭제·이동·휴지통 등 변경 성격 UI의 노출을 `s16` 권한 게이팅 유틸
   (`hasWorkspaceRole`/`<RequireRole>`, owner ≥ editor ≥ viewer + admin bypass)로만 판정한다(INV-1·2·3).
3. When 변경 조작(생성·이름변경·이동)이 발생하면, the 화면 shall 결과를 트리·목록에 낙관적으로 반영하되,
   서버 오류 시 원상 복원한다.
4. When 백엔드가 오류를 반환하면, the 화면 shall `s16` 공용 API 클라이언트가 정규화한 `ApiError`
   (code·message·field_errors)를 그대로 표면화하며 자체 에러 형태를 발명하지 않는다.
5. If 인증이 만료(401)되면, the 화면 shall 개별 처리를 하지 않고 `s16` 전역 401 인터셉터의 로그인
   리다이렉트(returnTo 보존)에 위임한다.
6. The 문서/휴지통 화면 shall 모든 백엔드 호출을 `s16` 공용 API 클라이언트로만 수행하고, 다른 feature를
   직접 import 하지 않는다.
7. The 클라이언트 권한 게이팅 shall UI 노출 편의일 뿐이며 서버측 권한 강제(백엔드 403)를 대체하지 않음을
   전제한다.
