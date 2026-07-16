# Requirements Document

## Introduction

`s10-trash`는 Notion-lite 문서 3단계 생명주기(active → trashed → deleted)의 **휴지통 단계 API·UX**를
구현한다. 워크스페이스 휴지통의 **묶음(bundle) 목록 열람**, **묶음 복구**, **묶음 즉시 완전삭제**,
그리고 **묶음별 독립 보관 타이머에 따른 자동 영구삭제 배치**를 소유한다. editor 이상 사용자는 워크스페이스
휴지통 전체(본인 삭제분 외 포함)에 접근하고, viewer는 접근할 수 없다(REQ-6.11, INV-2).

이 spec의 핵심 성격은 **s07-document-core가 소유한 `DocumentStateEngine` primitive를 소비하는 얇은 레이어**라는
점이다. 삭제/복구/완전삭제/묶음 식별의 상태 전이 규칙(비흡수·복구 위치·독립 타이머 기준, INV-10·11·12)은
s07 엔진에 단일 구현으로 캡슐화되어 있으며, **s10은 그 규칙을 재구현하지 않고 엔진 primitive**
(`identify_bundles`·`get_bundle`·`restore_bundle`·`purge_bundle`)를 **호출하기만 한다**. 묶음은 s07 규약대로
**루트 문서 id**로 식별되며(카탈로그의 `{bundleId}` = 묶음 루트 문서 id), 보관 타이머는 각 묶음의 `trashed_at`을
엔진의 묶음 식별로 확정한 뒤 워크스페이스 `trash_retention_days`를 더해 독립 산정한다.

모든 계약 엔티티(휴지통 API 카탈로그 행 29~31, 에러 모델, Base Schemas, 세션/권한 resolver, `document`·
`workspace` 스키마, `trash_retention_days`·기본 보관일 Settings)는 `s01`이 정의한 단일 소스를 **재사용**하며
재정의하지 않는다. 권한 게이팅은 `s05`가 실동작시킨 워크스페이스 권한 resolver(`require_ws_role`)를 재사용한다
(문서별 개별 권한 없음, INV-1). 산출물 언어는 한국어이며, 상위 근거로 `docs/projects.md`(§2.2 workspace·§2.4
document 데이터 모델, §3 REQ-6.8~6.11, §4.1~4.2 상태 전이·묶음 규칙, §5 INV-2·3·4·7·10·11·12)를 참조한다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - 휴지통 묶음 목록 조회 API(카탈로그 행 29, `GET /workspaces/{id}/trash` → `Page[TrashBundleRead]`):
    워크스페이스의 trashed 묶음을 엔진 `identify_bundles`로 열거하고, 각 묶음의 루트·구성원·`trashed_at`·
    보관 만료 예정 시각을 표시용 스키마로 노출.
  - 묶음 복구 API(행 30, `POST /trash/{bundleId}/restore`): 엔진 `restore_bundle` 호출. 복구 위치·순서 규칙
    자체는 s07 엔진이 결정하며 s10은 호출·결과 반영만 담당.
  - 묶음 완전삭제 API(행 31, `DELETE /trash/{bundleId}`): 엔진 `purge_bundle` 호출로 해당 묶음만 즉시 deleted
    전환. 되돌릴 수 없는 조작에 대한 확인 절차 계약.
  - 보관 만료 자동 영구삭제 배치: 각 묶음의 `trashed_at` + 워크스페이스 `trash_retention_days` 경과 묶음을
    엔진 `purge_bundle`로 자동 deleted 전환. 묶음별 독립 타이머(INV-12).
  - editor 이상의 워크스페이스 휴지통 전체 접근 권한 게이팅과 viewer 차단(INV-2). 묶음 id(루트 문서 id)로부터
    소속 워크스페이스를 확정해 resolver에 주입하는 매핑.
- **Out of scope (다른 spec이 소유)**:
  - bundle/status 전이 로직 자체(삭제 캐스케이드·비흡수·복구 위치·완전삭제 원자성·묶음 식별) — s07
    `DocumentStateEngine`가 단일 구현으로 소유. s10은 primitive를 **호출만** 한다.
  - 완전삭제(deleted 전환) 시 첨부 파일 "삭제된 파일 보관 폴더" 이동(8.6) — s12-attachment가 완전삭제 결과를
    관찰·수행. s10의 완전삭제·자동삭제는 **문서 상태 전이만** 트리거한다.
  - 문서 trashed 전이 시 공유 링크 무효화·재발급(7.8~7.10, INV-8) — s14-sharing 소유.
  - active → trashed 삭제(카탈로그 행 23, `DELETE /documents/{id}`)와 삭제 캐스케이드 — s07 소유.
  - `s01` 계약 요소(API 카탈로그·에러 모델·Base Schemas·권한 resolver 로직·세션 인증·DB 스키마)의 **정의**와
    `s05` 워크스페이스·멤버십·`trash_retention_days` 설정 **동작**. 프론트엔드 화면.
- **Adjacent expectations (이 spec이 상·하위에 기대·제공하는 것)**:
  - `s07`은 `DocumentStateEngine`의 `Bundle` DTO와 primitive(`identify_bundles`·`get_bundle`·`restore_bundle`·
    `purge_bundle`)를 안정 계약으로 제공한다. s10은 이 계약에만 의존하고 문서 상태·묶음 규칙을 재구현하지 않는다.
  - `s05`가 소유·설정한 워크스페이스 `trash_retention_days`(기본 30, `s01` Settings `default_trash_retention_days`)를
    보관 만료 산정의 유일 근거로 소비한다. `s05`가 채운 `workspace_member`로 `require_ws_role`이 실동작한다.
  - `s12-attachment`는 s10의 완전삭제·자동 영구삭제로 문서가 deleted가 되는 사건을 관찰해 첨부 보관 이동(8.6)을
    수행한다. `s11-integration-check-L4`가 잠금↔삭제 독립·묶음 타이머·엔진 결합을 누적 검증한다.
  - 완전삭제·자동삭제 이후 deleted 문서는 종착 상태이며 애플리케이션 복원 경로가 없다(INV-7). 휴지통 목록은
    trashed 묶음만 노출하고 deleted는 노출하지 않는다.

## Requirements

### Requirement 1: 휴지통 묶음 목록 조회

**Objective:** As a 워크스페이스 editor 이상 사용자, I want 워크스페이스 휴지통에 있는 삭제 묶음의 목록을
묶음 단위로 조회하기를, so that 무엇이 언제 삭제되었고 언제 자동 영구삭제되는지 파악해 복구·완전삭제를 결정할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 워크스페이스 휴지통 목록을 요청하면, the system shall 그 워크스페이스의 trashed 묶음 전체를 묶음 단위로 열거해 반환한다.
2. The system shall 묶음 목록을 s07 상태 엔진의 묶음 식별 결과로 구성하고 무엇이 하나의 묶음인지를 자체적으로 재판정하지 않는다.
3. When 각 묶음이 목록에 표현되면, the system shall 해당 묶음의 루트 문서 식별자·루트 제목·구성원 요약·묶음 공통 trashed_at·보관 만료 예정 시각을 함께 제공한다.
4. The system shall 각 묶음의 보관 만료 예정 시각을 그 묶음의 trashed_at에 워크스페이스 trash_retention_days를 더한 값으로 산정한다.
5. When 휴지통 목록이 반환되면, the system shall trashed 상태 묶음만 포함하고 이미 deleted(영구삭제)된 문서는 노출하지 않는다.
6. The system shall editor 이상 사용자에게 본인이 삭제하지 않은 묶음을 포함한 워크스페이스 휴지통 전체를 노출한다.
7. If viewer role만 가진 사용자가 휴지통 목록을 요청하면, the system shall 해당 요청을 403으로 거부한다.
8. If 대상 워크스페이스가 존재하지 않으면, the system shall 404 공통 에러 응답을 반환한다.

### Requirement 2: 묶음 복구

**Objective:** As a 워크스페이스 editor 이상 사용자, I want 휴지통의 특정 묶음을 복구하기를, so that 실수로
삭제했거나 다시 필요해진 문서 서브트리를 워크스페이스로 되돌릴 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 묶음 복구를 요청하면, the system shall s07 상태 엔진의 복구 primitive를 해당 묶음 루트에 대해 호출해 묶음 전체를 active로 되돌린다.
2. The system shall 복구 위치(부모 밑/root)·정렬 순서 복원·자동 재중첩 여부 규칙을 s07 엔진이 결정하도록 위임하고 그 규칙을 재구현하지 않는다.
3. When 복구가 요청된 묶음 루트가 유효한 묶음 루트가 아니면(존재하지 않거나 trashed 묶음 루트가 아님), the system shall 404 공통 에러 응답을 반환한다.
4. The system shall 한 묶음의 복구가 다른 독립 묶음을 함께 되살리지 않도록 복구를 요청된 묶음에만 적용한다.
5. If viewer role만 가진 사용자가 묶음 복구를 요청하면, the system shall 해당 요청을 403으로 거부한다.
6. When 복구 요청 사용자가 본인이 삭제하지 않은 묶음을 지정하면, the system shall editor 이상 권한만으로 그 묶음을 복구할 수 있게 한다.

### Requirement 3: 묶음 완전삭제 및 확인 절차

**Objective:** As a 워크스페이스 editor 이상 사용자, I want 휴지통의 특정 묶음을 즉시 완전삭제하기를, so that
보관 기간을 기다리지 않고 불필요한 문서 묶음을 영구히 제거할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 묶음 완전삭제를 요청하면, the system shall s07 상태 엔진의 완전삭제 primitive를 해당 묶음 루트에 대해 호출해 묶음 전체를 즉시 deleted로 전환한다.
2. The system shall 완전삭제를 요청된 묶음에만 적용하고 다른 독립 묶음의 상태와 보관 타이머에 영향을 주지 않는다.
3. Where 완전삭제가 물리 삭제 없이 수행되는 경우, the system shall 레코드를 제거하지 않고 상태 전환(deleted)만으로 영구삭제를 표현하며 deleted를 복원 경로 없는 종착 상태로 취급한다.
4. Because 완전삭제는 되돌릴 수 없으므로, the system shall 완전삭제 요청 전에 사용자 확인 절차를 거치도록 하는 계약을 제공한다.
5. When 완전삭제가 요청된 묶음 루트가 유효한 묶음 루트가 아니면, the system shall 404 공통 에러 응답을 반환한다.
6. If viewer role만 가진 사용자가 묶음 완전삭제를 요청하면, the system shall 해당 요청을 403으로 거부한다.
7. The system shall 완전삭제를 문서 상태 전이에 한정하고 첨부 파일 보관 이동·공유 링크 무효화는 소유하지 않는다.

### Requirement 4: 보관 만료 자동 영구삭제 배치 (묶음별 독립 타이머)

**Objective:** As a 시스템 운영자·상태 엔진 소비자, I want 보관일을 경과한 휴지통 묶음이 묶음별 독립 타이머에
따라 자동으로 영구삭제되기를, so that 휴지통이 수동 개입 없이 워크스페이스 보관 정책대로 정리된다.

#### Acceptance Criteria

1. When 어떤 묶음이 trashed된 지 그 워크스페이스의 trash_retention_days(기본 30일)를 경과하면, the system shall 그 묶음을 s07 완전삭제 primitive로 deleted(영구삭제)로 전환한다.
2. The system shall 각 묶음의 만료 여부를 그 묶음의 trashed_at을 기준으로 독립 산정하고, 다른 묶음의 삭제·복구가 그 기준에 영향을 주지 않도록 한다.
3. The system shall 자동 영구삭제 대상 묶음을 s07 상태 엔진의 묶음 식별로 확정하고 묶음 경계를 자체적으로 재구성하지 않는다.
4. While 자동 영구삭제 배치가 주기적으로 실행되는 동안, the system shall 만료된 묶음만 전환하고 아직 보관 기간이 남은 묶음은 그대로 둔다.
5. Where 동일 부모의 자식 묶음과 부모 묶음이 서로 다른 trashed_at을 가지는 경우, the system shall 각자의 만료 시점에 독립적으로 영구삭제되도록 하며 통상 자식 묶음이 먼저 만료됨을 허용한다.
6. When 자동 영구삭제 배치가 이미 deleted되었거나 복구되어 더 이상 존재하지 않는 묶음을 만나면, the system shall 오류 없이 해당 묶음을 건너뛴다.
7. The system shall 자동 영구삭제 배치를 반복 실행해도 이미 처리된 묶음에 중복 전이를 일으키지 않도록 멱등하게 동작한다.

### Requirement 5: 접근 권한·경계

**Objective:** As a 보안·권한 검증자, I want 휴지통 접근이 워크스페이스 단위 editor 이상으로만 게이팅되고
viewer는 차단되기를, so that 문서별 개별 권한 없이 워크스페이스 권한 모델(INV-1·2·3)이 휴지통에도 일관되게 적용된다.

#### Acceptance Criteria

1. The system shall 휴지통 목록·복구·완전삭제 접근을 워크스페이스 단위 editor 이상 권한으로만 허용한다.
2. If viewer 또는 비멤버 사용자가 휴지통 목록·복구·완전삭제에 접근하면, the system shall 403 공통 에러 응답으로 거부한다.
3. The system shall admin 사용자의 휴지통 접근을 어떤 권한 검사로도 차단하지 않는다.
4. The system shall 묶음 id(루트 문서 id)로부터 소속 워크스페이스를 확정해 권한 resolver에 주입하되 resolver의 위계 비교·admin bypass 로직을 재구현하지 않는다.
5. If 요청이 세션 인증되지 않았으면, the system shall 401 공통 에러 응답으로 거부한다.
6. The system shall 워크스페이스 단위로만 휴지통 권한을 판정하고 묶음·문서별 개별 권한을 두지 않는다.

### Requirement 6: 엔진 재사용·계약 정합 및 라우터 조립

**Objective:** As a 하위 feature 구현자·통합 체크포인트, I want s10이 s07 상태 엔진 primitive와 `s01` 단일
계약·`s05` 권한 resolver를 재사용하고 계약을 벗어나지 않기를, so that 계약·불변식 드리프트 없이 휴지통이 L4
계층에 정합적으로 얹힌다.

#### Acceptance Criteria

1. The system shall 삭제/복구/완전삭제/묶음 식별 상태 전이 규칙(INV-10·11·12)을 재구현하지 않고 s07 `DocumentStateEngine` primitive를 호출해 소비한다.
2. The system shall 휴지통 응답 스키마를 `s01`의 `{Resource}Read` 규약과 Base Schemas(`Page` 포함)를 상속하여 정의하고 계약 엔티티를 재정의하지 않는다.
3. The system shall 모든 오류를 `s01` 공통 에러 응답 형태(code·message·field_errors)로 반환한다.
4. The system shall `s01` 세션 인증 의존성과 `s05`가 실동작시킨 워크스페이스 권한 resolver를 재사용해 휴지통 접근을 게이팅한다.
5. The system shall 휴지통 라우터를 `s01` 라우터 조립 지점에 등록하여 앱 부팅 시 카탈로그 행 29~31이 노출되도록 한다.
6. The system shall `document`·`workspace` 접근을 `s01` 초기 마이그레이션 스키마 위에서 수행하고 새 스키마 마이그레이션을 추가하지 않는다.
7. Where 보관일 기본값·배치 실행 주기 등 설정이 필요하면, the system shall `s01` 단일 Settings를 통해서만 접근하고 모듈별 설정 파일을 신설하지 않는다.
