# Requirements Document

## Introduction

`s09-lock-version`는 MarkSpace의 **편집 잠금(edit lock)** 과 **저장 시 버전 생성(version snapshot)** 동작을
구현한다. 동시 편집 충돌을 실시간 병합(CRDT)이 아닌 단순 편집 잠금으로 방지하고, 편집자가 저장할 때마다
새 `document_version` 스냅샷을 만들어 **무한 보관**한다(rollback 없음). 편집 잠금은 시작·저장·취소/이탈·
강제 해제의 네 가지 흐름으로 구성되며, 자동 타임아웃은 두지 않는다.

이 spec은 `s01-contract-foundation`이 확정한 계약(`document`의 `lock_user_id`·`lock_acquired_at`·
`current_version_id` 컬럼, `document_version` 스키마, API 카탈로그 행 24~28, 공통 에러 모델, Base Schemas,
세션 인증·권한 resolver `require_ws_role`)과 `s07-document-core`가 실동작시킨 문서 도메인(문서 엔티티·문서
→workspace_id 어댑터·`DocumentStateEngine`)을 **재사용**하며 재정의하지 않는다. `s07`이 인정만 하고 값 설정을
위임한 lock 필드와, `s07`이 생성하지 않는 `document_version` 레코드의 쓰기 경로를 이 spec이 소유한다.

`s09`의 성공 기준은 (1) 한 문서에 대한 편집 잠금이 최대 1인만 보유하도록 보장하고(INV-9), (2) 저장 시
버전 생성·`current_version` 갱신·잠금 해제가 단일 트랜잭션으로 원자적으로 적용되며, (3) 잠금·버전 동작이
문서 삭제 상태와 **독립적**으로 동작함(§4.3)을 검증 가능하게 만드는 것이다. 산출물 언어는 한국어이며 코드
식별자는 영어 관례를 따른다. 상위 근거로 `docs/projects.md`(§2.4 document·§2.5 document_version 데이터
모델, §3 REQ-5, §4.3 편집 잠금 상태, §5 INV-9)를 참조한다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - 편집 잠금 시작(획득): editor 이상이 미잠금 문서에 잠금을 설정(`s01` 카탈로그 행 24, REQ-5.1).
  - 타인 잠금 시 편집 시작 차단과 "다른 사용자가 편집 중" 신호(행 24 충돌 응답, REQ-5.2).
  - 저장: 새 `document_version` 생성·`current_version_id` 갱신·잠금 해제(행 25, REQ-5.3·5.7).
  - 편집 취소/이탈: 잠금 해제·미저장 변경분 폐기(행 26, REQ-5.4).
  - 강제 해제: owner/admin이 잠금 해제(변경분 폐기)(행 27, REQ-5.6). 자동 타임아웃 없음(REQ-5.5).
  - 버전 목록 열람: viewer 이상이 저장 이력을 페이지 단위로 조회(행 28, REQ-5.7).
  - lock 필드(`lock_user_id`·`lock_acquired_at`)와 `document_version` 레코드의 **쓰기 경로**.
- **Out of scope (다른 spec이 소유)**:
  - 문서 엔티티·계층·CRUD·이동·렌더·status/bundle 전이 엔진(`s07`). 잠금·버전은 상태 전이를 수행하지 않는다.
  - 휴지통 목록/복구/완전삭제·보관 타이머(`s10`).
  - 과거 버전으로의 rollback(복원) 및 과거 버전 **본문 열람** — 미도입 확정(`docs/projects.md` §6).
  - 저장으로 참조가 소멸한 이미지의 보관 폴더 이동(8.7)은 `s12-attachment`가 소유. 이 spec은 버전을 생성만
    하고 첨부 아카이브를 관찰·수행하지 않는다.
  - 공유 링크(`s14`), 프론트엔드 화면. `s01`·`s05`·`s07` 계약·로직의 **정의·재구현**.
- **Adjacent expectations (상·하위에 기대·제공하는 것)**:
  - `s01` `document`·`document_version` 스키마, 에러 모델, Base Schemas, 세션 인증, 권한 resolver를 재구현
    없이 재사용하고, `s05`가 채운 `workspace_member` 데이터로 실동작하는 `require_ws_role`을 재사용한다.
  - `s07`의 문서→workspace_id 어댑터를 재사용해 `/documents/{id}/*` 경로를 게이팅하고, 문서 상태 전이는
    `s07` `DocumentStateEngine`이 소유함을 전제한다(잠금·삭제 독립, §4.3).
  - `s12-attachment`는 이 spec이 생성한 버전을 근거로 "저장 시 현재 버전에서 참조 소멸" 판정을 수행한다
    (8.7). 이 spec은 그 판정·아카이브를 소유하지 않고 버전 생성 이벤트만 제공한다.

## Requirements

### Requirement 1: 편집 잠금 시작

**Objective:** As a 워크스페이스 editor 이상 사용자, I want 문서 편집을 시작할 때 편집 잠금을 획득하기를,
so that 동시 편집 충돌 없이 단독으로 문서를 편집할 수 있다.

#### Acceptance Criteria

1. When editor 이상 사용자가 미잠금(`lock_user_id = NULL`) 문서에 편집 시작을 요청하면, the system shall 해당 문서의 `lock_user_id`를 요청자로, `lock_acquired_at`을 현재 시각으로 설정하고 잠금 정보를 반환한다.
2. If 편집 시작을 요청한 문서가 이미 다른 사용자에게 잠겨 있으면, then the system shall 편집 시작을 거부하고 다른 사용자가 편집 중임을 나타내는 충돌 응답(409)을 반환한다.
3. When 현재 잠금 보유자가 자신이 잠근 문서에 편집 시작을 다시 요청하면, the system shall 기존 잠금을 유지한 채 멱등하게 성공 응답을 반환한다.
4. The system shall 한 문서에 대한 편집 잠금을 최대 1인만 보유하도록 보장한다.
5. If 편집 시작 요청자가 해당 워크스페이스의 editor 미만(viewer)이거나 멤버가 아니면(admin 아님), then the system shall 권한 부족(403)으로 요청을 거부한다.
6. If 편집 시작 대상 문서가 존재하지 않으면, then the system shall not-found(404)를 반환한다.

### Requirement 2: 저장 시 버전 생성·current 갱신·잠금 해제

**Objective:** As a 잠금 보유 편집자, I want 편집 내용을 저장하면 새 버전이 만들어지고 현재 버전이 갱신되며
잠금이 해제되기를, so that 저장된 스냅샷이 영구 보관되고 다른 사용자가 이어서 편집할 수 있다.

#### Acceptance Criteria

1. When 잠금 보유자가 문서 저장을 요청하면, the system shall 요청 본문 markdown(`content`)으로 새 `document_version` 레코드를 생성하고 `created_by`를 요청자로 기록한다.
2. When 저장으로 새 버전이 생성되면, the system shall 해당 문서의 `current_version_id`를 새 버전으로 갱신한다.
3. When 저장이 완료되면, the system shall 해당 문서의 편집 잠금을 해제한다(`lock_user_id`·`lock_acquired_at`을 NULL로).
4. The system shall 버전 생성·`current_version_id` 갱신·잠금 해제를 단일 트랜잭션으로 원자적으로 적용한다.
5. If 저장 요청자가 해당 문서의 잠금 보유자가 아니면(미잠금이거나 타인 잠금), then the system shall 저장을 거부하고 충돌 응답(409)을 반환하며 어떤 버전도 생성하지 않는다.
6. When 저장이 성공하면, the system shall 생성된 버전의 식별자·저장자·저장 시각을 포함한 정보를 반환한다.

### Requirement 3: 편집 취소·이탈 시 잠금 해제·변경분 폐기

**Objective:** As a 잠금 보유 편집자, I want 저장하지 않고 편집을 취소하거나 이탈하면 잠금이 해제되고 변경분이
폐기되기를, so that 미저장 편집 세션이 다른 사용자를 영구히 막지 않는다.

#### Acceptance Criteria

1. When 잠금 보유자가 편집 취소를 요청하면, the system shall 해당 문서의 잠금을 해제하고 새 버전을 생성하지 않는다.
2. If 편집 취소를 요청한 문서가 이미 미잠금 상태이면, then the system shall 멱등하게 성공(변경 없음)으로 처리한다.
3. If 편집 취소 요청자가 아닌 다른 사용자가 잠금을 보유하고 있으면, then the system shall 취소를 거부하고 충돌 응답(409)을 반환한다.
4. The system shall 편집 취소로 인해 어떤 `document_version`도 생성하지 않는다.
5. If 편집 취소 요청자가 해당 워크스페이스의 editor 미만이거나 멤버가 아니면(admin 아님), then the system shall 권한 부족(403)으로 요청을 거부한다.

### Requirement 4: 강제 해제 및 자동 타임아웃 없음

**Objective:** As a owner 또는 admin, I want 방치된 편집 잠금을 강제로 해제하기를, so that 잠금 보유자가
부재해도 문서 편집을 재개할 수 있다.

#### Acceptance Criteria

1. When owner 또는 admin이 문서 강제 해제를 요청하면, the system shall 현재 잠금 보유자와 무관하게 잠금을 해제하고 변경분을 폐기한다(새 버전 생성 없음).
2. If 강제 해제 요청자가 owner 미만이고 admin이 아니면, then the system shall 권한 부족(403)으로 요청을 거부한다.
3. If 강제 해제 대상 문서가 이미 미잠금이면, then the system shall 멱등하게 성공으로 처리한다.
4. The system shall 편집 잠금에 자동 타임아웃을 두지 않는다.
5. While 문서가 잠긴 상태로 방치되어 있는 동안, the system shall 오직 강제 해제(또는 보유자 저장/취소)로만 잠금이 풀리도록 보장한다.

### Requirement 5: 버전 무한 보관·목록 열람·rollback 없음

**Objective:** As a 워크스페이스 viewer 이상 사용자, I want 문서의 저장 버전 이력을 열람하기를, so that
언제 누가 저장했는지 확인할 수 있다.

#### Acceptance Criteria

1. When viewer 이상 사용자가 문서의 버전 목록을 요청하면, the system shall 해당 문서의 `document_version` 목록을 페이지 단위(`Page[T]`)로 반환한다.
2. The system shall 각 저장마다 새 버전을 만들고 기존 버전을 삭제하거나 덮어쓰지 않는다.
3. The system shall 과거 버전으로의 rollback(복원) 기능과 과거 버전 본문 조회 엔드포인트를 제공하지 않는다.
4. Where 버전 목록이 반환되는 경우, the system shall 각 버전의 식별자·저장자·저장 시각 메타데이터를 최신 저장 순으로 제공한다.
5. If 버전 목록 요청자가 해당 워크스페이스의 viewer 미만이거나 멤버가 아니면(admin 아님), then the system shall 권한 부족(403)으로 요청을 거부한다.

### Requirement 6: 잠금·삭제 독립성

**Objective:** As a 시스템, I want 편집 잠금·버전 동작이 문서 삭제 상태와 독립적으로 동작하기를, so that
잠금과 삭제가 서로 충돌하지 않는다(§4.3).

#### Acceptance Criteria

1. The system shall 편집 잠금 획득·저장·취소·강제 해제를 문서의 `status`(active/trashed/deleted)와 독립적으로 수행한다.
2. When 잠긴 문서가 삭제(trashed/deleted)되어도, the system shall 잠금 필드를 그대로 유지하며 `s07` 상태 전이 엔진의 동작을 방해하지 않는다.
3. The system shall 잠금·버전 동작에서 문서 상태 전이(삭제/복구/완전삭제)를 수행하지 않는다.
4. The system shall 편집 잠금의 유일 근거를 `document.lock_user_id` 단일 컬럼에 두어 문서별 개별 권한이 아닌 워크스페이스 권한만으로 접근을 게이팅한다.

### Requirement 7: 계약 재사용 및 경계

**Objective:** As a 구현자, I want `s01` 계약과 `s05`·`s07` 구현을 재사용하기를, so that 계약 드리프트 없이
잠금·버전 동작만 채운다.

#### Acceptance Criteria

1. The system shall `s01` API 카탈로그 행 24~28(`POST /documents/{id}/lock`·`POST /documents/{id}/save`·`POST /documents/{id}/cancel`·`POST /documents/{id}/force-unlock`·`GET /documents/{id}/versions`)의 경로·메서드·요구 role을 그대로 구현한다.
2. The system shall `s01` `document`·`document_version` 스키마를 재사용하고 새 마이그레이션을 추가하지 않는다.
3. The system shall `s01` 세션 인증·권한 resolver(`require_ws_role`)와 `s07` 문서→workspace_id 어댑터를 재사용해 권한을 게이팅하며 resolver 위계 비교·admin bypass를 재구현하지 않는다.
4. The system shall 모든 오류를 `s01` 공통 `ErrorResponse` 형태로 반환한다.
5. The system shall 요청/응답 스키마를 `s01` Base Schemas 규약(`{Resource}Create/Read`, `Page[T]`)에 따라 정의한다.
6. When `s09` 라우터가 부팅되면, the system shall `s01` 라우터 조립 지점에 연결되어 카탈로그 행 24~28 경로가 앱 라우트에 노출된다.
