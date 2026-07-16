# Research & Design Decisions — s08-integration-check-L3

---
**Purpose**: L3 누적 통합 검증 체크포인트의 검증 전략·하네스 재사용 결정·bundle 엔진 재사용 경계·정밀도 Risk
재검증 방안을 기록한다.
---

## Summary
- **Feature**: `s08-integration-check-L3`
- **Discovery Scope**: Extension (기존 `s06-integration-check-L2` 하네스 패턴 확장 + 문서 도메인·bundle 엔진 실제 결합 관찰)
- **Key Findings**:
  - L3의 신규 경계는 **문서 도메인**이다. `s07`이 문서 CRUD·이동·삭제 라우트(카탈로그 행 18~23)와
    `DocumentStateEngine`(삭제 캐스케이드·복구·완전삭제·묶음 식별)을 채우면서, (1) `require_ws_role`이 문서
    라우트에서 실제 role로 게이팅되는지, (2) bundle 비흡수 엔진이 실제 API·엔진 결합에서 INV-5·6·10·11·12를
    유지하는지가 L3 검증의 핵심이다.
  - 대조 기준은 `s01` 단일 소스다: `document`/`document_version` 물리 모델, 카탈로그 행 18~23, 에러 카탈로그,
    INV-1·2·3·4·5·6·10·11·12, `Common/Permissions`의 `Role` 위계·admin bypass 계약.
  - L3에서 문서 라우트가 노출하는 게이트 등급은 **viewer 요구**(행 19·20)와 **editor 요구**(행 18·21·22·23)다.
    L2에서 "viewer 통과 + owner 거부"로만 관찰됐던 editor 위계가 L3에서 **문서 쓰기 권한**으로 직접 검증된다.
  - **bundle 엔진의 재사용 경계**: `s07` 라우터는 `active → trashed`(행 23 DELETE)만 노출한다. `trashed → active`
    (복구)·`trashed → deleted`(완전삭제)·묶음 열거 API는 L4(s10)에서야 등장한다. 따라서 L3은 삭제 캐스케이드를
    **API 경유**로, 복구·완전삭제·묶음 식별을 **엔진 primitive 직접 호출**로 검증한다. 엔진 직접 호출은 실제
    `s07` 프로덕션 코드를 실행하는 것이므로 mock 금지 원칙에 저촉되지 않으며, 오히려 s10이 소비할 계약을 선검증한다
    (`s07/design.md`의 "엔진 재사용 경계" 통합 테스트와 동일 접근).
  - `s07`의 `research.md`는 `trashed_at`이 `DATETIME`(초 단위) 정밀도라서 동일 초 독립 삭제가 묶음 재구성에서
    오병합될 **이론적 여지**를 Risk로 기록했다. 사용자 지시에 따라 L3은 이 경계를 겨냥한 묶음 멤버십 경계 테스트를
    포함한다. 정상 경로에서 캐스케이드는 이미 trashed된 하위를 구조적으로 제외하므로 오병합이 발생하지 않아야 한다.
  - `s06`의 하네스(L1 재사용 + 워크스페이스/멤버/role 세션 시나리오)는 그대로 확장 가능하다. 사용자 지시
    ("extend, don't duplicate")에 따라 이를 재사용하고 문서 생성·이동·삭제 헬퍼와 엔진 세션 접근 픽스처만 추가한다.

## Research Log

### 문서 라우트의 require_ws_role 실제 데이터 게이팅 경계
- **Context**: L3 검증의 초점은 문서 라우트가 실제 workspace_member 데이터 위에서 editor/viewer 위계를 계약대로
  게이팅하는지다.
- **Sources Consulted**: `s01/design.md` §Common/Permissions(`Role` IntEnum, `require_ws_role`, admin bypass),
  §API Endpoint Catalog 행 18~23, `s07/design.md` §DocumentRouter API Contract·§DocumentWsAdapter, `docs`
  INV-1·2·3.
- **Findings**:
  - 문서 라우트 게이트: 생성·수정·이동·삭제=`require_ws_role(EDITOR)`, 조회·목록=`require_ws_role(VIEWER)`.
  - `/workspaces/{id}/documents`(행 18·19)는 경로 `{id}`가 곧 workspace_id → resolver 직접 주입.
  - `/documents/{id}`(행 20~23)는 문서를 로드해 workspace_id를 추출하는 **문서→WS 어댑터**로 resolver에 주입.
    미존재 문서는 404, 권한 미충족은 403. 어댑터는 위계 비교·admin bypass를 재구현하지 않고 `s01` resolver에 위임.
  - `s07`은 판정 **로직**을 재정의하지 않고 문서→WS 매핑만 신설한다. 판정 로직은 `s01`, 멤버십 데이터는 `s05`.
- **Implications**: L3은 editor/viewer/owner/비멤버/admin 세션으로 문서 CRUD·이동·삭제·조회 게이트를 통과/거부시켜
  위계와 admin bypass를 관찰한다. 특히 viewer의 문서 변경 거부(INV-2)와 비멤버 차단(INV-1)이 문서 도메인에서 처음
  직접 검증된다.

### bundle 엔진 결합의 검증 경로 — API 경유 vs 엔진 primitive 직접 호출
- **Context**: brief의 "bundle 엔진은 API 경유 시나리오로 불변식 검증", 그러나 복구/완전삭제 API는 L4(s10)에만 존재.
- **Sources Consulted**: `s01/design.md` 카탈로그(행 23 DELETE는 s07, 행 29~31 휴지통은 s10),
  `s07/design.md` §DocumentStateEngine(`trash_document`·`restore_bundle`·`purge_bundle`·`identify_bundles`·
  `get_bundle`·`active_descendants`), §Testing Strategy "엔진 재사용 경계" 통합 테스트, `docs` §4.2·§6.2~6.7.
- **Findings**:
  - `active → trashed`는 행 23 `DELETE /documents/{id}`로 노출된다 → **API 경유** 검증 가능(권한 게이트 포함).
  - `trashed → active`·`trashed → deleted`·묶음 열거는 s07이 엔진 primitive로만 노출한다(라우터 없음, s10이 소비).
    → L3은 부팅 앱과 동일한 DB 세션으로 실제 `DocumentStateEngine`을 인스턴스화해 `restore_bundle`·`purge_bundle`·
    `identify_bundles`·`get_bundle`을 직접 호출해 검증한다.
  - 이는 `s07/design.md`가 이미 명시한 "엔진 primitive가 라우터 밖에서도 호출 가능한 재사용 경계임을 확인" 테스트와
    동일 접근이며, s10이 이 primitive를 소비할 계약을 L3에서 선검증하는 의미를 갖는다.
- **Implications**: L3은 (1) 삭제 캐스케이드·비흡수를 DELETE API 경유로, (2) 복구 위치 규칙(6.5·6.7)·완전삭제
  원자성(INV-10)·묶음별 독립성(INV-12)을 엔진 primitive 직접 호출로 검증한다. 둘 다 실제 구현 결합이며 mock 없음.

### trashed_at 묶음 경계 정밀도 Risk 재검증
- **Context**: 사용자 지시 "flagged trashed_at DATETIME second-granularity risk from s07 — include an integration
  test that exercises bundle membership boundaries".
- **Sources Consulted**: `s07/research.md` §"묶음 구성원 재구성의 정밀도(precision) 경계"·§Risks,
  `s01/design.md` document 물리 모델(타임스탬프 `DATETIME`), `docs` INV-10·11.
- **Findings**:
  - `s07`은 묶음을 별도 컬럼 없이 "루트 + 동일 `trashed_at` 연결 서브트리"로 재구성한다. `trashed_at`이 `DATETIME`
    (초 단위)이므로, 부모를 나중에 삭제하는데 이미 trashed된 자식과 `trashed_at` 초가 같으면 독립 묶음이 잘못
    병합될 **이론적 여지**가 있다.
  - `s07`의 방어책: (1) 캐스케이드가 이미 trashed된 하위를 **구조적으로 제외**(6.2.1)하여 정상 경로에서 오병합을
    차단, (2) 묶음 루트 판정을 "부모가 trashed가 아니거나 부모의 `trashed_at`이 자신과 다른 문서"로 정의. 즉 묶음
    구성원은 **삭제 시점에 확정**되고 재구성은 그 결과를 읽을 뿐이다.
  - `s07`은 실제 회귀 관측 시 `trashed_at` 고해상도화(`DATETIME(6)` 등)를 **s01 계약 개정**으로 승격(전 체크포인트
    재검증 동반)하기로 기록했다.
- **Implications**: L3은 부모-자식이 동일 초에 trashed될 수 있는 경계(자식 먼저 삭제 → 곧바로 부모 삭제)를 구성해
  묶음 멤버십 경계가 오병합 없이 유지됨을 검증한다. 회귀 관측 시 이를 실패로 보고하고 s01 정밀도 승격 대상으로
  기록한다(체크포인트는 수정하지 않고 원인 spec에서 처리).

### 작성자 표시 보존 — 삭제된 사용자(L1) ↔ 문서 도메인 결합
- **Context**: brief의 "작성자 표시: `is_deleted` 사용자(L1) 이름이 문서 작성자로 보존".
- **Sources Consulted**: `s01/design.md` document(`created_by` FK), user(`is_deleted`·`name`, 물리 삭제 없음),
  `docs` INV-4.
- **Findings**:
  - `document.created_by`는 `user(id)` FK다. INV-4로 user는 물리 삭제되지 않으므로(is_deleted 플래그만) dangling
    FK가 발생하지 않고 작성자 이름이 보존된다.
  - 삭제된 사용자는 로그인만 거부(s02 게이트)되고 그가 만든 문서·이름은 DB에 남는다.
- **Implications**: L3은 문서 작성자를 admin이 삭제 처리한 뒤, 그 문서의 `created_by` 참조와 사용자 이름이 보존됨을
  직접 조회로 확인한다(계정 생명주기 L1 ↔ 문서 도메인 결합, INV-4).

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| L2 하네스 별도 복제 | integration_L3에 마이그레이션·부팅·시드·워크스페이스 픽스처를 새로 작성 | 독립성 | 하네스 중복·드리프트, 사용자 지시 위반 | 기각 |
| **L2 하네스 재사용·확장** | integration_L2 conftest/helpers를 재사용하고 문서·엔진 시나리오만 추가 | 중복 제거·단일 하네스 진화 | L2 픽스처 계약에 결합 | **채택**(“extend, don't duplicate”) |
| bundle 엔진 단위 테스트로만 검증 | 엔진을 격리 호출해 규칙 검증 | 빠름 | s07 자체 테스트와 중복, 결합·게이팅 경계 미검증 | 기각(체크포인트는 결합·경계 검증) |
| 복구/완전삭제도 API로만 검증 | s10 API를 통해서만 엔진 검증 | API 대칭 | L3 시점에 s10 미구현 → mock 필요(금지) | 기각 |

## Design Decisions

### Decision: L2 하네스 확장으로 L3 결합 환경 구성
- **Context**: 사용자 지시 "reuse its integration test harness (reuse, don't duplicate)".
- **Alternatives Considered**:
  1. L3 전용 하네스 신규 작성 — 마이그레이션·부팅·admin 시드·워크스페이스/멤버 픽스처를 중복 정의.
  2. L2 하네스 재사용 — `integration_L2/conftest.py`·`helpers.py`(및 그것이 재사용하는 L1 자산)를 import·확장.
- **Selected Approach**: `tests/integration_L3/conftest.py`가 L2의 하네스 픽스처(마이그레이션 적용·`create_app`
  부팅·admin 시드·role별 세션 클라이언트·워크스페이스/멤버 구성 헬퍼)를 재사용하고, 문서 생성·하위 문서·이동·삭제
  호출 헬퍼와 부팅 앱과 동일 DB 세션으로 `DocumentStateEngine`에 접근하는 엔진 픽스처만 신규 추가한다.
- **Rationale**: 하네스 단일화로 계약 드리프트를 방지하고, L3이 L1·L2 위에 누적된다는 계층 구조를 코드로 반영.
- **Trade-offs**: L2 픽스처 시그니처에 결합되지만, 재검증 트리거가 이미 L1·L2·L3을 함께 재실행하므로 정합적이다.
- **Follow-up**: L2 픽스처가 재사용 가능한 형태(role별 세션 클라이언트 팩토리·워크스페이스 구성 헬퍼)로 노출되는지
  확인. 부팅 앱이 s07 문서 라우터가 조립된 상태여야 한다.

### Decision: bundle 엔진 primitive는 엔진 직접 호출로, 삭제 캐스케이드는 API로 검증
- **Context**: 복구·완전삭제·묶음 열거 API는 L4(s10)에만 존재하지만, L3 게이트는 엔진 계약 정합을 요구한다.
- **Selected Approach**: `active → trashed`는 `DELETE /documents/{id}` API 경유(권한 게이트 포함)로, `trashed →
  active`·`trashed → deleted`·묶음 식별은 실제 `DocumentStateEngine` primitive 직접 호출로 검증한다.
- **Rationale**: 엔진 직접 호출은 실제 s07 프로덕션 코드 실행이므로 mock 금지에 저촉되지 않고, s10이 소비할 재사용
  계약을 선검증한다. s07 design의 "엔진 재사용 경계" 테스트와 동일 접근.
- **Trade-offs**: 복구·완전삭제의 HTTP 표면 검증은 L4(s11)로 이월되지만, 엔진 계약 정합은 L3에서 확보한다.

### Decision: 게이트 판정은 실제 pytest 실행 결과로만 산출
- **Context**: 로드맵 게이트 규칙(체크포인트 통과가 상위 계층 impl 착수의 선행 조건).
- **Selected Approach**: `uv run pytest tests/integration_L3` 전체 통과 = 게이트 통과(=L4 착수 가능). 수동 선언
  금지. DB 미가용 등 환경 미충족은 스킵이 아니라 실패로 처리(미검증의 통과 오인 방지).
- **Rationale**: `s04`·`s06`과 동일 원칙. 미검증이 통과로 오인되면 회귀가 상위 계층으로 전파된다.

## Risks & Mitigations
- **trashed_at 초 단위 정밀도 오병합(s07 flagged Risk)** — 부모-자식 동일 초 삭제 경계 테스트로 묶음 멤버십 경계를
  검증. 정상 경로는 캐스케이드가 이미 trashed된 하위를 제외해 구조적으로 차단됨. 회귀 관측 시 실패 보고 + s01 정밀도
  승격 대상 기록(체크포인트는 수정하지 않음).
- **테스트 상태 오염(멀티 사용자·멀티 워크스페이스·멀티 문서 트리)** — 각 테스트가 고유 login_id·워크스페이스·
  문서 트리를 생성하고 정리 픽스처(트랜잭션 롤백/명시 정리)로 격리. L1·L2의 고유 식별자 생성기를 재사용.
- **엔진 primitive 직접 호출의 세션 정합** — 부팅 앱과 동일한 `SessionLocal`/`get_db` 세션 팩토리로 엔진을
  인스턴스화해 API 경유 상태 변경과 엔진 관찰이 동일 DB를 보게 한다(별도 트랜잭션 격리로 인한 관측 누락 방지).
- **이동 규칙의 순환/WS 위반 매핑 모호성(409 vs 422)** — `s07`이 구현 시 확정하는 매핑을 기준으로 "거부(4xx)"를
  검증하되, `s01` 에러 카탈로그의 상태 코드 집합(409/422) 범위 내인지 대조한다(구체 코드는 구현 확정 값 허용).
- **DB 미가용** — 스킵이 아니라 실패로 처리하여 게이트가 미검증 상태로 통과하지 않게 한다.

## References
- 대조 기준 단일 소스: `.kiro/specs/s01-contract-foundation/design.md`
  (§Physical Data Model document·document_version · §API Endpoint Catalog 18~23 · §Errors · §Invariants Catalog
  INV-1·2·3·4·5·6·10·11·12 · §Common/Permissions).
- 검증 대상 동작: `.kiro/specs/s07-document-core/design.md`(문서 CRUD·이동·삭제 게이팅·`DocumentStateEngine`·
  `DocumentWsAdapter`·삭제 캐스케이드·복구·완전삭제·묶음 식별), `.kiro/specs/s07-document-core/research.md`
  (묶음 재구성 정밀도 Risk).
- 재사용할 하네스 패턴: `.kiro/specs/s06-integration-check-L2/design.md`(§L2TestHarness·Helpers·스위트 구성·
  게이트 판정), 및 그것이 재사용하는 `s04-integration-check-L1` 하네스.
- 게이트·재검증 트리거: `.kiro/steering/roadmap.md`(§게이트 · §재검증 트리거 · §Shared seams to watch).
