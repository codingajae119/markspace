# Requirements Document

## Introduction

`s11-integration-check-L4`는 **계층 4(L4)의 누적 통합 검증 체크포인트**다. 이 시점까지 완성된 upstream 누적
집합(`s01-contract-foundation` ⊕ `s02-auth` ⊕ `s03-admin-account` ⊕ `s05-workspace` ⊕ `s07-document-core`
⊕ `s09-lock-version` ⊕ `s10-trash`)이 공유 계약과 정합하는지, 그리고 이번 계층에서 처음 결합되는 **경계(편집
잠금·버전 도메인 ↔ 휴지통 도메인 ↔ document-core 상태/묶음 엔진 ↔ 아래 계층 권한·계정)**가 실제 결합 상태에서
성립하는지 mock 없이 검증한다.

이 체크포인트는 **feature 로직을 구현하지 않는다.** 새 엔드포인트·서비스·스키마·마이그레이션·상태 엔진·스케줄러를
추가하지 않으며, 오직 (1) 누적 upstream의 계약·경계 정합 검증과 (2) 그 검증을 실제 구현 결합으로 실행하는
integration/e2e 테스트만 소유한다. 검증의 유일한 대조 기준은 개별 spec(s02·s03·s05·s07·s09·s10)의 design이
아니라 **`s01-contract-foundation`의 단일 소스**(데이터 스키마 · 세션/권한 resolver 계약 · 카탈로그 행 24~31 ·
공통 에러 모델 · Settings 스키마 · 불변식 카탈로그 INV-1~12)다.

L4의 검증 초점은 세 가지다. (1) **잠금↔삭제 독립(§4.3, INV-9 ↔ INV-10)**: 편집 잠금 상태와 문서 trashed/deleted
상태가 서로 간섭하지 않는지 — 잠긴 문서를 휴지통에 넣을 수 있고, trashed 문서의 잠금 필드가 상태 전이와 충돌하지
않으며, 잠금·저장·해제 동작이 문서 status를 검사하지 않는지. (2) **묶음(bundle)별 보관 타이머(INV-12)**: 보관 만료
자동 영구삭제 스윕이 각 묶음의 `trashed_at`을 기준으로 만료를 **독립 산정**하여 만료된 묶음만 실제로 영구삭제하며,
한 묶음의 처리가 다른 묶음의 보관 기준에 영향을 주지 않고, 자식이 부모보다 먼저 만료되는 케이스(6.4.1)를 수용하는지.
(3) **엔진 결합**: `s09`(잠금·버전)와 `s10`(휴지통)이 각각 `s07` `DocumentStateEngine`과 문서→WS 권한 게이팅을
**재구현하지 않고 재사용**하며, 상태 전이·묶음 규칙(INV-10·11·12)을 `s07` 엔진 단일 구현에 위임하는지.

또한 이번 계층 결합에서 추가로 확인해야 할 **조정 항목(coordination item)**이 있다: `s10`이 `s01` `Settings`에
`trash_sweep_interval_seconds` 필드를 **additive**로 추가하고 APScheduler 외부 의존성을 도입했다. 이 additive 확장이
`s01`의 Settings 계약 로딩(부팅·검증)을 깨뜨리지 않고, `default_trash_retention_days` 등 기존 필드가 그대로 로드되며,
스케줄러가 설정값(`>0` 기동 · `<=0` 미기동)대로 lifespan에 결합되는지 실제 부팅으로 확인한다.

이 체크포인트는 로드맵의 **게이트(G-1 규칙)**(각 체크포인트가 상위 계층 impl 착수의 선행 조건이 되는 게이트 규칙)을
담당한다: 이 체크포인트가 통과하기 전에는 L5(`s12-attachment`)의 impl을 착수할 수 없다. 또한 upstream
(s01·s02·s03·s05·s07·s09·s10) 중 하나라도 수정되면 이 체크포인트를 누적 집합 기준으로 재실행하는 **재검증
트리거**의 대상이다.

산출물 언어는 한국어이며, 상위 근거로 `docs/projects.md` §2.4·§2.5, §3 REQ-5·REQ-6, §4.1~4.3, §5
INV-1·2·3·4·7·9·10·11·12, `s01-contract-foundation/design.md`(§Physical Data Model document(lock 필드)·
document_version · §API Endpoint Catalog 24~31 · §Errors · §Invariants Catalog · §Settings 스키마 ·
§Common/Permissions), `s09-lock-version/design.md`(§LockVersionService·저장 트랜잭션·§4.3 잠금·삭제 독립),
`s10-trash/design.md`(§TrashService·§RetentionSweepService·§RetentionScheduler·Settings additive 확장),
`s08-integration-check-L3/design.md`(재사용·확장할 통합 테스트 하네스 패턴), `.kiro/steering/roadmap.md`
(게이트·재검증 트리거·Shared seams to watch)를 참조한다.

## Boundary Context

- **In scope (이 체크포인트가 소유)**:
  - **계약 대조 검증**: 실제 결합된 시스템의 `document`(lock 필드 `lock_user_id`·`lock_acquired_at`·
    `current_version_id`)·`document_version` 스키마, 잠금·버전·휴지통 API(`s01` 카탈로그 행 24~31), status 전이
    계약, 공통 에러 모델이 `s01` 단일 소스와 일치하는지 대조. **Settings additive 확장 조정 항목**: `s10`이 추가한
    `trash_sweep_interval_seconds`가 `s01` `Settings` 계약 로딩을 깨지 않고 기존 필드가 보존되며 APScheduler
    의존성이 부팅에 결합되는지 확인.
  - **편집 잠금·버전 흐름 검증(이번 계층 신규 경계 = 잠금/버전 도메인)**: 편집 시작→타인 편집 시작 차단(5.2)→저장
    시 새 `document_version` 생성·`current_version_id` 갱신·잠금 해제(5.3), 취소 시 미저장 변경분 폐기·잠금 해제
    (5.4), owner/admin 강제 해제(5.6), 자동 타임아웃 없음(5.5), 저장 반복 시 버전 무한 누적·rollback 없음(5.7),
    문서당 잠금 최대 1인(INV-9). 잠금·버전 라우트의 role 게이팅(editor/owner/viewer, admin bypass).
  - **휴지통 흐름 검증(이번 계층 신규 경계 = 휴지통 도메인)**: editor 이상이 워크스페이스 휴지통 전체(본인 삭제분
    외 포함)를 열람·복구·완전삭제하고 viewer는 거부(6.11, INV-2)됨. 복구 위치 규칙(6.5)이 엔진 결합에서 성립,
    완전삭제 묶음 원자성(6.9, INV-10), 휴지통 API가 `s07` 엔진 primitive를 재사용해 상태 전이를 위임함.
  - **잠금↔삭제 독립 검증(§4.3, INV-9 ↔ INV-10)**: 잠긴 문서를 trashed로 전이할 수 있고, trashed 문서의 잠금
    필드가 상태 전이와 충돌하지 않으며, 잠금·저장·취소·강제해제 동작이 문서 status를 검사하지 않고 상태 전이를
    수행하지 않음. `s10`이 lock 필드를 변경하지 않음.
  - **엔진 결합 검증**: `s09`와 `s10`이 각각 `s07` `DocumentStateEngine`·문서→WS 어댑터·`require_ws_role` 권한
    게이팅을 재구현하지 않고 재사용하며, 묶음 규칙(INV-10·11·12)을 엔진 단일 구현에 위임함.
  - **묶음 보관 타이머 자동 영구삭제 검증(6.8, INV-12)**: 보관 스윕이 각 묶음 `trashed_at`을 기준으로 만료를 독립
    산정하여 만료된 묶음만 `deleted`로 전환하고, 한 묶음 처리가 다른 묶음 기준에 영향을 주지 않으며, 자식이 부모보다
    먼저 만료되는 케이스(6.4.1)를 수용하고, 반복 실행이 멱등이며, `now` 주입으로 만료 경계가 결정적으로 검증됨.
  - **아래 계층 결합 엣지케이스 검증**: role별 잠금·휴지통 접근 경계와 admin override(INV-1·2·3)가 계정·워크스페이스
    계층 결합에서 성립, 삭제(`is_deleted=true`) 처리된 사용자가 만든 문서·버전의 작성자 표시(`created_by`)가 물리
    삭제 없이 보존됨(INV-4), 잠금·저장·휴지통·스윕 시나리오 전반에서 예기치 않은 물리 삭제 부재(INV-4).
  - **게이트·재검증 판정**: 위 검증 전부가 mock 없이 통과함을 게이트(G-1 규칙, L4→L5) 통과 조건으로 기록하고,
    재검증 트리거 대상(s01·s02·s03·s05·s07·s09·s10)을 명시.
- **Out of scope (이 체크포인트가 소유하지 않음)**:
  - 새로운 feature 동작·엔드포인트·서비스·스키마·마이그레이션·상태 엔진·스케줄러 구현(모두 s01·s02·s03·s05·s07·
    s09·s10 소유, 이미 완료 가정).
  - 검증 중 발견된 계약 위반의 **수정** — 원인 spec에서 고쳐야 하며, 체크포인트는 회귀를 포착·보고만 한다.
  - **후속 계층(L5 이상) 관심사**: 첨부·이미지·완전삭제 시 보관 폴더 이동(8.6)·저장 참조 소멸 아카이브(8.7,
    `s12`), 공유 링크·무효화(`s14`). L4는 `s09`의 "저장 = 버전 생성" 이벤트와 `s10`의 "완전삭제 = deleted 전이"
    결과가 성립하는 범위까지만 관찰하고, 첨부 아카이브·공유 무효화 동작 자체는 후속 체크포인트(s13 이상)가 검증한다.
  - 개별 spec 단위 검증의 재실행(각 spec의 자체 테스트 소유). 체크포인트는 **결합·경계**만 본다.
- **Adjacent expectations (인접 spec/계약에 대한 기대)**:
  - `s01`이 `document`(lock 필드 포함)·`document_version` 스키마, `WorkspaceRoleResolver`/`require_ws_role`/
    `Role`(위계 판정·admin bypass), 세션 인증(`get_current_user`/`AuthContext`), 공통 에러 모델, Base Schemas,
    엔드포인트 카탈로그(행 24~31), `Settings` 스키마(`default_trash_retention_days` 포함), 불변식 카탈로그
    (INV-1·2·3·4·7·9·10·11·12)를 단일 소스로 제공한다.
  - `s07`이 `DocumentStateEngine`(삭제 캐스케이드·복구·완전삭제·묶음 식별)·`DocumentWsAdapter`(문서→WS 게이팅)를
    구현하여 배치되어 있고, `s09`/`s10`은 이를 재정의 없이 재사용한다.
  - `s09`가 카탈로그 행 24~28(잠금 시작·저장·취소·강제해제·버전 목록)의 동작과 저장 원자 트랜잭션을 구현하여
    배치되어 있고, 새 마이그레이션을 추가하지 않으며 잠금·버전 동작이 문서 status와 독립(§4.3)이다.
  - `s10`이 카탈로그 행 29~31(휴지통 목록·복구·완전삭제)의 동작과 `RetentionSweepService`·`RetentionScheduler`를
    구현하여 배치되어 있고, 상태 전이를 `s07` 엔진에 위임하며, `s01` `Settings`에 `trash_sweep_interval_seconds`를
    additive로 확장하고 APScheduler를 `uv add`로 추가하되 새 DB 마이그레이션은 추가하지 않는다.
  - `s08-integration-check-L3`의 통합 테스트 하네스(`tests/integration_L3` — L2/L1 하네스 재사용 + 문서 트리·
    엔진 세션 시나리오)가 존재하며, 이 체크포인트는 그 패턴을 **확장·재사용**한다(중복 신설 금지).

## Requirements

### Requirement 1: 검증 방법론 및 대조 기준 (mock 없는 실제 결합 · s01 단일 소스 · 누적 집합 · L3 하네스 확장)

**Objective:** As a L4 통합 체크포인트, I want 누적 upstream을 실제 구현으로 결합한 상태에서 단일 계약 소스에 대조
검증하기를, so that 잠금·버전·휴지통 도메인과 엔진 결합·잠금↔삭제 독립·묶음 타이머 회귀가 상위 계층(L5 이상)으로
전파되기 전에 조기에 포착된다.

#### Acceptance Criteria

1. The L4 Integration Checkpoint shall 모든 검증을 mock·stub·가짜 구현 없이 실제 `s01`·`s02`·`s03`·`s05`·`s07`·
   `s09`·`s10` 구현을 결합한 상태(마이그레이션 적용된 실제 DB + 실제 부팅된 애플리케이션 + 실제 서명 쿠키 세션 +
   실제 workspace_member 데이터 + 실제 `DocumentStateEngine` + 실제 `RetentionSweepService`)에서 수행한다.
2. The L4 Integration Checkpoint shall 계약 정합의 대조 기준을 항상 `s01-contract-foundation`의 단일 소스
   (데이터 스키마·엔드포인트 카탈로그·권한 resolver 계약·공통 에러 모델·Settings 스키마·불변식 카탈로그)로 삼으며,
   개별 spec(s02·s03·s05·s07·s09·s10)의 design을 기준으로 삼지 않는다.
3. The L4 Integration Checkpoint shall 어떤 feature 동작·엔드포인트·서비스·스키마·마이그레이션·상태 엔진·스케줄러도
   신규로 구현하지 않고 검증 및 그 테스트 자산만 산출한다.
4. The L4 Integration Checkpoint shall `s08-integration-check-L3`의 통합 테스트 하네스 패턴(마이그레이션·앱 부팅·
   admin 시드·세션 유지 클라이언트·워크스페이스/멤버/role 세션 시나리오 헬퍼·문서 트리 구성·엔진 세션 접근 픽스처)을
   재사용·확장하며 동일한 하네스를 중복 신설하지 않는다.
5. If 검증 대상 시스템에 계약을 위반하는 결합 회귀가 발견되면, the L4 Integration Checkpoint shall 이를 실패로
   보고하되 원인 spec에서의 수정을 유발할 뿐 체크포인트 내부에서 feature 로직을 변경하여 우회하지 않는다.

### Requirement 2: 계약 대조 — lock 필드·document_version·휴지통 스키마 · 카탈로그(행 24~31) · Settings additive 확장 · 에러 모델

**Objective:** As a L4 통합 체크포인트, I want 결합된 시스템의 잠금·버전·휴지통 스키마·API·Settings 확장·에러 형태가
`s01` 단일 소스와 일치함을 확인하기를, so that s09·s10이 계약을 벗어난 드리프트 없이 s01 위에 얹혀 있고 additive
Settings 확장이 기존 계약을 깨지 않음을 보장한다.

#### Acceptance Criteria

1. The L4 Integration Checkpoint shall 마이그레이션이 적용된 실제 DB의 `document` 테이블 lock 관련 컬럼
   (`lock_user_id BIGINT FK NULL`, `lock_acquired_at DATETIME NULL`, `current_version_id BIGINT FK NULL`)과
   `document_version` 테이블(`document_id` FK, `content`, `created_by` FK, `created_at`, INDEX(document_id,
   created_at))이 `s01` 물리 데이터 모델과 컬럼·제약·인덱스 면에서 일치하고, `s09`·`s10`이 새 DB 마이그레이션을
   추가하지 않았음을 확인한다.
2. The L4 Integration Checkpoint shall 부팅된 애플리케이션에 `s01` 엔드포인트 카탈로그 행 24~31(`POST
   /documents/{id}/lock`, `POST /documents/{id}/save`, `POST /documents/{id}/cancel`, `POST
   /documents/{id}/force-unlock`, `GET /documents/{id}/versions`, `GET /workspaces/{id}/trash`, `POST
   /trash/{bundleId}/restore`, `DELETE /trash/{bundleId}`)이 카탈로그가 정한 경로·메서드·요구 role대로 노출됨을
   확인한다.
3. When 결합된 시스템의 임의 잠금·버전·휴지통 엔드포인트가 오류를 반환하면, the L4 Integration Checkpoint shall
   응답이 `s01` 공통 에러 응답 형태(`code`·`message`·선택적 `field_errors`)이고 상태 코드가 에러 코드 카탈로그
   (401/403/404/409/422)와 일치함을 확인한다.
4. The L4 Integration Checkpoint shall 잠금·버전·휴지통 응답 본문이 `s01` Base Schemas 규약(`DocumentLockRead`·
   `DocumentVersionRead`·`TrashBundleRead`가 `ORMReadModel`/`TimestampedRead` 상속, 목록은 `Page[T]`)을 따르고,
   `DocumentVersionRead`에 본문 필드가 없음(rollback·과거 본문 미제공)을 확인한다.
5. The L4 Integration Checkpoint shall `s10`이 `s01` `Settings`에 additive로 추가한 `trash_sweep_interval_seconds`
   필드가 존재하는 실제 결합 부팅에서 `s01` `Settings` 계약 로딩이 정상 성공하고(부팅 실패 없음), 기존 필드
   (`default_trash_retention_days` 등)가 보존되며, 설정 접근이 여전히 단일 `Settings`/`get_settings` 경유임을
   확인한다(모듈별 설정 파일·`os.environ` 직접 접근 부재).
6. The L4 Integration Checkpoint shall APScheduler 의존성이 부팅에 결합된 상태에서 `s01` `create_app()`이 정상
   부팅되고, `trash_sweep_interval_seconds`가 `>0`이면 스케줄러가 기동·`<=0`이면 미기동되며, 이 결합이 기존 앱
   부팅 계약을 회귀시키지 않음을 확인한다.

### Requirement 3: 편집 잠금·버전 흐름 결합 (5.2·5.3·5.4·5.5·5.6·5.7, INV-9 · 권한 게이팅)

**Objective:** As a L4 통합 체크포인트, I want 편집 잠금 생명주기와 저장 시 버전 생성이 실제 API·엔진 결합에서
계약대로 동작하고 role별로 게이팅됨을 확인하기를, so that 잠금·버전 도메인(s09)이 s01 계약·s05 권한·s07 어댑터 위에서
불변식(INV-9)을 유지함을 보장한다.

#### Acceptance Criteria

1. When editor A가 `POST /documents/{id}/lock`으로 편집을 시작한 뒤 editor B가 같은 문서에 `POST
   /documents/{id}/lock`을 요청하면, the L4 Integration Checkpoint shall B의 요청이 409 conflict("편집 중")로
   거부되고 문서당 잠금 보유자가 최대 1인(INV-9)임을 확인한다(5.2).
2. When 잠금 보유자 A가 `POST /documents/{id}/save`(content)로 저장하면, the L4 Integration Checkpoint shall 새
   `document_version`이 생성되고 `document.current_version_id`가 갱신되며 잠금이 해제되어 이후 B가 `POST
   /documents/{id}/lock`에 성공함을 확인한다(5.3, 저장=버전 생성+잠금 해제의 원자 결과).
3. When 잠금 보유자 A가 `POST /documents/{id}/cancel`로 편집을 취소하면, the L4 Integration Checkpoint shall 잠금이
   해제되고 새 버전이 생성되지 않아(미저장 변경분 폐기) 버전 목록이 증가하지 않음을 확인한다(5.4).
4. When owner 또는 admin이 A가 잠근 문서에 `POST /documents/{id}/force-unlock`을 요청하면, the L4 Integration
   Checkpoint shall 보유자와 무관하게 잠금이 해제되고 새 버전이 생성되지 않으며, editor(비 owner)의 force-unlock은
   403으로 거부됨을 확인한다(5.6, owner/admin 강제 해제).
5. The L4 Integration Checkpoint shall 잠금에 자동 타임아웃이 없어, 시간 경과만으로는 잠금이 해제되지 않고 명시적
   저장·취소·강제해제로만 해제됨을 확인한다(5.5, 타임아웃 없음).
6. When A가 같은 문서를 여러 번 `POST /documents/{id}/save`로 저장하면, the L4 Integration Checkpoint shall 저장할
   때마다 새 `document_version`이 누적(무한 보관)되고 기존 버전이 삭제·수정되지 않으며 `GET
   /documents/{id}/versions`가 최신 저장 순 메타데이터를 반환하고 rollback(과거 버전 복원)·과거 본문 조회 경로가
   존재하지 않음을 확인한다(5.7).
7. The L4 Integration Checkpoint shall `s05`가 채운 멤버십 데이터 위에서 잠금·버전 라우트가 게이팅됨을 확인한다:
   lock/save/cancel은 `require_ws_role(EDITOR)`(viewer 403, 비멤버 403), force-unlock은 `require_ws_role(OWNER)`
   (editor 403), versions는 `require_ws_role(VIEWER)`(비멤버 403)이며 admin은 비멤버 WS에서도 모두 bypass하고,
   `/documents/{id}/*`가 `s07` 문서→WS 어댑터로 게이트되어 미존재 문서는 404임을 확인한다(INV-1·2·3).

### Requirement 4: 휴지통 흐름 결합 (6.5·6.9·6.11, INV-2·10 · 엔진 위임 · 권한 게이팅)

**Objective:** As a L4 통합 체크포인트, I want 휴지통 목록·복구·완전삭제 API가 s07 엔진 primitive를 재사용해
계약대로 동작하고 role별로 게이팅됨을 확인하기를, so that 휴지통 도메인(s10)이 상태 전이를 재구현하지 않고 엔진에
위임하며 복구 위치·완전삭제 원자성 불변식이 실제 결합에서 성립함을 보장한다.

#### Acceptance Criteria

1. When editor가 삭제된 묶음이 있는 워크스페이스에서 `GET /workspaces/{id}/trash`를 호출하면, the L4 Integration
   Checkpoint shall 응답이 `Page[TrashBundleRead]`로 trashed 묶음(본인 삭제분 외 워크스페이스 전체 포함)만을
   반환하고 각 묶음에 `expires_at`(= `trashed_at` + 워크스페이스 `trash_retention_days`)이 포함됨을 확인한다
   (6.11 editor+ WS 전체 열람).
2. When editor가 `POST /trash/{bundleId}/restore`로 묶음을 복구하면, the L4 Integration Checkpoint shall 복구가
   `s07` 엔진 `restore_bundle` 위임으로 수행되어 묶음 구성원이 active·`trashed_at=NULL`이 되고, 복구 위치가 복구
   시점 루트 부모 상태로 결정(부모 active면 부모 밑, non-active/부재면 root 맨 뒤)되며(6.5), 복구된 묶음이 휴지통
   목록에서 사라짐을 확인한다.
3. When editor가 `DELETE /trash/{bundleId}`로 묶음을 완전삭제하면, the L4 Integration Checkpoint shall 완전삭제가
   `s07` 엔진 `purge_bundle` 위임으로 수행되어 묶음 구성원 전체가 원자적으로 `status=deleted`(종착, INV-7)로
   전환되고 물리 삭제 없이 보존되며(6.9, INV-10·4) 요청 묶음에만 적용되어 다른 묶음이 불변임을 확인한다.
4. When viewer 또는 비멤버가 `GET /workspaces/{id}/trash`·`POST /trash/{bundleId}/restore`·`DELETE
   /trash/{bundleId}`에 접근하면, the L4 Integration Checkpoint shall 요청이 403 forbidden으로 거부되고(6.11,
   INV-1·2), admin은 자신이 멤버가 아닌 워크스페이스의 휴지통에도 모두 접근 성공(INV-3)함을 확인한다.
5. When 존재하지 않는 묶음 id(문서 부재)로 복구·완전삭제를 요청하면 게이트 단계에서 404가, 존재하나 유효한 trashed
   묶음 루트가 아닌 id로 요청하면 엔진 단계에서 404가 반환됨을, the L4 Integration Checkpoint shall 확인한다
   (묶음→WS 어댑터·엔진 위임 경계).

### Requirement 5: 잠금↔삭제 독립 및 엔진 결합 (§4.3, INV-9 ↔ INV-10 · s09/s10의 s07 엔진·게이팅 재사용)

**Objective:** As a L4 통합 체크포인트, I want 편집 잠금 상태와 문서 삭제 상태가 서로 간섭하지 않고 s09·s10이 s07
엔진과 권한 게이팅을 재사용함을 확인하기를, so that 잠금·삭제 독립(§4.3)과 엔진 단일 구현 재사용 경계가 실제 결합에서
성립함을 보장한다.

#### Acceptance Criteria

1. When 잠금 보유자가 있는(잠긴) 문서를 `DELETE /documents/{id}`로 삭제(trashed 전이)하면, the L4 Integration
   Checkpoint shall 상태 전이가 잠금 여부와 무관하게 정상 수행되고 문서의 잠금 필드(`lock_user_id`)가 상태 전이로
   인해 변경되지 않음을 확인한다(잠긴 문서 trashed 가능, §4.3).
2. When 문서가 trashed 상태일 때 잠금·저장·취소·강제해제·버전 목록 동작을 수행하면, the L4 Integration Checkpoint
   shall 각 동작이 문서 `status`를 검사하지 않고 잠금 필드/버전 append에만 작용하며 상태 전이를 유발하지 않음을
   확인한다(trashed 문서의 잠금 상태 충돌 없음, §4.3, `s09`는 상태 전이 미수행).
3. When 묶음 복구·완전삭제·보관 스윕이 수행되면, the L4 Integration Checkpoint shall `s10`이 문서 `status`/
   `trashed_at`을 직접 갱신하지 않고 `s07` 엔진 primitive(`restore_bundle`·`purge_bundle`·`identify_bundles`)에
   위임하며 lock 필드를 변경하지 않음을 확인한다(상태 전이 전면 위임, 잠금 독립).
4. The L4 Integration Checkpoint shall `s09` 잠금·버전 라우트와 `s10` 휴지통 라우트가 권한 판정을 재구현하지 않고
   `s01` `require_ws_role` resolver와 `s07` 문서→WS(묶음→WS) 어댑터를 재사용함을 실제 결합 게이팅 관찰로 확인한다
   (권한 검사 공통 레이어 단일 구현, INV-1).
5. When 잠긴 상태로 trashed된 문서를 완전삭제(`purge_bundle`)하거나 복구(`restore_bundle`)하면, the L4 Integration
   Checkpoint shall 상태 전이가 잠금 필드 유무와 무관하게 정상 수행됨을 확인한다(§4.3, 상태/잠금 독립의 완전삭제·
   복구 경로 확인).

### Requirement 6: 묶음 보관 타이머 자동 영구삭제 독립성 (6.8·6.4.1, INV-12 · 멱등 · Settings 주기)

**Objective:** As a L4 통합 체크포인트, I want 보관 만료 자동 영구삭제 스윕이 묶음별 독립 타이머로 만료된 묶음만
실제로 영구삭제함을 확인하기를, so that 묶음 보관 만료가 각 `trashed_at` 기준 독립 산정된다는 불변식(INV-12)이 실제
결합에서 성립함을 보장한다.

#### Acceptance Criteria

1. When 서로 다른 `trashed_at`을 가진 여러 묶음이 있는 상태에서 보관 스윕(`sweep_expired_bundles`/`run_sweep`)을
   주입된 `now`로 실행하면, the L4 Integration Checkpoint shall `trashed_at + trash_retention_days <= now`인 묶음만
   `status=deleted`로 전환되고 아직 만료되지 않은 묶음은 불변임을 확인한다(6.8 만료 자동 영구삭제).
2. When 한 워크스페이스에 여러 독립 묶음이 있고 그중 일부만 만료되면, the L4 Integration Checkpoint shall 만료된
   묶음의 영구삭제가 다른(미만료) 묶음의 구성원·`trashed_at`·보관 기준에 영향을 주지 않음을 확인한다(묶음별 독립
   타이머, INV-12).
3. When 부모 묶음과 자식 묶음이 서로 다른 `trashed_at`(자식이 먼저 삭제되어 더 이른 만료)을 가지면, the L4
   Integration Checkpoint shall 자식 묶음이 부모 묶음보다 먼저 만료되어 독립적으로 영구삭제되는 케이스가 허용됨을
   확인한다(6.4.1 자식이 부모보다 먼저 만료 수용).
4. When 이미 `deleted`이거나 복구된 묶음을 포함해 스윕을 반복 실행하면, the L4 Integration Checkpoint shall 이미
   처리된 묶음이 오류 없이 건너뛰어지고(멱등) 반복 실행이 중복 전이나 예외 전파를 일으키지 않음을 확인한다.
5. When 스윕이 여러 워크스페이스에 걸쳐 실행되면, the L4 Integration Checkpoint shall 각 워크스페이스의 보관일
   (`trash_retention_days`)이 그 워크스페이스 묶음 만료 산정에만 적용되고 다른 워크스페이스의 미만료 묶음은 불변임을
   확인한다(워크스페이스 스코프 독립).
6. The L4 Integration Checkpoint shall 스윕이 실제로 만료 묶음을 영구삭제한 결과를 DB 관찰(구성원 `status=deleted`·
   물리 삭제 부재)로 확인하고, 스윕이 묶음 경계를 재구성하지 않고 `s07` 엔진 `identify_bundles`·`purge_bundle`에만
   의존함을 확인한다(INV-12·엔진 위임).

### Requirement 7: 아래 계층 결합 엣지케이스 — 권한/계정 결합 · 작성자 보존 (INV-1·2·3·4)

**Objective:** As a L4 통합 체크포인트, I want role별 잠금·휴지통 접근 경계와 admin override, 삭제된 사용자의 작성자
표시 보존이 계정·워크스페이스 계층 결합에서 성립함을 확인하기를, so that 아래 계층(auth·admin·workspace)과 잠금·
휴지통 도메인의 결합이 실제 결합에서 안전함을 보장한다.

#### Acceptance Criteria

1. The L4 Integration Checkpoint shall role별 세션(owner/editor/viewer/비멤버/admin)으로 잠금·버전·휴지통 라우트
   접근 경계를 관찰하여 viewer의 잠금·저장·취소·강제해제·휴지통 변경 거부(INV-2), 비멤버 차단(INV-1), admin의 비멤버
   WS 전면 접근(INV-3)이 아래 계층 결합에서 성립함을 확인한다.
2. When 문서·버전을 생성한 사용자(`created_by`)가 admin에 의해 삭제(`is_deleted=true`) 처리되면, the L4 Integration
   Checkpoint shall 그 문서·`document_version`의 작성자 정보(`created_by` 참조 및 사용자 이름)가 물리 삭제 없이 DB에
   보존되고, 삭제된 사용자가 잠금·저장 등 후속 요청 시 로그인 게이트(401)로 차단됨을 확인한다(INV-4, 계정 생명주기 결합).
3. The L4 Integration Checkpoint shall 잠금·저장·취소·강제해제·복구·완전삭제·보관 스윕 시나리오 전반에서
   `document`·`document_version`·`user` 레코드에 예기치 않은 물리 삭제가 발생하지 않았음을 확인한다(INV-4, 물리
   삭제 부재).

### Requirement 8: 게이트 G-1 판정 및 재검증 트리거 (누적, L4→L5)

**Objective:** As a 로드맵 게이트 관리자, I want L4 검증 결과가 L5 impl 착수 가부와 재검증 대상을 명확히 산출하기를,
so that L5(`s12-attachment`) impl 착수 가부와 upstream 변경 시 재실행 범위를 예측 가능하게 통제할 수 있다.

#### Acceptance Criteria

1. When Requirement 2~7의 모든 검증이 실제 결합 상태에서 통과하면, the L4 Integration Checkpoint shall 게이트를
   통과로 판정하여 L5(`s12-attachment`) impl 착수의 선행 조건 충족을 기록한다.
2. If Requirement 2~7 중 하나라도 실패하면, the L4 Integration Checkpoint shall 게이트를 미통과로 판정하고 L5
   impl 착수를 차단 상태로 표시한다.
3. The L4 Integration Checkpoint shall 재검증 트리거 대상을 명시한다: `s01`·`s02`·`s03`·`s05`·`s07`·`s09`·`s10`
   중 어느 것이 수정되어도 이 체크포인트(및 로드맵상 그 이후 모든 체크포인트 L5~L6)를 누적 집합 기준으로 재실행해야
   하며, `s01` 수정 시에는 모든 체크포인트를 재실행해야 한다.
4. If 검증 대상 환경(마이그레이션된 MySQL 8·부팅 앱·APScheduler 결합)이 미충족이면, the L4 Integration Checkpoint
   shall 이를 스킵이 아니라 실패로 처리하여 미검증이 게이트 통과로 오인되지 않게 한다.
