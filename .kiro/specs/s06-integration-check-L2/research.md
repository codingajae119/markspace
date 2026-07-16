# Research & Design Decisions — s06-integration-check-L2

---
**Purpose**: L2 누적 통합 검증 체크포인트의 검증 전략·하네스 재사용 결정·리스크를 기록한다.
---

## Summary
- **Feature**: `s06-integration-check-L2`
- **Discovery Scope**: Extension (기존 `s04-integration-check-L1` 하네스 패턴 확장 + 실제 결합 관찰)
- **Key Findings**:
  - L2의 신규 경계는 **권한·멤버십**이다. `s01` `require_ws_role` resolver는 데이터 부재 시 admin만 통과하다가
    `s05`가 `workspace_member`를 채우면서 실제 role 판정으로 전환된다. 이 "resolver 실동작"이 L2 검증의 핵심이다.
  - 대조 기준은 `s01` 단일 소스다: `workspace`/`workspace_member` 물리 모델, 카탈로그 행 9~17, 에러 카탈로그,
    INV-1·2·3·4, `Common/Permissions`의 `Role` 위계·admin bypass 계약.
  - L2에서 관찰 가능한 게이트 등급은 **viewer 요구**(행 12)와 **owner 요구**(행 13~17)뿐이다. editor 전용
    워크스페이스 엔드포인트는 존재하지 않으므로, editor 위계는 "viewer 게이트 통과 + owner 게이트 거부"로 관찰한다.
    editor의 문서 쓰기 권한 자체는 L3(s07·s08)에서 검증된다.
  - `s04`의 하네스(마이그레이션·앱 부팅·admin 시드·세션 유지 클라이언트·계정 생명주기 헬퍼)는 그대로 확장 가능하다.
    사용자 지시(“extend, don't duplicate”)에 따라 이를 재사용하고 워크스페이스/멤버 시나리오 헬퍼만 추가한다.

## Research Log

### require_ws_role resolver의 실제 데이터 판정 경계
- **Context**: L2 검증의 초점은 resolver가 실제 workspace_member 데이터 위에서 계약대로 판정하는지다.
- **Sources Consulted**: `s01/design.md` §Common/Permissions(`Role` IntEnum, `WorkspaceRoleResolver`,
  `require_ws_role`, admin bypass), `s05/design.md` §권한 게이팅 흐름·§WsIdAdapter, `docs` INV-1·2·3.
- **Findings**:
  - `require_ws_role(minimum)`은 요청자 role이 minimum 이상이거나 요청자가 admin이면 통과, 아니면 403.
  - `s05`는 판정 **로직**을 재정의하지 않고 `workspace_member`(role 데이터)만 채운다. 판정 로직은 `s01` 소유.
  - 워크스페이스 라우트 게이트: 상세=`require_ws_role(VIEWER)`, 수정·삭제·멤버 관리=`require_ws_role(OWNER)`.
    생성·목록=`get_current_user`(인증만). admin 소유권 변경=`require_admin`(admin 전용).
- **Implications**: L2는 viewer 게이트와 owner 게이트를 role별 실제 세션으로 통과/거부시켜 위계·bypass를 관찰한다.
  editor는 두 게이트의 관찰 조합(viewer 통과·owner 거부)으로 위계상 중간 등급임을 확인한다.

### 유일 owner 상태 전이와 멤버십 결합
- **Context**: brief의 "유일 owner를 admin이 비활동/삭제 → editor·viewer 활동 무영향(3.7)".
- **Sources Consulted**: `s03/design.md`(계정 상태 전이·단일 admin 잠금 가드), `s05/design.md`(복수 owner 허용·
  마지막 owner 소실 허용, docs 3.7·3.9), `docs` INV-4.
- **Findings**:
  - 워크스페이스 owner는 시스템 admin과 별개다(`user.is_admin`이 아님). 따라서 s03의 admin 잠금 가드(admin 계정
    비활동/삭제 거부)는 워크스페이스 owner에게는 적용되지 않는다 — 워크스페이스 owner인 일반 사용자는 비활동/삭제
    가능하다.
  - 사용자가 삭제(`is_deleted=true`)되어도 물리 삭제되지 않으므로(INV-4) `workspace_member` 행과 사용자 이름은
    보존된다. 다만 로그인은 s02 상태 게이트가 401로 거부한다.
  - `s05`는 마지막 owner의 소실을 허용한다(docs 3.9). owner가 로그인 불가여도 editor·viewer는 자신의 role로
    워크스페이스에 계속 접근한다(resolver는 로그인한 요청자의 멤버십 role을 볼 뿐 owner 생존 여부와 무관).
- **Implications**: 이 결합은 계정 상태(L1/s03) ↔ 멤버십(s05)의 교차 경계다. L2는 유일 owner를 비활동/삭제한 뒤
  editor·viewer 세션이 무영향인지, 멤버십·이름이 보존되는지, 삭제된 owner 로그인이 401인지를 e2e로 관찰한다.

### admin override 관찰 지점
- **Context**: brief의 "admin이 비멤버 WS에 접근 성공(INV-3, 2.6)".
- **Findings**: admin은 어떤 워크스페이스의 멤버가 아니어도 viewer/owner 게이트를 모두 bypass한다. 또한 목록
  조회(`GET /workspaces`)는 admin이면 전체 반환, 아니면 멤버 스코프(`s05` `WorkspaceService.list_workspaces`).
- **Implications**: admin bypass는 단일 라우트가 아니라 **모든** 워크스페이스 게이트에서 성립해야 한다. L2는
  viewer 게이트·owner 게이트·설정 변경·목록 전체 가시성 네 곳에서 admin bypass를 관찰한다.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| L1 하네스 별도 복제 | integration_L2에 마이그레이션·부팅·시드 픽스처를 새로 작성 | 독립성 | 하네스 중복·드리프트, 사용자 지시 위반 | 기각 |
| **L1 하네스 재사용·확장** | integration_L1 conftest/helpers를 재사용하고 워크스페이스 시나리오만 추가 | 중복 제거·단일 하네스 진화 | L1 픽스처 계약에 결합 | **채택**(“extend, don't duplicate”) |
| 단위 테스트로 resolver 검증 | resolver를 직접 호출해 판정 검증 | 빠름 | mock/실 결합 아님, e2e 경계 미검증 | 기각(mock 금지·결합 검증 목적) |

## Design Decisions

### Decision: L1 하네스 확장으로 L2 결합 환경 구성
- **Context**: 사용자 지시 "reuse its integration test harness pattern (extend, don't duplicate)".
- **Alternatives Considered**:
  1. L2 전용 하네스 신규 작성 — 마이그레이션·부팅·admin 시드·세션 클라이언트를 중복 정의.
  2. L1 하네스 재사용 — `integration_L1/conftest.py`·`helpers.py`를 import·확장.
- **Selected Approach**: `tests/integration_L2/conftest.py`가 L1의 하네스 픽스처(마이그레이션 적용·`create_app`
  부팅·admin 시드·세션 유지 클라이언트 팩토리)와 계정 생명주기 헬퍼를 재사용하고, 워크스페이스 생성·멤버 추가
  (role 지정)·소유권 변경·설정 변경·다중 사용자 세션 클라이언트 헬퍼만 신규 추가한다.
- **Rationale**: 하네스 단일화로 계약 드리프트를 방지하고, L2가 L1 위에 누적된다는 계층 구조를 코드로 반영.
- **Trade-offs**: L1 픽스처 시그니처에 결합되지만, 재검증 트리거가 이미 L1·L2를 함께 재실행하므로 정합적이다.
- **Follow-up**: L1 픽스처가 재사용 가능한 형태(세션 클라이언트 팩토리·고유 login_id 생성기)로 노출되는지 확인.

### Decision: editor 위계의 L2 관찰 범위 한정
- **Context**: brief의 "editor 문서권한"은 문서 도메인(L3)이며, L2엔 editor 전용 워크스페이스 엔드포인트가 없다.
- **Selected Approach**: L2는 editor를 "viewer 게이트 통과 + owner 게이트 거부"로 관찰하여 위계상 중간 등급임을
  확인한다. editor의 문서 쓰기 권한 자체는 s08(L3 체크포인트)로 명시적으로 이월한다.
- **Rationale**: 체크포인트는 현재 계층까지 결합된 것만 검증한다(게이트 규칙). 문서 도메인 미구현 상태에서
  editor 쓰기 권한을 검증하려 하면 mock이 필요해지므로 금지된다.
- **Trade-offs**: L2에서 editor 고유 능력의 전면 검증은 못 하지만, 위계 판정 정합은 확보한다.

### Decision: 게이트 판정은 실제 pytest 실행 결과로만 산출
- **Context**: 로드맵 게이트 규칙(체크포인트 통과가 상위 계층 impl 착수의 선행 조건).
- **Selected Approach**: `uv run pytest tests/integration_L2` 전체 통과 = 게이트 통과(=L3 착수 가능). 수동 선언
  금지. DB 미가용 등 환경 미충족은 스킵이 아니라 실패로 처리(미검증의 통과 오인 방지).
- **Rationale**: `s04`와 동일 원칙. 미검증이 통과로 오인되면 회귀가 상위 계층으로 전파된다.

## Risks & Mitigations
- **테스트 상태 오염(멀티 사용자·멀티 워크스페이스)** — 각 테스트가 고유 login_id·워크스페이스를 생성하고
  정리 픽스처(트랜잭션 롤백/명시 정리)로 격리. L1의 고유 식별자 생성기를 재사용.
- **세션 혼선(다중 role 세션 클라이언트)** — role별로 독립 세션 쿠키를 유지하는 별도 `TestClient` 인스턴스를
  사용(로그인→후속 요청 쿠키 자동 전달). admin·owner·editor·viewer·비멤버 클라이언트를 분리.
- **owner 게이트 통과의 "성공" 판정 모호성** — 문서 미구현 상태에서 owner 요구 라우트의 성공은 워크스페이스 자체
  라우트(PATCH 설정·멤버 추가)로 관찰한다(부수효과가 실제 반영되는지까지 확인).
- **DB 미가용** — 스킵이 아니라 실패로 처리하여 게이트가 미검증 상태로 통과하지 않게 한다.

## References
- 대조 기준 단일 소스: `.kiro/specs/s01-contract-foundation/design.md`
  (§Physical Data Model · §API Endpoint Catalog 9~17 · §Errors · §Invariants Catalog · §Common/Permissions).
- 검증 대상 동작: `.kiro/specs/s05-workspace/design.md`(권한 게이팅·소유권 변경·설정),
  `.kiro/specs/s03-admin-account/design.md`(계정 상태 전이), `.kiro/specs/s02-auth/design.md`(로그인 게이트).
- 재사용할 하네스 패턴: `.kiro/specs/s04-integration-check-L1/design.md`(§L1TestHarness·스위트 구성).
- 게이트·재검증 트리거: `.kiro/steering/roadmap.md`(§게이트 · §재검증 트리거 · §Shared seams to watch).
