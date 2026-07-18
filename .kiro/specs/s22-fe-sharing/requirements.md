# Requirements Document

## Introduction

`s22-fe-sharing`는 Notion-lite 프론트엔드의 **문서 단위 읽기 전용 공유** 도메인 화면군
(`src/features/sharing`)을 소유한다. editor 이상 사용자가 공유 가능한 워크스페이스의 문서에 대해 공유 링크를
**발급/재발급·on-off 토글·복사·무효화 안내**를 수행하고, 링크를 받은 게스트가 인증 없이 `/share/:token`
경로에서 문서(+접근 시점의 active 하위 계층·첨부 이미지/파일)를 **읽기 전용**으로 열람하는 흐름을 구현한다.
모두 `s16-fe-foundation` 공통 레이어(게스트 라우트 프레임·공용 API 클라이언트·전역 401 인터셉터·권한 게이팅
유틸·UI 프리미티브·읽기 전용 prose(`ReadOnlyProse`)·현재 WS 앰비언트 컨텍스트 `useCurrentWorkspace()`의
`isShareable`·`role` 접근자)를 **소비만** 한다(게이트 플래그의 토글 UI는 `s18-fe-workspace` 소유).

이 spec은 프론트엔드 최상위(Wave-3 종단) 계층으로, 소비하는 백엔드 계약(s14-sharing, s01 카탈로그 행 34~37)은
이미 GO 상태이므로 실동작 공개 엔드포인트를 소비한다(mock 아님). 검증 기준은 백엔드와 동일하게
`s01-contract-foundation`의 계약 단일 소스다: 공유 발급/토글은 `ShareLinkRead`/`ShareLinkUpdate`, 공개 렌더는
`PublicDocumentRead`(인증 우회, `content_html` 최소 노출), 링크 경유 첨부는 `/public/{token}/attachments/{aid}`
바이너리 서빙, 오류는 공통 `ErrorResponse`, 무효화/재발급은 **INV-8 재발급 통일 원칙(§4.5)** 을 재사용한다.
API 형태를 새로 발명하지 않는다.

핵심 규칙은 **재발급 통일 원칙(INV-8)** 의 UI 반영이다: 사용자가 직접 조작하는 **토글(on/off)** 만 동일
토큰의 상태를 되돌리는 유일한 예외이고, 그 밖의 무효화(문서 휴지통 이동, 워크스페이스 게이트 off)는 링크를
영구히 무효화하여 **새 토큰 재발급**을 요구한다. 무효화 판정은 백엔드가 문서 status·게이트를 관찰해 수행하며,
프론트는 그 결과(관찰 가능한 신호: 문서 status·`s16` 컨텍스트 `isShareable`)를 **표면화**만 한다. 산출물 언어는 한국어이며,
상위 근거로 `s01`·`s14`·`s16`·`s18`·`s19`의 산출물과 steering(`tech.md`·`structure.md`·`roadmap.md`)을 참조한다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - **공유 링크 관리 UI(editor 이상)**: 공유 가능 워크스페이스 문서에서 링크 발급/재발급(`POST /documents/{id}/share`),
    on/off 토글(`PATCH /documents/{id}/share`), 링크 복사, 무효화/재발급 안내(INV-8).
  - **게스트 읽기 전용 뷰**: `s16`이 등록한 게스트 라우트(`/share/:token`, 인증 가드 없음)에 마운트되는 공개
    뷰어. `GET /public/{token}`으로 문서 + 접근 시점의 현재 active 하위 계층을 읽기 전용으로 렌더.
  - **링크 경유 첨부 접근·차단 반영**: 공개 렌더 HTML의 첨부 참조(`/public/{token}/attachments/{id}`)를 통한
    이미지 로딩·파일 다운로드, 그리고 게이트 off·문서 trashed 시 첨부가 문서 렌더와 함께 차단되는 상태 반영.
  - 위 화면의 게이팅 결선(editor 이상 관리 UI는 `s16` 권한 게이팅 유틸·`s16` `useCurrentWorkspace().isShareable`·
    `role` 소비, 게스트 뷰는 인증·권한과 독립)과 도메인 API 어댑터(백엔드 계약 미러링만).
- **Out of scope (다른 spec이 소유)**:
  - **`is_shareable` 게이트 플래그 관리**(설정 화면·토글 저장): `s18-fe-workspace` 단독 소유. 이 spec은 그 값을
    `s16` 현재 WS 앰비언트 컨텍스트(`useCurrentWorkspace().isShareable`)를 통해 **소비(읽기·반영)만** 한다.
  - **문서 상태 전이·인증 문서 뷰어 자체**: `s19-fe-document`·백엔드 엔진. 무효화 신호(문서 status)는 관찰만.
  - **게스트 라우트 프레임 등록**(`/share/:token` 경로 정의·가드 없음 규약): `s16-fe-foundation` 소유. 이
    spec은 그 프레임에 **마운트되는 뷰**만 구현한다.
  - **공통 레이어**(API 클라이언트·401 인터셉터·권한 게이팅·UI 프리미티브·라우터 셸·읽기 전용 prose·현재 WS
    앰비언트 컨텍스트): `s16` 소유, 소비만.
  - 백엔드 공유·공개 엔드포인트의 **동작**(발급/재발급/토글/공개 렌더/링크 경유 서빙·무효화 스윕·lazy retire):
    `s14-sharing` 백엔드가 이미 소유·구현. 이 spec은 계약을 소비만 한다.
- **Adjacent expectations (인접 seam)**:
  - **`s21-fe-attachment`(동일 wave, 병렬 생성)**: 링크 경유 첨부 렌더는 `s01` 공개 서빙 경로
    (`/public/{token}/attachments/...`)를 통해서만 정합하며, 인증 첨부 렌더(s21)와는 경로가 다르다.
    cross-spec 리뷰에서 정합한다.
  - **`s19-fe-document`(upstream)**: 공유 관리 UI는 인증 문서 뷰 표면에서 현재 선택 문서를 대상으로 노출되며,
    문서 status는 이 spec의 무효화 안내가 관찰하는 신호다. 뷰어 render 경로를 이 spec이 이원화하지 않는다.
  - **계약 공백(seam)**: `s01` 카탈로그에는 **문서의 현재 공유 링크를 조회하는 GET 엔드포인트가 없다**
    (행 34~37은 발급 POST·토글 PATCH·공개 GET만). 따라서 관리 UI는 cold load 시 기존 링크 존재/상태를
    권위 있게 열거할 수 없으며, 뮤테이션(발급/토글) 응답으로 확인된 링크 상태만 세션 내에서 관리한다. GET
    공유 링크 엔드포인트를 발명하지 않는다.

## Requirements

### Requirement 1: 공유 링크 관리 진입·게이팅·게이트 반영

**Objective:** As a 워크스페이스 editor 이상 사용자, I want 공유 가능한 문서에 대해서만 공유 링크 관리 UI가
노출되고 게이트 상태가 반영되기를, so that 권한·게이트가 없는 상태에서 발급/활성화를 시도해 혼란을 겪지 않는다.

#### Acceptance Criteria

1. The system shall 공유 링크 관리 UI의 노출을 `s16` 권한 게이팅 유틸(`hasWorkspaceRole`/`<RequireRole>`,
   최소 role=editor)과 세션 `is_admin`(admin override)만으로 판정하고, 컴포넌트별 역할 문자열 비교를 하지 않는다.
2. While 현재 사용자가 viewer 권한만 가진 경우, the system shall 공유 링크 발급·토글·재발급 조작 UI를
   노출하지 않는다(읽기 전용, INV-2).
3. When 관리 UI가 현재 워크스페이스의 게이트가 off임을 `s16` 현재 WS 앰비언트 컨텍스트의 `isShareable`
   접근자(`useCurrentWorkspace().isShareable`)에서 관찰하면, the system shall 발급·활성화 조작을 비활성 상태로
   반영하고 게이트가 꺼져 공유할 수 없음을 안내한다.
4. Where 문서의 현재 공유 링크를 조회하는 백엔드 엔드포인트가 없는 경우, the system shall 발급/토글 뮤테이션
   응답으로 확인된 링크 상태만 세션 내 상태로 관리하고, 열거되지 않은 사전 링크 존재 여부를 단정하지 않는다.
5. The system shall 관리 UI의 게이팅이 UI 노출 편의일 뿐 서버측 권한 강제(백엔드 403)·게이트 강제(409)를
   대체하지 않음을 계약으로 전제한다.

### Requirement 2: 공유 링크 발급·재발급 (POST /share, INV-8)

**Objective:** As a 워크스페이스 editor 이상 사용자, I want 공유 가능한 active 문서에 대해 공유 링크를
발급하고 무효화 이후에는 새 토큰으로 재발급하기를, so that 문서를 외부에 안전하게 공개하되 무효화된 링크는
되살아나지 않는다(INV-8).

#### Acceptance Criteria

1. When 사용자가 발급을 실행하면, the system shall `POST /documents/{id}/share`를 호출하고 응답
   `ShareLinkRead`(token·is_enabled·`share_url`)을 세션 링크 상태로 반영한다.
2. When 발급이 성공하면, the system shall 응답의 `token`으로 게스트가 열람할 프론트 공유 링크
   (`/share/{token}`)를 구성해 사용자에게 제시한다(백엔드 `share_url`은 공개 API 경로이며 그대로 노출하지 않는다).
3. When 이미 발급 이력이 있는 문서에 대해 다시 발급이 실행되면, the system shall 재발급이 이전 토큰을 되살리지
   않고 **새 토큰**을 반환함(INV-8)을 반영하고, 이전에 배포한 링크는 더 이상 유효하지 않음을 사용자에게 안내한다.
4. If 발급 요청이 문서 부재로 404, viewer/비멤버로 403, 게이트 off·비active 문서로 409를 반환하면, the system
   shall 해당 `ApiError`를 사유에 맞게 표면화하고 세션 링크 상태를 변경하지 않는다.

### Requirement 3: 공유 링크 토글 on/off (PATCH /share, 토큰 유지)

**Objective:** As a 워크스페이스 editor 이상 사용자, I want 발급된 공유 링크를 재발급 없이 동일 링크로 on/off
전환하기를, so that 일시적으로 공개를 끄고 다시 켤 때 같은 링크를 재사용한다(재발급 통일 원칙의 유일한 예외).

#### Acceptance Criteria

1. When 사용자가 링크를 비활성화하면, the system shall `PATCH /documents/{id}/share`(`is_enabled=false`)를
   호출하고 응답을 반영하며, 토큰이 유지됨을 UI에 반영한다.
2. When 사용자가 링크를 활성화하면, the system shall `PATCH /documents/{id}/share`(`is_enabled=true`)를 호출하고,
   게이트 on·문서 active 조건 미충족으로 409가 반환되면 그 사유를 표면화하되 토큰을 새로 만들지 않는다.
3. If 토글 대상 링크가 없어 404가 반환되면, the system shall 링크가 없음을 안내하고 발급을 유도한다(토글은
   존재하는 링크만 전환 가능).
4. The system shall 토글을 재발급 통일 원칙(INV-8)의 유일한 상태 기반 예외로 취급하고, 무효화(retire)로 영구
   소멸한 이전 토큰이 토글만으로 되살아난다고 안내하지 않는다.

### Requirement 4: 공유 링크 복사

**Objective:** As a 워크스페이스 editor 이상 사용자, I want 발급된 공유 링크를 한 번의 조작으로 클립보드에
복사하기를, so that 게스트에게 전달하기 위해 링크를 수기로 옮겨 적지 않는다.

#### Acceptance Criteria

1. When 사용자가 링크 복사를 실행하면, the system shall 현재 활성 토큰으로 구성한 절대 게스트 링크
   (origin + `/share/{token}`)를 클립보드에 복사한다.
2. When 복사가 완료되면, the system shall 복사됨을 사용자에게 즉시 피드백한다.
3. If 클립보드 접근이 실패하면, the system shall 오류 없이 링크 문자열을 사용자가 직접 선택·복사할 수 있는
   형태로 표시하는 폴백을 제공한다.
4. While 활성 링크가 없는 상태(미발급·비활성)에서, the system shall 복사 조작을 제공하지 않거나 비활성으로 둔다.

### Requirement 5: 무효화·재발급 안내 (INV-8, 관찰 신호 표면화)

**Objective:** As a 워크스페이스 editor 이상 사용자, I want 문서가 휴지통으로 이동하거나 워크스페이스 게이트가
꺼져 공유 링크가 무효화되었을 때 재발급이 필요함을 안내받기를, so that 무효화된 링크가 재발급 없이 되살아난다고
오해하지 않는다(INV-8).

#### Acceptance Criteria

1. When 관리 UI가 문서 status가 active가 아니거나 `s16` 현재 WS 컨텍스트의 `isShareable`이 off인 관찰 신호를
   확인하면, the system shall 현재 공유 링크가 무효화되었을 수 있으며 다시 공유하려면 재발급이 필요함을 안내한다.
2. The system shall 무효화 판정(상태 전이·게이트 설정·토큰 교체 retire)을 스스로 수행하지 않고 백엔드 관찰
   결과(문서 status·`s16` 컨텍스트 `isShareable`)만 신호로 삼아 안내를 표면화한다.
3. The system shall 무효화 이후 문서 복구·게이트 재활성만으로 이전 토큰이 자동 복원되지 않으며 재발급(새 토큰)이
   필요함을 안내에 명시한다.
4. If 게스트 링크가 무효화되어 공개 렌더가 404로 통일 응답되면, the system shall 게스트 측에서 무효 사유를
   구분·추정하지 않고 링크를 사용할 수 없음만 안내한다(존재 추정 차단).

### Requirement 6: 게스트 읽기 전용 뷰 (/share/:token, GET /public/{token}, 공개)

**Objective:** As a 링크를 받은 게스트, I want 인증 없이 `/share/:token`에서 공유 문서와 하위 계층을 읽기
전용으로 열람하기를, so that 계정 없이도 공유된 문서를 볼 수 있으면서 편집·변경은 할 수 없다.

#### Acceptance Criteria

1. The system shall 게스트 뷰를 `s16`이 등록한 게스트 라우트(`/share/:token`, 인증 가드 없음)에 마운트하고,
   세션·워크스페이스 권한과 독립적으로 렌더한다.
2. When 게스트 뷰가 로드되면, the system shall 경로 파라미터 `token`으로 `GET /public/{token}`을 호출하되 전역
   401 리다이렉트를 유발하지 않는 공개 호출로 수행한다.
3. When 공개 렌더 응답(`PublicDocumentRead`)을 받으면, the system shall 루트 문서와 그 `children`(접근 시점의
   현재 active 하위 계층)을 중첩 트리로 읽기 전용 표시하고, 서버가 산정한 `content_html`을 렌더한다.
4. The system shall 게스트 뷰에서 편집·이동·삭제·발급 등 변경 성격의 조작을 일절 제공하지 않는다(읽기 전용).
5. If `GET /public/{token}`이 404를 반환하면, the system shall 무효/미존재/보관/게이트 off 사유를 구분하지 않고
   링크를 사용할 수 없음을 안내한다(존재 추정 차단).
6. The system shall 공개 렌더의 읽기 표시가 인증 뷰어(s19)와 시각적으로 일관되도록 `s16`이 단일 소유하는 읽기
   전용 prose 스타일(`ReadOnlyProse`/공용 prose CSS)을 소비하되, 게스트 뷰가 별도 에디터 인스턴스를 구성하지
   않고 서버 산정 안전 HTML(`content_html`)을 읽기 전용으로 표시한다(에디터 미사용은 허용된 예외, 렌더 경로 포크 아님).

### Requirement 7: 링크 경유 첨부 접근·차단 반영

**Objective:** As a 링크를 받은 게스트, I want 공유 문서 안의 이미지가 표시되고 첨부 파일을 내려받을 수
있기를, so that 텍스트뿐 아니라 문서에 포함된 이미지·파일까지 온전히 열람할 수 있다.

#### Acceptance Criteria

1. The system shall 공개 렌더 HTML의 첨부 참조(`/public/{token}/attachments/{id}`)를 브라우저가 백엔드 공개
   서빙 엔드포인트에서 로드할 수 있도록 단일 설정의 API base URL 기준 절대 경로로 재작성한다.
2. When 게스트 뷰가 이미지 참조를 렌더하면, the system shall 해당 이미지가 `/public/{token}/attachments/{id}`
   공개 서빙으로 인증 없이 로딩되도록 한다.
3. Where 첨부가 파일(다운로드) 성격인 경우, the system shall 링크 경유 공개 서빙 경로를 통해 내려받을 수 있는
   접근을 제공한다.
4. When 워크스페이스 게이트가 off이거나 문서가 trashed되어 공개 렌더가 404로 통일 차단되면, the system shall
   그 문서의 링크 경유 첨부도 함께 접근 불가 상태로 반영한다(문서 렌더와 첨부 차단의 결합).
5. The system shall 첨부 참조 재작성을 서버가 산정한 참조 id 경계를 보존하는 문자열 변환으로만 수행하고, 참조
   범위·격리·보관 판정(백엔드 소유)을 재구현하지 않는다.

### Requirement 8: 공통 레이어 단일 소비·격리·오류 표면화

**Objective:** As a 하위 화면 구현자, I want 공유·공개 호출과 오류 처리가 `s16` 공통 레이어 단일 경로로
수행되기를, so that 이 feature가 자체 fetch·에러 파싱·라우팅 가드를 중복 구현하지 않고 계약 드리프트를 피한다.

#### Acceptance Criteria

1. The system shall 모든 백엔드 호출(발급·토글·공개 렌더)을 `s16` `apiClient` 단일 경로로 수행하고, 자체 fetch·
   base URL 상수·에러 파싱을 두지 않는다.
2. The system shall 모든 오류를 `s16` `apiClient`가 정규화한 `ApiError`로 받아 `ErrorMessage`/상태로 표면화만
   하고, 새 에러 코드/형태를 발명하지 않는다.
3. While 게스트가 공개 리소스를 열람하는 동안, the system shall 공개 호출에서 보호 라우트용 401 리다이렉트가
   강제되지 않도록 한다.
4. The system shall 계약 미러 타입(`ShareLinkRead`·`ShareLinkUpdate`·`PublicDocumentRead`·`PublicDocumentNode`)을
   백엔드 스키마 형태로만 미러링하고 새 필드를 발명하지 않으며, TypeScript strict(`any` 금지)를 준수한다.
5. The system shall 다른 feature 폴더(`src/features/*`)를 직접 import 하지 않고 공통 레이어(`s16` 현재 WS
   앰비언트 컨텍스트 `useCurrentWorkspace()` 포함)만 소비한다.
