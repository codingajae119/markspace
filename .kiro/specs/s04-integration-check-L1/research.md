# Research & Design Decisions — s04-integration-check-L1

## Summary
- **Feature**: `s04-integration-check-L1` (누적 통합 검증 체크포인트, L1)
- **Discovery Scope**: Complex Integration (feature 구현 아님 — 실제 결합 검증 전용)
- **Key Findings**:
  - 검증 대상은 누적 upstream(`s01` ⊕ `s02` ⊕ `s03`)이며, 대조 기준은 항상 `s01` 단일 소스다. s02·s03의 개별
    design은 대조 기준이 아니라 검증 대상 구현이다.
  - 이번 계층에서 처음 결합되는 경계는 **계정 생명주기(s03) ↔ 로그인 게이트(s02)**다. 두 spec은 서로를 직접
    호출하지 않고 `user` 테이블의 상태(`is_active`/`is_deleted`/`password_hash`)를 매개로만 결합된다 —
    이 "상태 매개 결합"이 개별 spec 검증에서 비어 있던 지점이다.
  - 애플리케이션에는 admin 생성 경로가 없다(`is_admin`은 수동 DB 설정). 따라서 실제 결합 e2e를 돌리려면 테스트
    하네스가 admin 사용자를 DB에 직접 시드해야 한다.

## Research Log

### 결합 경계 식별 — 계정 상태 ↔ 로그인
- **Context**: 체크포인트가 무엇을 "새로" 검증해야 하는지(개별 spec 검증과 겹치지 않게) 결정해야 함.
- **Sources Consulted**: `brief.md`, `roadmap.md`(§게이트·재검증 트리거·Shared seams to watch),
  `s01/design.md`(§Physical Data Model user, §API Catalog 1~8, §Errors, §Invariants INV-3·4),
  `s02/design.md`(로그인 상태 게이트 흐름·본인 비번 변경), `s03/design.md`(계정 생명주기 flag 전이·단일 admin 잠금).
- **Findings**:
  - s02 로그인 게이트: `find_by_login_id` → `verify_password` → `is_active`/`is_deleted` 게이트. 실패는 사유 불문
    401 동일 응답(계정 열거 방지).
  - s03 상태 전이: 삭제=`is_deleted=true`, 비활동=`is_active=false`, 재활성화=`is_deleted=false`. 두 flag 독립.
    admin 대상 비활동/삭제는 409(단일 admin 잠금 방지)이므로 시나리오는 **비-admin 사용자**로 구성해야 한다.
  - s03 비밀번호 재설정과 s02 본인 비밀번호 변경은 동일 `password_hash` 컬럼을 s01 해싱 스킴으로 갱신 → 로그인
    검증과 자연히 결합된다.
- **Implications**: 체크포인트는 s03로 상태를 만들고 s02로 로그인 결과를 관찰하는 **cross-spec e2e**로 구성한다.
  단위 로직 재검증이 아니라 결합 시나리오만 소유한다.

### 실제 결합 e2e를 위한 테스트 하네스
- **Context**: mock 금지(brief·roadmap) 제약 하에서 실제 DB·앱·세션을 결합해야 함.
- **Sources Consulted**: `s01/design.md`(§Bootstrap `create_app`, SessionMiddleware, 마이그레이션),
  `s02/tasks.md`·`s03/tasks.md`(통합 테스트가 "마이그레이션된 DB + 부팅 앱"을 전제로 함), `tech.md`(uv 실행 표준).
- **Findings**:
  - s01의 `create_app()`이 세션 미들웨어·에러 핸들러·라우터 조립을 완성하고 s02·s03 라우터가 조립 지점에
    등록되어 있으므로, 부팅 앱 하나로 auth·admin 경로가 모두 노출된다.
  - FastAPI `TestClient`(Starlette)는 쿠키 자를 유지하므로 로그인 세션 쿠키가 후속 요청에 자동 전달되어 실제
    세션 결합을 mock 없이 재현할 수 있다.
  - admin 시드는 애플리케이션 경로가 없으므로 리포지토리/ORM 또는 직접 INSERT로 `is_admin=true` 사용자를 생성.
- **Implications**: `tests/integration_L1/conftest.py`에 (1) 마이그레이션 적용, (2) 부팅 앱, (3) admin 시드,
  (4) 세션 유지 클라이언트 픽스처를 둔다. 이 하네스가 유일한 신규 코드이며 feature 로직이 아니다.

### 계약 대조 방식
- **Context**: "s01 단일 소스와 일치"를 어떻게 자동 검증할지.
- **Findings**:
  - user 스키마: 부팅에 사용된 실제 DB의 `information_schema`(또는 마이그레이션이 만든 실 테이블)에서 컬럼·유일
    제약을 조회해 s01 물리 모델과 대조.
  - API 계약: 부팅 앱의 라우트 테이블(OpenAPI/`app.routes`)에서 경로·메서드를 추출해 s01 카탈로그 1~8과 대조.
  - 에러 모델: 대표 실패 요청(미인증 401, 비-admin 403, 미존재 404, 중복 409, 검증 422)을 실제로 유발해 응답
    본문 형태(`code`/`message`/`field_errors`)와 상태 코드가 s01 에러 카탈로그와 일치하는지 관찰.
- **Implications**: 계약 대조는 "구현이 카탈로그를 벗어났는가"를 보는 결합 관점 검증이며, s01 자체 계약 완전성
  테스트(s01 소유)와 중복되지 않는다.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 실제 결합 e2e(선택) | 실 DB+부팅 앱+세션 클라이언트로 s03→s02 시나리오 관찰 | mock 없이 실제 경계 결합 검증, 회귀 조기 포착 | 실행에 MySQL 8·마이그레이션 필요 | brief·roadmap 요구(mock 금지)와 정합 |
| 컴포넌트 단위 재검증 | 각 서비스/리포지토리 단위 재테스트 | 빠름 | 결합 경계를 못 봄, 개별 spec 검증과 중복 | 기각 |
| 계약 문서 정적 대조만 | design 문서끼리 텍스트 대조 | 실행 불필요 | 실제 런타임 정합 미보장, "실제 구현 결합" 지시 위반 | 기각 |

## Design Decisions

### Decision: 체크포인트는 테스트 자산과 게이트 판정만 소유(feature 코드 0)
- **Context**: roadmap 게이트 규칙 — 체크포인트는 feature 로직을 구현하지 않는다.
- **Alternatives Considered**:
  1. 검증 중 발견된 위반을 체크포인트에서 직접 수정 — 경계 위반.
  2. 위반을 원인 spec으로 되돌려 수정하고 체크포인트는 재실행만 — 경계 준수.
- **Selected Approach**: 2. 체크포인트는 `tests/integration_L1/`와 재검증 체크리스트만 산출. 회귀 발견 시 원인
  spec(s01/s02/s03)에서 수정 후 이 체크포인트를 재실행.
- **Rationale**: 계약 드리프트의 단일 수정 지점을 원인 spec에 유지(structure.md 코드 조직 원칙, 계약 단일 소스).
- **Trade-offs**: 체크포인트 자체는 산출물이 얇지만, 회귀 수정 루프가 spec 간을 오간다. 대신 책임 경계가 선명.
- **Follow-up**: 실패 시 어느 upstream을 고쳐야 하는지 실패 메시지가 가리키도록 테스트를 구성.

### Decision: cross-spec 시나리오는 비-admin 사용자로 구성
- **Context**: s03는 단일 admin 잠금 방지를 위해 admin 계정의 비활동/삭제를 409로 거부한다.
- **Selected Approach**: 생명주기 시나리오(비활동/삭제/재활성화)의 대상은 admin이 생성한 일반 사용자로 한정.
  admin 시드 계정은 시나리오를 수행하는 주체(actor)로만 사용.
- **Rationale**: admin 대상 상태 전이는 s03가 의도적으로 막으므로 로그인 거부 경계를 그 계정으로 검증할 수 없다.
- **Trade-offs**: 없음(요구 시나리오와 일치).
- **Follow-up**: admin 대상 409 거부 자체는 s03 소유 검증이므로 여기서 중복 검증하지 않는다.

### Decision: 상태 독립성(is_active ⊥ is_deleted)을 로그인 관점에서 교차 검증
- **Context**: s03는 두 flag의 독립 갱신을 보장. s02는 둘 중 하나라도 참이면 로그인 거부.
- **Selected Approach**: "비활동 상태 유지 + 삭제 flag만 되돌림 → 여전히 로그인 거부"를 검증하여 독립성이 로그인
  결합에서 올바르게 작동함을 확인(Requirement 5.2).
- **Rationale**: 재활성화가 로그인 허용을 무조건 복원한다는 오해(회귀 위험)를 결합 관점에서 차단.
- **Trade-offs**: 시나리오 1개 추가. 경계 정밀도 향상으로 상쇄.

## Risks & Mitigations
- **실 DB 부재로 e2e 미실행** — conftest에서 마이그레이션 적용을 전제로 하고, DB 미가용 시 명확히 실패(스킵 아님)
  하도록 하여 "검증 안 됨"이 "통과"로 오인되지 않게 한다.
- **테스트 상태 오염(계정 잔존)** — 각 테스트가 고유 login_id를 쓰고 트랜잭션/정리 픽스처로 격리.
- **세션 쿠키 정합 회귀** — 로그인→me 왕복을 실제 쿠키 자로 검증(s01 세션 키 ↔ s02 write 정합).
- **계약 대조가 s01 자체 테스트와 중복** — 체크포인트는 "실제 결합된 런타임이 카탈로그를 벗어났는가"만 보고,
  카탈로그 완전성(문서 정합)은 s01 소유로 남긴다.

## References
- `.kiro/specs/s01-contract-foundation/design.md` — §Physical Data Model(user), §API Endpoint Catalog(1~8),
  §Errors(에러 코드 카탈로그), §Invariants Catalog(INV-3·4), §Bootstrap(`create_app`).
- `.kiro/specs/s02-auth/design.md` — 로그인 상태 게이트 흐름, 본인 비밀번호 변경 흐름, 세션 정합.
- `.kiro/specs/s03-admin-account/design.md` — 계정 상태 전이 판정, 단일 admin 잠금, 비밀번호 재설정, INV-4.
- `.kiro/steering/roadmap.md` — §게이트(G-1), §재검증 트리거, §Shared seams to watch.
- `docs/projects.md` — §3 REQ-1·REQ-2, §5 INV-3·INV-4.
