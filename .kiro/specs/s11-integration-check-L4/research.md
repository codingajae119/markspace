# Research & Design Decisions — s11-integration-check-L4

---
**Purpose**: L4 누적 통합 검증 체크포인트의 검증 전략·하네스 재사용 결정·잠금↔삭제 독립 검증 방안·묶음 보관 타이머
독립성 검증 방안·Settings additive 조정 항목 확인 방안·엔진/스윕 재사용 경계를 기록한다.
---

## Summary
- **Feature**: `s11-integration-check-L4`
- **Discovery Scope**: Extension (기존 `s08-integration-check-L3` 하네스 패턴 확장 + 잠금·버전·휴지통 도메인·엔진/스윕
  실제 결합 관찰)
- **Key Findings**:
  - L4의 신규 경계는 **편집 잠금·버전 도메인(s09)**과 **휴지통 도메인(s10)**이다. 두 spec 모두 `s07`
    `DocumentStateEngine`과 문서→WS 권한 게이팅을 **재사용**하고 상태 전이·묶음 규칙을 재구현하지 않는다. 따라서
    L4 검증의 핵심은 (1) 잠금↔삭제 독립(§4.3), (2) 묶음 보관 타이머 독립성(INV-12), (3) s09·s10의 s07 엔진·게이팅
    재사용 정합이다.
  - 대조 기준은 `s01` 단일 소스다: `document` lock 필드(`lock_user_id`·`lock_acquired_at`·`current_version_id`)·
    `document_version` 물리 모델, 카탈로그 행 24~31, 에러 카탈로그, `Settings` 스키마(`default_trash_retention_days`),
    INV-1·2·3·4·7·9·10·11·12, `Common/Permissions`의 `Role` 위계·admin bypass.
  - **s10의 Settings additive 조정 항목**: `s10/design.md`는 `s01` `Settings`에 `trash_sweep_interval_seconds`
    (기본 3600)를 additive로 추가하고 `config.yml`에 값을 추가하며 APScheduler를 `uv add`로 도입한다. 사용자 지시에
    따라 L4는 이 additive 확장이 `s01` Settings 계약 로딩(부팅·검증)을 깨지 않고 기존 필드가 보존되며 스케줄러가
    설정값대로(`>0` 기동 · `<=0` 미기동) 결합되는지 실제 부팅으로 확인한다.
  - **잠금 상태는 `POST /lock`으로 설정**한다. L3에서는 복구/완전삭제 API가 없어 엔진 primitive를 직접 호출했지만,
    L4에서는 s09의 잠금 라우트와 s10의 휴지통 라우트가 실제로 존재하므로 잠금·삭제 독립을 **실제 API 왕복**으로 검증할
    수 있다(엔진 primitive 직접 호출은 스윕·묶음 관찰 보조 수단으로만 사용).
  - **보관 스윕은 `now` 주입 직접 호출**로 검증한다. `s10/design.md`는 `sweep_expired_bundles(db, now)`가 `now`를
    인자로 받아 테스트 결정성을 확보한다고 명시했다. L4는 APScheduler job의 실시간 대기를 피하고 `run_sweep`/
    `sweep_expired_bundles`를 `now` 주입으로 직접 호출해 만료 경계를 결정적으로 검증한다(스케줄러 기동/미기동은 부팅
    스모크로만 관찰).
  - `s08`의 하네스(L2/L1 재사용 + 문서 트리·엔진 세션 시나리오)는 그대로 확장 가능하다. 사용자 지시("extend its
    integration test harness — reuse, don't duplicate")에 따라 이를 재사용하고 잠금·휴지통·스윕 호출 헬퍼와 두
    editor(A·B) 세션·스윕(`now` 주입) 픽스처만 추가한다.

## Research Log

### 잠금↔삭제 독립(§4.3, INV-9 ↔ INV-10) 결합 검증 경계
- **Context**: brief의 핵심 초점 "잠금↔삭제 독립(lock state and trash/delete state must not interfere)".
- **Sources Consulted**: `s09/design.md` §Overview·§System Flows(잠금 생명주기)·§4.3(모든 동작은 문서 `status`를
  검사하지 않음)·REQ-6(잠금·삭제 독립), `s07/design.md` §DocumentStateEngine(상태 전이는 lock 필드와 독립),
  `s10/design.md`(상태 전이 전면 위임·lock 필드 미변경), `s01/design.md` INV-9·INV-10, `docs` §4.3.
- **Findings**:
  - `s09`는 잠금 판정 근거를 `lock_user_id` 단일 컬럼으로만 삼고, 잠금·저장·취소·강제해제 어느 동작도 문서
    `status`를 검사하거나 변경하지 않는다(§4.3). 즉 trashed 문서도 잠금·저장·해제가 정상 동작한다.
  - `s07` 상태 전이 엔진(`trash_document`·`restore_bundle`·`purge_bundle`)은 lock 필드를 읽거나 변경하지 않는다
    (상태/잠금 독립, L3에서 이미 엔진 관점 확인).
  - `s10`은 상태 전이를 전면 엔진 위임하고 어디에도 `status`/`trashed_at`/lock 직접 갱신을 두지 않는다.
  - 따라서 잠긴 문서를 trashed로 전이할 수 있고(lock 필드 불변), trashed 문서의 잠금 동작이 상태를 건드리지 않으며,
    복구/완전삭제가 lock 유무와 무관하게 정상 전이한다.
- **Implications**: L4는 (1) `POST /lock`으로 잠근 문서를 `DELETE /documents/{id}`로 trashed 시켜 lock 필드 불변을
  DB 관찰, (2) trashed 상태에서 `POST /lock`·`/save`·`/cancel`이 status 무검사로 동작함을 관찰, (3) 잠긴 상태로
  trashed된 문서를 `purge_bundle`/`restore_bundle`로 전이해 lock 유무와 무관한 정상 전이를 관찰한다. 실제 API/엔진
  결합, mock 없음.

### 묶음 보관 타이머 독립성(INV-12, 6.8, 6.4.1) 검증 — now 주입 직접 호출
- **Context**: brief의 핵심 초점 "묶음(bundle) 보관 타이머(per-bundle retention auto-purge via engine identity)"와
  사용자 지시 "Verify the trash retention sweep actually purges expired bundles independently (INV-12)".
- **Sources Consulted**: `s10/design.md` §RetentionSweepService(`sweep_expired_bundles(db, now)`·묶음별 독립 산정·
  멱등)·§보관 만료 자동 영구삭제 스윕 흐름·§RetentionScheduler(`run_sweep`·`now` 1회 산정 주입), `s07/design.md`
  §DocumentStateEngine(`identify_bundles`·`purge_bundle`), `s01/design.md` INV-12·`workspace.trash_retention_days`,
  `docs` §6.8·§6.4.1·INV-12.
- **Findings**:
  - 스윕은 워크스페이스별로 엔진 `identify_bundles`를 호출해 **묶음별로** 만료를 독립 산정한다(`trashed_at +
    retention_days <= now`). 만료 판정은 각 묶음 `trashed_at` 기준이며 다른 묶음 처리가 그 기준을 바꾸지 않는다(INV-12).
  - 자식/부모 묶음이 서로 다른 `trashed_at`이면 각자 만료(통상 자식 먼저) — 6.4.1 허용. `s10`은 이를 명시적으로
    수용한다.
  - `now`는 스윕 진입점에서 1회 산정해 **주입 가능**하다. 이미 deleted/복구되어 `identify_bundles`에 없거나
    `purge_bundle`이 안전 처리하는 묶음은 오류 없이 skip(멱등).
  - "actually purges" 확인: 만료 묶음 구성원 `status=deleted` 전환을 DB로 직접 관찰해야 한다(스윕 반환값만으로는
    불충분).
- **Implications**: L4는 서로 다른 `trashed_at` 묶음(자식 선삭제 포함)과 알려진 `trash_retention_days`를 구성하고
  `sweep_expired_bundles(db, now)`(또는 `run_sweep`)를 `now` 주입으로 호출해: 만료분만 `deleted` 전환(DB 관찰)·
  미만료/타 워크스페이스 묶음 불변·자식 선만료 수용·반복 실행 멱등·워크스페이스 스코프 독립을 검증한다. 스케줄러 job
  실시간 대기는 하지 않는다(비결정성 회피).

### s10 Settings additive 확장 · APScheduler 결합 조정 항목
- **Context**: 사용자 지시 "s10 added a `trash_sweep_interval_seconds` field to s01's Settings and an APScheduler
  dependency — confirm this additive extension does not break s01's Settings contract loading".
- **Sources Consulted**: `s10/design.md` §Modified Files(`config.yml`·`app/config.py` additive·`pyproject.toml`
  APScheduler)·§Technology Stack(Config·Scheduler)·§RetentionScheduler(`>0` 기동·`<=0` 미기동), `s01/design.md`
  §Settings(pydantic-settings BaseSettings, `default_trash_retention_days` 등)·§Bootstrap.
- **Findings**:
  - `s10`은 `s01` `Settings`에 `trash_sweep_interval_seconds: int = 3600`을 additive로 추가하고 `config.yml`에 값을
    넣는다. pydantic-settings는 새 필드 추가가 기존 필드 로딩을 깨지 않으며(추가 필드는 독립), `extra="ignore"`
    설정도 있어 유연하다.
  - APScheduler는 `uv add`로 도입되며 `RetentionScheduler.start(app)`가 lifespan에서 `trash_sweep_interval_seconds`
    `>0`이면 `BackgroundScheduler`를 기동, `<=0`이면 미기동한다. 새 DB 마이그레이션은 없다.
  - 조정 항목의 위험은 (a) additive 필드가 실수로 필수화되어 기존 `config.yml`/`.env`로 부팅 실패, (b) 모듈별 설정
    파일·`os.environ` 직접 접근이 도입되어 단일화 원칙 위반, (c) 스케줄러 기동이 부팅 계약을 회귀시키는 경우다.
- **Implications**: L4 계약 스위트는 실제 결합 부팅에서 `Settings`/`get_settings` 로딩 성공·기존 필드 보존·단일
  접근자 유지·APScheduler 결합 부팅 회귀 부재·`>0`/`<=0` 분기를 관찰한다. 회귀 관측 시 원인 spec(s10/s01)에서 수정.

### s09·s10의 s07 엔진·권한 게이팅 재사용 정합
- **Context**: brief의 초점 "엔진 결합(s09/s10 both correctly reuse s07's DocumentStateEngine and permission gating)".
- **Sources Consulted**: `s09/design.md` §Architecture(문서→WS 어댑터·resolver 재사용·상태 전이 미수행),
  `s10/design.md` §Architecture(상태 전이 전면 위임·묶음→WS 어댑터·resolver 재사용), `s07/design.md`
  §DocumentStateEngine·§DocumentWsAdapter, `s01/design.md` §Common/Permissions.
- **Findings**:
  - `s09`는 문서→WS 어댑터(`ws_role_for_document`)와 `require_ws_role`를 재사용하고 상태 전이를 수행하지 않는다
    (lock 필드·`document_version`만 쓴다).
  - `s10`은 묶음→WS 어댑터(`ws_role_for_bundle`, 내부적으로 s07 `DocumentRepository.get_workspace_id` 재사용)와
    `require_ws_role`를 재사용하고 상태 전이를 엔진에 위임한다.
  - 두 spec 모두 권한 위계 비교·admin bypass를 재구현하지 않고 `s01` resolver에 위임한다.
- **Implications**: L4는 잠금·버전·휴지통 라우트의 role 게이팅 매트릭스(editor/viewer/owner/비멤버/admin)가 문서
  도메인(L3)에서 관찰된 것과 동일 규칙으로 판정됨을 확인하고, s10 서비스가 status/trashed_at을 직접 갱신하지 않고
  엔진 위임함을 상태 관찰로 확인한다. 판정 로직은 s01, 데이터는 s05, 매핑은 s07.

### 작성자 표시 보존 — 삭제된 사용자(L1) ↔ 문서·버전 도메인 결합
- **Context**: brief의 누적 대상에 auth·admin 포함. 잠금·버전은 `document_version.created_by`로 작성자 결합이 확장됨.
- **Sources Consulted**: `s01/design.md` document(`created_by`)·document_version(`created_by`)·user(`is_deleted`·
  `name`, 물리 삭제 없음), `s09/design.md`(`document_version` created_by), `docs` INV-4.
- **Findings**:
  - `document.created_by`·`document_version.created_by`는 모두 `user(id)` FK다. INV-4로 user는 물리 삭제되지 않으므로
    dangling FK가 발생하지 않고 작성자 이름이 보존된다.
  - 삭제된 사용자는 로그인만 거부(s02 게이트)되고 그가 만든 문서·버전·이름은 DB에 남는다.
- **Implications**: L4는 문서·버전 작성자를 admin이 삭제 처리한 뒤 `created_by` 참조·이름 보존을 직접 조회로 확인하고,
  삭제 사용자의 잠금·저장 후속 요청이 401로 차단됨을 관찰한다(계정 생명주기 L1 ↔ 잠금·버전 도메인 결합, INV-4).

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| L3 하네스 별도 복제 | integration_L4에 마이그레이션·부팅·시드·문서 트리 픽스처를 새로 작성 | 독립성 | 하네스 중복·드리프트, 사용자 지시 위반 | 기각 |
| **L3 하네스 재사용·확장** | integration_L3 conftest/helpers를 재사용하고 잠금·휴지통·스윕 시나리오만 추가 | 중복 제거·단일 하네스 진화 | L3 픽스처 계약에 결합 | **채택**("extend, don't duplicate") |
| 스윕을 APScheduler job 실시간 대기로 검증 | 스케줄러 기동 후 interval 경과 대기 | 실제 스케줄 경로 | 비결정성·느림·테스트 취약 | 기각(부팅 스모크로만 관찰) |
| 스윕을 `now` 주입 직접 호출로 검증 | `sweep_expired_bundles(db, now)`/`run_sweep` 직접 호출 | 결정적 만료 경계·빠름·실제 s10 코드 | 스케줄러 job 자체 경로는 부팅 스모크 별도 필요 | **채택**(s10 design의 테스트 결정성 계약 활용) |
| 잠금↔삭제 독립을 lock 컬럼 임의 조작으로 검증 | 테스트가 DB에 lock_user_id 직접 세팅 | 셋업 간단 | 실제 s09 획득 경로 미검증 | 기각(실제 `POST /lock`으로 설정) |

## Design Decisions

### Decision: L3 하네스 확장으로 L4 결합 환경 구성
- **Context**: 사용자 지시 "extend its integration test harness (reuse, don't duplicate)".
- **Alternatives Considered**:
  1. L4 전용 하네스 신규 작성 — 마이그레이션·부팅·admin 시드·워크스페이스/멤버/문서 트리 픽스처를 중복 정의.
  2. L3 하네스 재사용 — `integration_L3/conftest.py`·`helpers.py`(및 그것이 재사용하는 L2/L1 자산)를 import·확장.
- **Selected Approach**: `tests/integration_L4/conftest.py`가 L3의 하네스 픽스처(마이그레이션·`create_app` 부팅·admin
  시드·role별 세션 클라이언트·워크스페이스/멤버·문서 트리·엔진 세션)를 재사용하고, 두 editor(A·B) 세션·잠금/휴지통
  시나리오·스윕(`now` 주입) 호출 픽스처와 잠금·버전·휴지통·스윕 호출 헬퍼만 신규 추가한다.
- **Rationale**: 하네스 단일화로 계약 드리프트를 방지하고, L4가 L1·L2·L3 위에 누적된다는 계층 구조를 코드로 반영.
- **Trade-offs**: L3 픽스처 시그니처에 결합되지만, 재검증 트리거가 이미 하위 계층을 함께 재실행하므로 정합적이다.
- **Follow-up**: 부팅 앱이 s09 잠금·버전 라우터 + s10 휴지통 라우터·스케줄러가 조립된 상태여야 한다.

### Decision: 잠금·삭제 독립은 실제 API 왕복, 스윕은 now 주입 직접 호출로 검증
- **Context**: L4 시점에는 잠금 라우트(s09)와 휴지통 라우트(s10)가 실제 존재하며, 스윕은 결정적 검증이 필요.
- **Selected Approach**: 잠금 상태는 `POST /lock`으로 설정하고 삭제는 `DELETE /documents/{id}`·`DELETE
  /trash/{bundleId}`로 수행해 잠금↔삭제 독립을 실제 e2e로 검증한다. 보관 스윕은 `sweep_expired_bundles(db, now)`/
  `run_sweep`를 `now` 주입으로 직접 호출해 만료 경계를 결정적으로 검증한다. 엔진·스윕 직접 호출은 실제 s07·s10 코드
  실행이므로 mock 금지에 저촉되지 않는다.
- **Rationale**: 실제 획득·삭제·스윕 경로를 결합으로 검증하되 스케줄러 실시간 대기의 비결정성을 회피. s10 design이
  `now` 주입을 테스트 결정성 계약으로 명시했으므로 이를 활용.
- **Trade-offs**: 스케줄러 job 자체 경로(interval 기동)는 부팅 스모크(`>0` 기동·`<=0` 미기동)로만 관찰하고, 만료
  로직은 서비스 직접 호출로 검증한다.

### Decision: Settings additive 조정 항목을 실제 결합 부팅으로 확인
- **Context**: 사용자 지시 — additive `trash_sweep_interval_seconds` + APScheduler가 s01 Settings 계약 로딩을 깨지
  않는지 확인.
- **Selected Approach**: 계약 스위트에서 실제 결합 부팅으로 `Settings`/`get_settings` 로딩 성공·기존 필드
  (`default_trash_retention_days` 등) 보존·단일 접근자 유지·APScheduler 결합 부팅 회귀 부재·`>0`/`<=0` 스케줄러 분기를
  관찰한다.
- **Rationale**: additive 확장의 회귀는 부팅 시점에 표면화되므로 실제 부팅이 가장 신뢰 가능한 검증이다.
- **Trade-offs**: 없음. 이는 계약 대조 스위트의 한 그룹으로 통합된다.

### Decision: 게이트 판정은 실제 pytest 실행 결과로만 산출
- **Context**: 로드맵 게이트 규칙(체크포인트 통과가 상위 계층 impl 착수의 선행 조건).
- **Selected Approach**: `uv run pytest tests/integration_L4` 전체 통과 = 게이트 통과(=L5 착수 가능). 수동 선언
  금지. DB 미가용·부팅 실패 등 환경 미충족은 스킵이 아니라 실패로 처리(미검증의 통과 오인 방지).
- **Rationale**: `s04`·`s06`·`s08`과 동일 원칙. 미검증이 통과로 오인되면 회귀가 상위 계층으로 전파된다.

## Risks & Mitigations
- **APScheduler 실기동으로 인한 테스트 비결정성** — 테스트는 `run_sweep`/`sweep_expired_bundles`를 `now` 주입으로
  직접 호출하고 스케줄러 job 대기를 하지 않는다. 스케줄러 결합은 부팅 스모크(`>0` 기동·`<=0` 미기동)로만 관찰.
- **Settings additive 확장 회귀(부팅 실패·필드 소실·모듈별 설정 파일 도입)** — 실제 결합 부팅에서 `Settings` 로딩·
  기존 필드 보존·단일 접근자 유지를 관찰. 회귀 시 원인 spec(s10/s01) 수정.
- **잠금 상태 오설정으로 인한 위양성** — 잠금은 반드시 실제 `POST /lock`으로 설정하고 테스트가 lock 컬럼을 임의
  조작하지 않는다(실제 획득 경로 결합 검증).
- **스윕 만료 경계의 초 단위 정밀도** — `now` 주입으로 경계값(만료 직전/직후)을 명시 세팅해 결정적으로 검증. 묶음
  `trashed_at`을 알려진 값으로 구성.
- **테스트 상태 오염(멀티 사용자·워크스페이스·문서 트리·묶음·잠금)** — 각 테스트가 고유 login_id·워크스페이스·문서
  트리를 생성하고 정리 픽스처로 격리. L1~L3의 고유 식별자 생성기를 재사용.
- **엔진/스윕 직접 호출의 세션 정합** — 부팅 앱과 동일한 `SessionLocal`/`get_db` 세션 팩토리로 엔진·스윕을 호출해
  API 경유 상태 변경과 관찰이 동일 DB를 보게 한다.
- **DB 미가용·부팅 실패** — 스킵이 아니라 실패로 처리하여 게이트가 미검증 상태로 통과하지 않게 한다.

## References
- 대조 기준 단일 소스: `.kiro/specs/s01-contract-foundation/design.md`
  (§Physical Data Model document(lock 필드)·document_version · §API Endpoint Catalog 24~31 · §Errors · §Settings
  스키마 · §Invariants Catalog INV-1·2·3·4·7·9·10·11·12 · §Common/Permissions).
- 검증 대상 동작: `.kiro/specs/s09-lock-version/design.md`(잠금 생명주기·저장 트랜잭션·버전 목록·§4.3 독립),
  `.kiro/specs/s10-trash/design.md`(휴지통 API·`RetentionSweepService`·`RetentionScheduler`·Settings additive·
  묶음→WS 어댑터·엔진 위임), `.kiro/specs/s07-document-core/design.md`(`DocumentStateEngine`·복구/완전삭제·묶음
  식별·문서→WS 어댑터).
- 재사용할 하네스 패턴: `.kiro/specs/s08-integration-check-L3/design.md`(§L3TestHarness·Helpers·스위트 구성·게이트
  판정), 및 그것이 재사용하는 `s06-integration-check-L2`·`s04-integration-check-L1` 하네스.
- 게이트·재검증 트리거: `.kiro/steering/roadmap.md`(§게이트 · §재검증 트리거 · §Shared seams to watch).
