# Requirements Document

## Introduction

`s08-integration-check-L3`는 **계층 3(L3)의 누적 통합 검증 체크포인트**다. 이 시점까지 완성된 upstream 누적
집합(`s01-contract-foundation` ⊕ `s02-auth` ⊕ `s03-admin-account` ⊕ `s05-workspace` ⊕ `s07-document-core`)이
공유 계약과 정합하는지, 그리고 이번 계층에서 처음 결합되는 **경계(문서 도메인 ↔ 워크스페이스 권한 경계 ↔ 세션
인증·계정 생명주기)**가 실제 결합 상태에서 성립하는지 mock 없이 검증한다.

이 체크포인트는 **feature 로직을 구현하지 않는다.** 새 엔드포인트·서비스·스키마·마이그레이션·상태 엔진을
추가하지 않으며, 오직 (1) 누적 upstream의 계약·경계 정합 검증과 (2) 그 검증을 실제 구현 결합으로 실행하는
integration/e2e 테스트만 소유한다. 검증의 유일한 대조 기준은 개별 spec(s02·s03·s05·s07)의 design이 아니라
**`s01-contract-foundation`의 단일 소스**(데이터 스키마 · 세션/권한 resolver 계약 · 문서 API 카탈로그 행 18~23 ·
공통 에러 모델 · 불변식 카탈로그 INV-1~12)다.

L3의 검증 초점은 **문서 권한 게이팅(문서 CRUD·이동이 `require_ws_role` 계약대로 게이트되는지, INV-1·2·3)**과
**bundle 전이 엔진 정합(INV-5·6·10·11·12 — status 전이, 계층 이동 순환 방지, 동일 WS 제약, bundle 비흡수·보관
기준의 독립성)**이다. 특히 `s07`이 `DocumentStateEngine` 단일 구현으로 캡슐화한 삭제 캐스케이드·복구 위치 규칙·
완전삭제 원자성·묶음 식별이 실제 API·엔진 결합에서 불변식을 유지하는지, 그리고 문서→WS 어댑터를 통한 권한
게이팅이 `s05`가 채운 실제 `workspace_member` 데이터 위에서 계약대로 판정하는지를 실제 결합으로 확인한다. 또한
아래 계층(auth·admin-account·workspace)과의 결합(삭제된 사용자의 문서 작성자 표시 보존, admin의 비멤버 WS 문서
접근, 문서를 보유한 워크스페이스의 삭제 거부)까지 누적 검증한다.

이 체크포인트는 로드맵의 **게이트 G-1**(각 체크포인트가 상위 계층 impl 착수의 선행 조건이 되는 게이트 규칙)을
담당한다: 이 체크포인트가 통과하기 전에는 L4(`s09-lock-version`, `s10-trash`)의 impl을 착수할 수 없다. 또한
upstream(s01·s02·s03·s05·s07) 중 하나라도 수정되면 이 체크포인트를 누적 집합 기준으로 재실행하는 **재검증
트리거**의 대상이다.

산출물 언어는 한국어이며, 상위 근거로 `docs/projects.md` §2.4·§2.5, §3 REQ-4·REQ-6, §4.1~4.3, §5
INV-1·2·3·4·5·6·10·11·12, `s01-contract-foundation/design.md`(§Physical Data Model document·document_version ·
§API Endpoint Catalog 18~23 · §Errors · §Invariants Catalog · §Common/Permissions), `s07-document-core/design.md`
(§DocumentStateEngine·§DocumentWsAdapter·삭제 캐스케이드·복구 primitive·정밀도 Risk),
`s06-integration-check-L2/design.md`(재사용·확장할 통합 테스트 하네스 패턴), `.kiro/steering/roadmap.md`
(게이트·재검증 트리거)를 참조한다.

## Boundary Context

- **In scope (이 체크포인트가 소유)**:
  - **계약 대조 검증**: 실제 결합된 시스템의 `document`·`document_version` 스키마, 문서 CRUD·이동·삭제 API
    (`s01` 카탈로그 행 18~23), status 전이 계약, 공통 에러 모델이 `s01` 단일 소스와 일치하는지 대조.
  - **문서 권한 게이팅 검증(이번 계층 신규 경계 = 문서 도메인 ↔ 권한 경계)**:
    - editor 이상 멤버가 문서·하위 문서 생성·수정·이동·삭제에 성공하고, viewer는 이들 변경 작업에서 거부(403)됨
      (INV-2 읽기 전용), 조회는 viewer 이상 통과.
    - 어떤 워크스페이스의 멤버가 아닌 사용자가 그 워크스페이스의 문서 라우트에 접근하면 거부(403)됨(INV-1).
    - `/documents/{id}` 라우트가 문서→WS 어댑터로 workspace_id를 추출해 `require_ws_role`로 게이트됨.
  - **문서 계층·이동 정합 검증(INV-5·6)**: 같은 WS 내 이동·재정렬(중간 삽입 포함) 성공, 자기 자신·후손으로의
    이동 거부(INV-5 순환 방지), 다른 WS로의 이동 거부(INV-6 WS 경계 유지).
  - **bundle 삭제 캐스케이드·비흡수 검증(INV-10·11)**: `DELETE /documents/{id}`가 그 시점 active 하위만
    묶음으로 포착(6.2)하고 공통 `trashed_at`을 부여, 이미 trashed된 자식은 흡수하지 않으며(6.4, INV-11) 독립
    묶음으로 식별, `child.trashed_at ≤ parent.trashed_at` 성립.
  - **bundle 복구·완전삭제 정합 검증(INV-10·12)**: 엔진 복구 primitive가 복구 위치를 루트 부모 상태로 결정
    (부모 active면 부모 밑 sort_order 원위치, non-active/부재면 root 맨 뒤; 6.5.1/6.5.2/6.7), 완전삭제가 묶음
    단위로 원자적(INV-10)이며 다른 독립 묶음은 불변(INV-12), 상태 전이가 편집 잠금과 독립.
  - **결합 엣지케이스 검증**: `trashed_at` 초 단위(`DATETIME`) 경계에서 묶음 멤버십 경계가 오병합 없이 유지됨
    (s07 flagged Risk), 삭제(`is_deleted=true`) 처리된 사용자(L1)의 이름이 문서 작성자 표시로 보존됨(INV-4).
  - **워크스페이스 삭제 ↔ 문서 존재 경계 검증(이번 계층 신규 결합 = s05 워크스페이스 삭제 ↔ s07 문서 도메인)**:
    문서를 하나라도 보유한 워크스페이스의 삭제(`DELETE /workspaces/{id}`, 행 14)가 409로 거부되어 워크스페이스·
    문서·멤버십이 물리 보존되고(`s01` `workspace` 참조 FK `ON DELETE RESTRICT` 및 INV-4 정합), 빈 워크스페이스의
    삭제는 여전히 성공하여 삭제가 오직 빈 워크스페이스에만 허용됨.
  - **게이트·재검증 판정**: 위 검증 전부가 mock 없이 통과함을 게이트(G-1 규칙, L3→L4) 통과 조건으로 기록하고,
    재검증 트리거 대상(s01·s02·s03·s05·s07)을 명시.
- **Out of scope (이 체크포인트가 소유하지 않음)**:
  - 새로운 feature 동작·엔드포인트·서비스·스키마·마이그레이션·상태 엔진 구현(모두 s01·s02·s03·s05·s07 소유,
    이미 완료 가정).
  - 검증 중 발견된 계약 위반의 **수정** — 원인 spec(s01/s02/s03/s05/s07)에서 고쳐야 하며, 체크포인트는 회귀를
    포착·보고만 한다.
  - **후속 계층(L4 이상) 관심사**: 편집 잠금 시작/저장/취소/강제해제·버전 생성 흐름(s09), 휴지통 목록/복구/완전
    삭제 **API**·묶음 보관 타이머 자동 영구삭제(s10), 첨부(s12), 공유 링크(s14). L3은 `s07`이 소유한 상태 엔진
    primitive(복구·완전삭제·묶음 열거)의 **재사용 계약**이 라우터 밖 호출에서 불변식을 유지하는 범위까지만
    관찰하며, 휴지통 UX·타이머·잠금·버전 동작 자체는 후속 체크포인트(s11 이상)가 검증한다.
  - 개별 spec 단위 검증의 재실행(각 spec의 자체 테스트 소유). 체크포인트는 **결합·경계**만 본다.
- **Adjacent expectations (인접 spec/계약에 대한 기대)**:
  - `s01`이 `document`·`document_version` 스키마, `WorkspaceRoleResolver`/`require_ws_role`/`Role`(위계 판정·
    admin bypass), 세션 인증(`get_current_user`/`AuthContext`), 공통 에러 모델, Base Schemas, 엔드포인트
    카탈로그(행 18~23), 불변식 카탈로그(INV-1·2·3·4·5·6·10·11·12)를 단일 소스로 제공한다.
  - `s07`이 카탈로그 행 18~23(문서 생성·목록·상세·제목 수정·이동·삭제)의 동작과 `DocumentStateEngine`
    (삭제 캐스케이드·복구·완전삭제·묶음 식별)·`DocumentWsAdapter`(문서→WS 게이팅 주입)·`MarkdownRenderer`를
    구현하여 배치되어 있고, `s01`·`s05` 계약을 재정의 없이 재사용한다. 새 마이그레이션을 추가하지 않는다.
  - `s05`가 `workspace_member` 데이터를 채워 `s01` resolver를 실제 role로 동작시키고, `s02`가 로그인·세션과
    계정 상태 게이트를, `s03`가 계정 생명주기(생성·비활동·삭제·재활성화)를 구현하여 배치되어 있다.
  - `s06-integration-check-L2`의 통합 테스트 하네스(`tests/integration_L2` — L1 하네스 재사용 + 워크스페이스·
    멤버·role 세션 시나리오)가 존재하며, 이 체크포인트는 그 패턴을 **확장·재사용**한다(중복 신설 금지).

## Requirements

### Requirement 1: 검증 방법론 및 대조 기준 (mock 없는 실제 결합 · s01 단일 소스 · 누적 집합 · L2 하네스 확장)

**Objective:** As a L3 통합 체크포인트, I want 누적 upstream을 실제 구현으로 결합한 상태에서 단일 계약 소스에 대조
검증하기를, so that 문서 도메인·bundle 엔진·권한 게이팅 회귀가 상위 계층(L4 이상)으로 전파되기 전에 조기에 포착된다.

#### Acceptance Criteria

1. The L3 Integration Checkpoint shall 모든 검증을 mock·stub·가짜 구현 없이 실제 `s01`·`s02`·`s03`·`s05`·`s07`
   구현을 결합한 상태(마이그레이션 적용된 실제 DB + 실제 부팅된 애플리케이션 + 실제 서명 쿠키 세션 + 실제
   workspace_member 데이터 + 실제 `DocumentStateEngine`)에서 수행한다.
2. The L3 Integration Checkpoint shall 계약 정합의 대조 기준을 항상 `s01-contract-foundation`의 단일 소스
   (데이터 스키마·엔드포인트 카탈로그·권한 resolver 계약·공통 에러 모델·불변식 카탈로그)로 삼으며, 개별 spec
   (s02·s03·s05·s07)의 design을 기준으로 삼지 않는다.
3. The L3 Integration Checkpoint shall 어떤 feature 동작·엔드포인트·서비스·스키마·마이그레이션·상태 엔진도
   신규로 구현하지 않고 검증 및 그 테스트 자산만 산출한다.
4. The L3 Integration Checkpoint shall `s06-integration-check-L2`의 통합 테스트 하네스 패턴(마이그레이션·앱 부팅·
   admin 시드·세션 유지 클라이언트·계정 생명주기 헬퍼·워크스페이스/멤버/role 세션 시나리오 헬퍼)을 재사용·확장
   하며 동일한 하네스를 중복 신설하지 않는다.
5. If 검증 대상 시스템에 계약을 위반하는 결합 회귀가 발견되면, the L3 Integration Checkpoint shall 이를 실패로
   보고하되 원인 spec에서의 수정을 유발할 뿐 체크포인트 내부에서 feature 로직을 변경하여 우회하지 않는다.

### Requirement 2: 계약 대조 — document·document_version 스키마 · 문서 API(행 18~23) · status 전이 · 에러 모델

**Objective:** As a L3 통합 체크포인트, I want 결합된 시스템의 문서 스키마·API·status 전이·에러 형태가 `s01` 단일
소스와 일치함을 확인하기를, so that s07이 계약을 벗어난 드리프트 없이 s01·s05와 동일 기준 위에 얹혀 있음을 보장한다.

#### Acceptance Criteria

1. The L3 Integration Checkpoint shall 마이그레이션이 적용된 실제 DB의 `document` 테이블이 `s01` 물리 데이터 모델
   (`workspace_id` FK, `parent_id` 자기참조 FK, `title`, `status` ENUM(active/trashed/deleted), `sort_order`
   DECIMAL, `current_version_id` FK, `trashed_at`, `created_by` FK, 타임스탬프, 인덱스
   `(workspace_id, status, parent_id)`·`(workspace_id, status, trashed_at)`)과 컬럼·제약·ENUM·인덱스 면에서
   일치함을 확인한다.
2. The L3 Integration Checkpoint shall 마이그레이션이 적용된 실제 DB의 `document_version` 테이블이 `s01` 물리
   데이터 모델(`document_id` FK, `content`, `created_by` FK, `created_at`, INDEX(document_id, created_at))과
   일치하며, `s07`이 새 마이그레이션을 추가하지 않고 `s01` 스키마만 사용함을 확인한다.
3. The L3 Integration Checkpoint shall 부팅된 애플리케이션에 `s01` 엔드포인트 카탈로그 행 18~23(`POST`/`GET
   /workspaces/{id}/documents`, `GET`/`PATCH /documents/{id}`, `POST /documents/{id}/move`, `DELETE
   /documents/{id}`)이 카탈로그가 정한 경로·메서드·요구 role대로 노출됨을 확인한다.
4. When 결합된 시스템의 임의 문서 엔드포인트가 오류를 반환하면, the L3 Integration Checkpoint shall 응답이 `s01`
   공통 에러 응답 형태(`code`·`message`·선택적 `field_errors`)이고 상태 코드가 에러 코드 카탈로그
   (401/403/404/409/422)와 일치함을 확인한다.
5. The L3 Integration Checkpoint shall 문서 응답 본문이 `s01` Base Schemas 규약(`DocumentRead`는 `TimestampedRead`
   상속, 목록은 `Page[DocumentRead]`)을 따르고, `status` 값이 `s01` `document.status` ENUM(active/trashed/deleted)
   과 동일 값 집합임을 확인한다.
6. The L3 Integration Checkpoint shall 문서 상태가 계약이 정한 전이(active → trashed, trashed → deleted)만 취하고
   `deleted`가 종착(복원 경로 없음, INV-7)이며, 어떤 경로에서도 문서가 물리 삭제되지 않음(INV-4)을 실제 결합에서
   확인한다.

### Requirement 3: 문서 권한 게이팅 — role 위계 (INV-1·2·3, editor/viewer via require_ws_role · 문서→WS 어댑터)

**Objective:** As a L3 통합 체크포인트, I want `s01` `require_ws_role` resolver가 문서 라우트에서 `s05`가 채운 실제
멤버십 데이터 위에 editor/viewer 위계를 계약대로 판정함을 확인하기를, so that 워크스페이스 단위 권한(INV-1)과 viewer
읽기 전용(INV-2)·admin bypass(INV-3) 경계가 문서 도메인에서 성립함을 보장한다.

#### Acceptance Criteria

1. When editor 이상 멤버가 자신의 세션으로 문서·하위 문서를 생성(`POST /workspaces/{id}/documents`)·수정
   (`PATCH /documents/{id}`)·이동(`POST /documents/{id}/move`)·삭제(`DELETE /documents/{id}`)하면, the L3
   Integration Checkpoint shall 각 변경 작업이 권한 게이트 기준으로 통과함을 확인한다(editor ≥ EDITOR).
2. When viewer 멤버가 문서 생성·수정·이동·삭제 라우트에 접근하면, the L3 Integration Checkpoint shall 요청이
   403 forbidden으로 거부됨을 확인한다(INV-2 viewer 읽기 전용).
3. When owner·editor·viewer 멤버가 문서 조회(`GET /documents/{id}`)·목록(`GET /workspaces/{id}/documents`)에
   접근하면, the L3 Integration Checkpoint shall 요청이 통과(viewer 요구 게이트 충족)함을 확인한다.
4. When 어떤 워크스페이스의 멤버가 아닌 사용자가 그 워크스페이스의 문서 조회·목록 또는 문서 변경 라우트에 접근
   하면, the L3 Integration Checkpoint shall 요청이 403 forbidden으로 거부됨을 확인한다(비멤버 접근 차단, INV-1).
5. When admin이 자신이 멤버가 아닌 워크스페이스의 문서 조회·목록·생성·수정·이동·삭제 라우트에 접근하면, the L3
   Integration Checkpoint shall 접근이 성공함을 확인한다(모든 문서 게이트에서 admin bypass, INV-3).
6. The L3 Integration Checkpoint shall `/documents/{id}` 계열 라우트가 문서 id로부터 workspace_id를 추출하는
   문서→WS 어댑터를 통해 게이트되어, 존재하지 않는 문서는 404, 권한 미충족은 403으로 판정됨을 확인한다(어댑터가
   resolver 위계 비교·admin bypass를 재구현하지 않고 `s01` resolver에 위임함).

### Requirement 4: 문서 계층·이동 정합 (INV-5·6, 순환 방지 · 동일 WS 경계 · 중간 삽입 정렬)

**Objective:** As a L3 통합 체크포인트, I want 문서 이동·재정렬이 순환을 만들지 않고 워크스페이스 경계를 넘지 않음을
확인하기를, so that 계층 이동 불변식(INV-5·6)이 실제 API 결합에서 성립하고 하위 계층으로 회귀가 전파되지 않는다.

#### Acceptance Criteria

1. When editor가 같은 워크스페이스 내에서 문서를 다른 부모 밑으로 이동하거나 형제 사이(중간 삽입)로 재정렬하면,
   the L3 Integration Checkpoint shall 이동이 성공하고 이후 조회에서 새 부모·정렬 순서가 반영됨을 확인한다.
2. When editor가 문서를 자기 자신 또는 자신의 후손 문서 밑으로 이동하려 하면, the L3 Integration Checkpoint shall
   요청이 거부(409 conflict 또는 422)됨을 확인한다(INV-5 순환 방지).
3. When editor가 문서를 다른 워크스페이스의 문서 밑으로 이동하려 하면, the L3 Integration Checkpoint shall 요청이
   거부됨을 확인한다(INV-6 워크스페이스 경계 유지).
4. When editor가 두 형제 사이로 문서를 이동하면, the L3 Integration Checkpoint shall 이동 대상만 인접 형제 사이의
   `sort_order` 값을 받고 다른 형제들의 순서는 재배치되지 않음을 확인한다(중간 삽입 정렬, 6.7).
5. When editor가 존재하지 않는 부모 또는 active가 아닌 부모 밑으로 이동하려 하면, the L3 Integration Checkpoint
   shall 요청이 거부(404 또는 409)됨을 확인한다.

### Requirement 5: bundle 삭제 캐스케이드 · 비흡수 (INV-10·11, 6.2·6.4)

**Objective:** As a L3 통합 체크포인트, I want 문서 삭제가 그 시점 서브트리를 묶음으로 원자적으로 포착하되 이미 삭제된
자식을 흡수하지 않음을 확인하기를, so that 묶음 비흡수 모델(INV-10·11)이 실제 API·엔진 결합에서 성립함을 보장한다.

#### Acceptance Criteria

1. When editor가 active 하위 문서를 가진 문서를 삭제(`DELETE /documents/{id}`)하면, the L3 Integration Checkpoint
   shall 그 시점 active 하위 문서(루트 포함)만 `status=trashed`로 전환되고 모두 동일한 `trashed_at`을 부여받음을
   확인한다(삭제 캐스케이드 묶음 포착, 6.2).
2. When 자식 문서를 먼저(t1) 삭제한 뒤 부모 문서를 나중(t2)에 삭제하면, the L3 Integration Checkpoint shall 부모
   삭제가 이미 trashed된 자식을 흡수하지 않고 자식이 자기 묶음·자기 `trashed_at(t1)`을 유지하며 `child.trashed_at
   ≤ parent.trashed_at`이 성립함을 확인한다(비흡수, 6.4, INV-11).
3. When 부모의 일부 하위만 개별로 먼저 삭제된 상태에서 부모가 삭제되면, the L3 Integration Checkpoint shall 먼저
   삭제된 자식 묶음과 부모 삭제 묶음이 서로 다른 루트로 독립 식별됨을 확인한다(독립 묶음, 6.3).
4. When 문서가 삭제되어 이미 `status=trashed`이면, the L3 Integration Checkpoint shall 같은 문서에 대한 재삭제
   요청(`DELETE /documents/{id}`)이 409 conflict로 거부됨을 확인한다(active만 삭제 대상).
5. When 삭제 캐스케이드가 수행되면, the L3 Integration Checkpoint shall 포착된 묶음 구성원 전이가 단일 원자적
   조작으로 적용되고(부분 전이 없음), 삭제된 문서가 물리적으로 보존됨(INV-4·INV-10)을 실제 DB 관찰로 확인한다.

### Requirement 6: bundle 복구 · 완전삭제 정합 (INV-10·12, 6.5·6.7 · 상태/잠금 독립)

**Objective:** As a L3 통합 체크포인트, I want `s07` 상태 엔진의 복구·완전삭제 primitive가 라우터 밖 재사용 경계에서도
불변식을 유지함을 확인하기를, so that L4(s10 휴지통)이 소비할 엔진 계약이 실제 결합에서 성립함을 미리 보장한다.

#### Acceptance Criteria

1. When 부모가 active인 묶음을 엔진 복구 primitive로 복구하면, the L3 Integration Checkpoint shall 묶음 루트가
   원래 부모 밑으로 복귀하고 `sort_order`가 원위치(또는 규칙에 따른 폴백)로 복원되며 구성원이 `status=active`·
   `trashed_at=NULL`로 전환됨을 확인한다(6.5.1, 6.7.1).
2. When 부모가 non-active(trashed/deleted)이거나 부재인 묶음을 복구하면, the L3 Integration Checkpoint shall 묶음
   루트가 `parent_id=NULL`로 root 맨 뒤에 append되고 묶음 내부 상대 계층은 유지되며 자동 재중첩이 없음을 확인
   한다(6.5.2, 6.5.3, 6.7.2).
3. When 묶음을 엔진 완전삭제 primitive로 완전삭제하면, the L3 Integration Checkpoint shall 묶음 구성원 전체가
   `status=deleted`로 원자적으로 전환되고 물리 삭제 없이 보존되며(INV-4·INV-10) `deleted`가 종착(복원 불가,
   INV-7)임을 확인한다.
4. When 여러 독립 묶음 중 하나를 복구 또는 완전삭제하면, the L3 Integration Checkpoint shall 다른 독립 묶음의
   구성원·`trashed_at`·보관 기준이 변경되지 않음을 확인한다(묶음별 독립성, INV-12; 보관 기준은 각 묶음의
   `trashed_at`).
5. When 편집 잠금 필드(`lock_user_id`)가 설정된 문서를 삭제·복구·완전삭제하면, the L3 Integration Checkpoint
   shall 상태 전이가 잠금 여부와 무관하게 정상 수행되고 체크포인트가 lock 필드 값을 스스로 설정하지 않음을
   확인한다(상태/잠금 독립, §4.3).

### Requirement 7: 결합 엣지케이스 — trashed_at 묶음 경계 정밀도 · 작성자 보존 · 비어있지 않은 워크스페이스 삭제 거부 (INV-4 · FK RESTRICT)

**Objective:** As a L3 통합 체크포인트, I want `trashed_at` 초 단위 경계에서 묶음 멤버십이 오병합 없이 유지되고 삭제된
사용자의 작성자 표시가 보존되며 문서를 보유한 워크스페이스의 삭제가 거부됨을 확인하기를, so that s07 설계가 기록한
정밀도 Risk와 아래 계층 결합(INV-4·FK RESTRICT: 워크스페이스 삭제 ↔ 문서 존재 경계)이 실제 결합에서 안전함을 보장한다.

#### Acceptance Criteria

1. When 부모-자식 문서가 서로 다른 삭제 조작으로 동일 초(second)에 trashed될 수 있는 경계 시나리오를 구성하면,
   the L3 Integration Checkpoint shall 각 삭제가 자기 묶음 구성원을 삭제 시점에 결정적으로 확정하고, 재구성이
   루트+동일 `trashed_at` 연결 서브트리 기준으로 독립 묶음을 오병합 없이 식별함을 확인한다(s07 flagged 정밀도
   Risk의 묶음 멤버십 경계 검증).
2. If 초 단위 `trashed_at` 경계에서 독립 묶음이 병합되는 회귀가 관측되면, the L3 Integration Checkpoint shall 이를
   실패로 보고하고 `trashed_at` 정밀도 승격을 `s01` 계약 개정(전 체크포인트 재검증 동반) 대상으로 기록한다.
3. When 문서를 생성한 사용자(`created_by`)가 admin에 의해 삭제(`is_deleted=true`) 처리되면, the L3 Integration
   Checkpoint shall 그 문서의 작성자 정보(`created_by` 참조 및 사용자 이름)가 물리 삭제 없이 DB에 보존됨을 직접
   조회로 확인한다(작성자 표시 보존, INV-4).
4. The L3 Integration Checkpoint shall 문서 삭제·완전삭제 시나리오 전반에서 `document`·`document_version`·`user`
   레코드에 예기치 않은 물리 삭제가 발생하지 않았음을 확인한다(INV-4).
5. When owner가 문서를 하나 이상 보유한 워크스페이스의 삭제(`DELETE /workspaces/{id}`, 카탈로그 행 14)를 요청하면,
   the L3 Integration Checkpoint shall 요청이 409 conflict 공통 에러 응답으로 거부되고 그 워크스페이스·문서·멤버십이
   물리적으로 보존됨을 실제 결합에서 확인한다(`s01` `workspace` 참조 FK `ON DELETE RESTRICT` 및 INV-4 정합; s07 문서
   도메인 ↔ s05 워크스페이스 삭제 경계).
6. When owner가 문서가 없는(빈) 워크스페이스의 삭제(`DELETE /workspaces/{id}`)를 요청하면, the L3 Integration
   Checkpoint shall 요청이 성공(워크스페이스·멤버십 제거)함을 확인하여 삭제가 오직 빈 워크스페이스에 대해서만 허용되는
   경계가 실제 결합에서 성립함을 확인한다.

### Requirement 8: 게이트 G-1 판정 및 재검증 트리거 (누적, L3→L4)

**Objective:** As a 로드맵 게이트 관리자, I want L3 검증 결과가 L4 impl 착수 가부와 재검증 대상을 명확히 산출하기를,
so that L4(`s09-lock-version`, `s10-trash`) impl 착수 가부와 upstream 변경 시 재실행 범위를 예측 가능하게 통제할 수 있다.

#### Acceptance Criteria

1. When Requirement 2~7의 모든 검증이 실제 결합 상태에서 통과하면, the L3 Integration Checkpoint shall 게이트를
   통과로 판정하여 L4(`s09-lock-version`·`s10-trash`) impl 착수의 선행 조건 충족을 기록한다.
2. If Requirement 2~7 중 하나라도 실패하면, the L3 Integration Checkpoint shall 게이트를 미통과로 판정하고 L4
   impl 착수를 차단 상태로 표시한다.
3. The L3 Integration Checkpoint shall 재검증 트리거 대상을 명시한다: `s01`·`s02`·`s03`·`s05`·`s07` 중 어느
   것이 수정되어도 이 체크포인트(및 로드맵상 그 이후 모든 체크포인트 L4~L6)를 누적 집합 기준으로 재실행해야 하며,
   `s01` 수정 시에는 모든 체크포인트를 재실행해야 한다.
4. If 검증 대상 환경(마이그레이션된 MySQL 8·부팅 앱)이 미충족이면, the L3 Integration Checkpoint shall 이를
   스킵이 아니라 실패로 처리하여 미검증이 게이트 통과로 오인되지 않게 한다.
