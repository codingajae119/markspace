# Requirements Document

## Introduction

`s14-sharing`는 Notion-lite 문서를 외부에 **읽기 전용 공유 링크**로 공개하는 최상위(L6) 도메인을 구현한다.
공유는 **문서 단위**이며, 워크스페이스의 `is_shareable` 플래그가 공유 가능 여부의 **게이트** 역할을 한다(게이트가
꺼져 있으면 링크를 만들거나 활성할 수 없다). 활성 링크로 접근하면 인증 없이 그 문서와 문서의 현재 active 하위
계층이 읽기 전용으로 표시되며, 문서에 새 하위가 추가되면 링크 노출 범위에 **동적으로** 포함된다. 링크 경유로
문서에 포함된 첨부(이미지·파일)도 조회할 수 있으나, 게이트가 꺼지거나 문서가 휴지통으로 가면 파일 접근도 함께
차단된다.

이 spec의 핵심 규칙은 **재발급 통일 원칙(INV-8)** 이다. 사용자가 직접 조작하는 **토글(on/off)** 만이 동일 링크의
상태를 되돌리는 예외이고, 그 밖의 모든 무효화(문서 휴지통 이동, 워크스페이스 게이트 off)는 링크를 영구히
무효화하며 다시 공유하려면 **새 토큰으로 재발급**해야 한다. 무효화된 링크는 재발급 없이 다시 접근되지 않는다
(INV-8). 무효화 판정은 상태 전이를 이 spec이 수행하지 않고, 문서 status와 워크스페이스 게이트라는 **관측 가능한
결과**를 기준으로 하며, 하위 계층(s07·s10·s05)은 상위 계층(s14)을 알지 못한다(의존 방향은 항상 아래층을 향한다).

모든 계약 엔티티(공유 API 카탈로그 행 34~37, `share_link`·`document`·`workspace`·`attachment` 스키마, 에러 모델,
Base Schemas, 세션/권한 resolver)는 `s01`이 정의한 단일 소스를 **재사용**하며 재정의하지 않는다. 권한 게이팅은
`s05`가 실동작시킨 워크스페이스 권한 resolver(`require_ws_role`)를 재사용하고(문서별 개별 권한 없음, INV-1),
문서 상태·active 하위 질의는 `s07`의 `DocumentStateEngine`·`DocumentRepository`·`MarkdownRenderer`를, 링크 경유
파일 서빙은 `s12`의 첨부 조회·저장 어댑터를 재사용한다. 산출물 언어는 한국어이며, 상위 근거로 `docs/projects.md`
(§3 REQ-7·REQ-8.4·8.5, §4.5 재발급 통일, §5 INV-6·8)를 참조한다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - 공유 링크 발급(카탈로그 행 34, `POST /documents/{id}/share`, editor 이상): 공유 가능 워크스페이스의 문서에
    대해 활성 링크(토큰)를 발급하고, 무효화 이후에는 새 토큰으로 재발급한다.
  - 공유 링크 토글(행 35, `PATCH /documents/{id}/share`, editor 이상): 동일 링크의 활성/비활성 상태를 전환한다
    (재발급 통일 원칙의 유일한 상태 기반 예외).
  - 공개 읽기 전용 렌더(행 36, `GET /public/{token}`, 공개): 활성 링크로 접근 시 문서와 현재 active 하위 계층을
    읽기 전용으로 표시하고, 하위가 추가되면 동적으로 포함한다.
  - 링크 경유 첨부 접근(행 37, `GET /public/{token}/attachments/{aid}`, 공개): 공유 문서(및 그 active 하위)에
    포함된 첨부 바이너리를 링크 경유로 조회한다.
  - 무효화·재발급 판정: 문서 휴지통 이동·완전삭제(status 관측)와 워크스페이스 게이트 off를 관측해 링크를 영구
    무효화하고, 다시 공유하려면 재발급(새 토큰)을 요구한다(INV-8).
  - 링크 경유 파일 접근의 게이트·상태·보관 연동 차단: 게이트 off·문서 휴지통·보관(archived) 첨부 시 파일 접근
    차단.
- **Out of scope (다른 spec이 소유)**:
  - `is_shareable` 플래그 자체의 설정·소유(`s05-workspace`가 owner/admin의 게이트 설정을 소유). s14는 이 플래그를
    **소비**할 뿐이다.
  - 문서 상태 전이(active→trashed→deleted)·복구·묶음 규칙(`s07-document-core` 엔진과 `s10-trash`). s14는 문서
    status를 **관측**할 뿐 전이를 수행하지 않는다.
  - 첨부 파일 저장·워크스페이스 격리·완전삭제 반응 보관 이동·참조 소멸 아카이브(`s12-attachment`). s14는 s12의
    저장·격리·아카이브 결과를 **소비(서빙)** 할 뿐이다.
  - markdown → 안전 HTML 렌더 규약(`s07-document-core`의 `MarkdownRenderer`). s14는 이를 재사용해 공개 렌더에
    적용하며 렌더 규약을 재정의하지 않는다.
  - `s01` 계약 요소(API 카탈로그·에러 모델·Base Schemas·권한 resolver 로직·세션 인증·DB 스키마)의 **정의**.
    프론트엔드 화면.
- **Adjacent expectations (이 spec이 상·하위에 기대·제공하는 것)**:
  - `s01`은 `share_link` 스키마(`document_id`·`token` UNIQUE·`is_enabled`·`created_at`)와 카탈로그 행 34~37,
    INV-8(무효화 링크는 재발급 없이 접근 불가)을 안정 계약으로 제공한다. s14는 이를 재사용하고 재정의하지 않으며,
    새 DB 마이그레이션을 추가하지 않는다.
  - `s05`는 워크스페이스 `is_shareable` 게이트를 owner/admin이 설정하도록 소유하고 `workspace_member`로
    `require_ws_role`을 실동작시킨다. s14는 게이트 값과 resolver를 소비한다.
  - `s07`은 문서 status·active 하위 집합 질의(`active_descendants`)·안전 HTML 렌더 규약을 제공한다. `s10`은
    문서를 trashed/deleted로 전환한다. s14는 이 결과를 문서 status로 **관측**해 링크 무효화를 판정하며, s07·s10·
    s05는 s14를 알지 못한다(의존 방향 준수).
  - `s12`는 첨부 저장·워크스페이스 격리·보관(archived) 결과와 첨부 조회 서빙을 제공한다. s14는 링크 경유 파일
    접근에서 이를 소비하고, 보관된 첨부는 어떤 경로로도 노출되지 않는다는 규약을 이어받는다.
  - `s15-integration-check-L6`가 무효화·재발급·링크 경유 파일 접근(INV-8 포함 전 계층 결합)을 전체 e2e로 누적
    검증한다.

## Requirements

### Requirement 1: is_shareable 게이트에 의한 공유 가능 여부 제어 (7.1·7.2)

**Objective:** As a 워크스페이스 소유자·보안 검증자, I want 워크스페이스의 `is_shareable` 게이트가 꺼져 있으면
어떤 문서도 공유 링크를 만들거나 활성할 수 없기를, so that 공유 여부가 워크스페이스 단위 정책으로 일관되게
통제된다.

#### Acceptance Criteria

1. While 문서 소속 워크스페이스의 `is_shareable`가 false인 동안, the system shall 그 문서에 대한 공유 링크 발급
   요청을 거부한다.
2. While 문서 소속 워크스페이스의 `is_shareable`가 false인 동안, the system shall 그 문서의 공유 링크를 활성
   상태로 전환하는 요청을 거부한다.
3. The system shall 워크스페이스 `is_shareable` 게이트의 값 자체를 설정·변경하지 않고 `s05`가 소유한 게이트
   값을 관측·소비하여 공유 가능 여부를 판정한다.
4. When 문서 소속 워크스페이스의 `is_shareable`가 true이고 문서가 active인 경우에 발급이 요청되면, the system
   shall 게이트를 통과시켜 발급을 허용한다.

### Requirement 2: 공유 링크 발급·재발급 (7.3·INV-8, 재발급 통일)

**Objective:** As a 워크스페이스 editor 이상 사용자, I want 공유 가능 워크스페이스의 문서에 대해 읽기 전용 공유
링크를 발급하고 무효화 이후에는 새 토큰으로 재발급하기를, so that 문서를 외부에 안전하게 공개하되 무효화된 링크는
재사용되지 않는다.

#### Acceptance Criteria

1. When editor 이상 사용자가 공유 가능 워크스페이스의 active 문서에 대해 공유 링크 발급을 요청하면, the system
   shall 활성(enabled) 상태의 링크와 그 접근 토큰을 발급하여 반환한다.
2. If viewer role만 가진 사용자 또는 비멤버가 공유 링크 발급·토글을 요청하면, the system shall 그 요청을 403
   공통 에러 응답으로 거부한다.
3. If 세션 인증되지 않은 사용자가 공유 링크 발급·토글을 요청하면, the system shall 401 공통 에러 응답으로
   거부한다.
4. When 이전에 무효화된 문서에 대해 다시 발급이 요청되면, the system shall 이전 토큰을 되살리지 않고 **새 토큰**을
   생성하여 활성 링크로 재발급한다.
5. The system shall 공유 링크를 문서 단위로 관리하고, 한 문서의 발급·재발급이 다른 문서의 링크에 영향을 주지
   않도록 한다.
6. The system shall 공유 링크 발급·토글 접근 권한을 워크스페이스 단위로만 판정하고 문서별 개별 권한을 두지
   않는다(INV-1).

### Requirement 3: 공개 읽기 전용 렌더 — 문서 + 동적 active 하위 (7.4·7.5·7.6)

**Objective:** As a 공유 링크 수신자, I want 활성 링크로 인증 없이 문서와 그 현재 active 하위 계층을 읽기 전용으로
보기를, so that 로그인 없이도 공개된 문서 트리의 최신 내용을 열람할 수 있다.

#### Acceptance Criteria

1. When 활성 공유 링크의 토큰으로 공개 접근이 요청되면, the system shall 그 문서와 문서의 현재 active 하위
   계층을 읽기 전용 형태로 반환한다.
2. The system shall 공개 렌더 본문을 `s07`의 안전 HTML 렌더 규약(스크립트·이벤트 핸들러 제거)으로 렌더링하여
   반환한다.
3. The system shall 공개 접근에서 문서의 편집·이동·삭제 등 변경 동작을 제공하지 않고 읽기 전용으로만 응답한다.
4. When 공유 문서에 새 하위 문서가 추가된 이후에 공개 접근이 요청되면, the system shall 그 시점의 현재 active
   하위 계층을 동적으로 포함하여 반환한다.
5. The system shall 공개 렌더에 문서의 현재 active 하위만 포함하고 trashed·deleted 상태의 하위는 제외한다.
6. If 존재하지 않는 토큰으로 공개 접근이 요청되면, the system shall 404 공통 에러 응답을 반환한다.

### Requirement 4: 공유 링크 토글 (7.7, 상태 기반 예외)

**Objective:** As a 워크스페이스 editor 이상 사용자, I want 발급된 공유 링크를 재발급 없이 동일 링크로 on/off
전환하기를, so that 일시적으로 공개를 중단했다가 같은 링크로 다시 공개할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 활성 링크를 비활성으로 토글하면, the system shall 그 링크의 토큰을 유지한 채 상태를
   비활성으로 전환하고 이후 그 토큰의 공개 접근을 차단한다.
2. When editor 이상 사용자가 게이트가 켜진 워크스페이스의 active 문서에서 비활성 링크를 활성으로 토글하면, the
   system shall 그 링크의 토큰을 유지한 채 상태를 활성으로 전환한다.
3. The system shall 토글을 재발급 통일 원칙의 유일한 상태 기반 예외로 취급하고, 토글 전환에서 새 토큰을 생성하지
   않는다.
4. If 무효화(문서 휴지통 이동·게이트 off)로 영구 무효화된 이전 토큰을 토글만으로 되살리려는 접근이 발생하면, the
   system shall 그 이전 토큰의 공개 접근을 허용하지 않는다(INV-8).

### Requirement 5: 무효화·재발급 원칙 — 상태·게이트 관측 (7.8·7.9·7.10·INV-8)

**Objective:** As a 보안 검증자, I want 문서가 휴지통으로 가거나 워크스페이스 게이트가 꺼지면 공유 링크가 즉시
무효화되고, 복구·게이트 재활성 후에는 재발급해야만 다시 공유되기를, so that 무효화된 링크가 재발급 없이 되살아나지
않는다(INV-8).

#### Acceptance Criteria

1. While 공유 문서가 trashed 또는 deleted 상태인 동안, the system shall 그 문서의 공유 링크 토큰에 대한 공개
   접근을 무효로 처리한다.
2. While 문서 소속 워크스페이스의 `is_shareable`가 false인 동안, the system shall 그 문서의 공유 링크 토큰에
   대한 공개 접근을 무효로 처리한다.
3. When 문서 status 또는 워크스페이스 게이트 관측으로 링크가 무효 조건에 해당하게 되면, the system shall 그 링크를
   비활성화하고 토큰을 교체하여 이전 토큰을 영구히 무효화한다.
4. When 무효화된 문서가 복구되거나 워크스페이스 게이트가 다시 켜지더라도, the system shall 이전 토큰의 공개 접근을
   자동으로 복원하지 않고 다시 공유하려면 재발급(새 토큰)을 요구한다.
5. The system shall 무효화 판정을 문서 상태 전이·게이트 설정을 스스로 수행하지 않고 문서 status·워크스페이스
   게이트라는 관측 가능한 결과에만 근거하여 수행한다.
6. The system shall 무효화 반응을 반복 수행해도 이미 무효화된 링크를 다시 무효화하거나 오류를 내지 않도록 멱등하게
   동작한다.

### Requirement 6: 링크 경유 첨부 접근 및 연동 차단 (8.4·8.5)

**Objective:** As a 공유 링크 수신자, I want 공유 문서에 포함된 이미지·첨부 파일을 링크 경유로 조회하되 게이트·문서
상태·보관에 따라 함께 차단되기를, so that 공개 문서의 이미지·파일을 볼 수 있으면서도 무효화·격리 규약이 파일
접근에도 일관되게 적용된다.

#### Acceptance Criteria

1. When 활성 공유 링크의 토큰으로 그 공유 문서 또는 문서의 active 하위에 포함된 첨부 바이너리가 요청되면, the
   system shall 그 첨부 파일 바이너리를 반환하여 다운로드·이미지 로딩을 허용한다.
2. While 문서 소속 워크스페이스의 `is_shareable`가 false이거나 공유 문서가 trashed·deleted 상태인 동안, the
   system shall 링크 경유 첨부 접근을 함께 차단하고 404 공통 에러 응답을 반환한다.
3. If 요청된 첨부가 보관(archived)된 상태이면, the system shall `s12` 규약에 따라 role·경로와 무관하게 404로
   처리하여 보관 파일을 노출하지 않는다.
4. If 요청된 첨부가 공유 문서 또는 그 active 하위에 속하지 않거나 다른 워크스페이스의 첨부이면, the system shall
   그 요청을 404로 처리하여 링크 범위 밖 파일을 노출하지 않는다(INV-6).
5. The system shall 링크 경유 파일 서빙에서 `s12`의 첨부 저장·격리·보관 규약을 재사용하고 첨부 저장·격리·보관
   판정을 재구현하지 않는다.

### Requirement 7: 계약 재사용·경계 정합 및 라우터 조립

**Objective:** As a 하위 feature 구현자·통합 체크포인트, I want s14가 `s01` 단일 계약·`s05` 게이트·resolver·`s07`
문서 상태·렌더·`s12` 첨부 서빙을 재사용하고 계약을 벗어나지 않기를, so that 계약·불변식 드리프트 없이 공유가
최상위(L6) 계층에 정합적으로 얹힌다.

#### Acceptance Criteria

1. The system shall 공유 링크·공개 렌더 응답 스키마를 `s01`의 `{Resource}Read` 규약과 Base Schemas를 상속하여
   정의하고 `share_link` 등 계약 엔티티를 재정의하지 않는다.
2. The system shall 모든 오류를 `s01` 공통 에러 응답 형태(code·message·field_errors)로 반환한다.
3. The system shall `s01` 세션 인증 의존성과 `s05`가 실동작시킨 워크스페이스 권한 resolver를 재사용해 발급·토글
   접근을 게이팅하고 resolver 위계 비교·admin bypass 로직을 재구현하지 않으며, 공개 접근 경로(행 36~37)는 인증을
   우회하되 토큰·게이트·문서 status·워크스페이스 격리로 접근 범위를 제한한다.
4. The system shall 공유 라우터를 `s01` 라우터 조립 지점에 등록하여 앱 부팅 시 카탈로그 행 34~37이 노출되도록
   하고, 무효화 반응 배치를 앱 lifespan에 연결한다.
5. The system shall `share_link`·`document`·`workspace`·`attachment` 접근을 `s01` 초기 마이그레이션 스키마 위에서
   수행하고 새 스키마 마이그레이션을 추가하지 않는다.
6. Where 토큰 생성 방식·무효화 반응 실행 주기 등 설정이 필요하면, the system shall `s01` 단일 Settings를 통해서만
   접근하고 모듈별 설정 파일을 신설하지 않는다.
7. The system shall 문서 상태 전이·active 하위 질의·안전 렌더·첨부 저장/격리/보관을 재구현하지 않고 `s07`
   `DocumentStateEngine`·`DocumentRepository`·`MarkdownRenderer`와 `s12` 첨부 서빙·저장 어댑터를 재사용한다.
