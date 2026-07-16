# L1 누적 통합 검증 체크포인트 (s04-integration-check-L1)

> 게이트 **G-1** 산출 지점. 이 문서는 게이트 판정 기준과 재검증 트리거를 기록하는 참조 문서다.
> **판정은 이 문서가 선언하지 않는다.** 판정은 오직 `uv run pytest tests/integration_L1`의
> 재현 가능한 실행 결과로만 산출된다(design.md §GateVerdict: "판정은 실제 테스트 실행 결과로만
> 산출한다 — 수동 선언 금지"). 아래 서술은 그 명령이 권위(authority)이며, 이 문서는 그 명령의
> 기준·범위·후속 조치를 기록할 뿐이다.

## 1. 이 체크포인트는 무엇인가

L1 계층 경계에서 수행하는 **누적 통합 검증 체크포인트**다. 이 시점까지 완성된 upstream 누적 집합
**s01-contract-foundation ⊕ s02-auth ⊕ s03-admin-account**를 대상으로 다음을 검증한다.

- **계약 정합(Req 2)**: 결합된 시스템의 `user` 스키마 · 인증/계정 API 노출(카탈로그 1~8) · 공통
  에러 모델 · 민감 필드 부재가 **s01 단일 소스**와 일치하는가.
- **계정 생명주기 ↔ 로그인 경계(Req 3~6)**: 이번 계층에서 처음 결합되는 경계 —
  생성→로그인, admin 비활동/삭제→로그인 거부, 재활성화→재허용, 상태 독립성, admin 비밀번호
  재설정→로그인, 본인 비밀번호 변경→로그인.
- **물리 삭제 없음(INV-4, Req 7)**: 삭제 처리가 레코드를 물리적으로 제거하지 않고 이름 등
  데이터를 보존하는가.

대조의 유일한 기준은 개별 spec(s02·s03) design이 아니라 **s01 단일 소스**
(§Physical Data Model · §API Endpoint Catalog 1~8 · §Errors 코드 카탈로그 · §Invariants
Catalog)다(Req 1.2).

**mock 없음(Req 1.1)**: 모든 검증은 실제 결합 상태 — 마이그레이션이 적용된 실제 MySQL 8 +
`create_app()`로 부팅된 실제 애플리케이션 + 실제 서명 쿠키 세션 — 에서 수행한다. stub·가짜 구현을
쓰지 않는다.

**feature 미구현(Req 1.3)**: 이 체크포인트는 어떤 엔드포인트·서비스·스키마·마이그레이션도 신규로
구현하지 않는다. 소유물은 `tests/integration_L1/` 테스트 자산과 본 문서(게이트 기록)뿐이다.

## 2. 실행 방법

```bash
# backend/ 디렉터리에서
uv run pytest tests/integration_L1
```

**전제 조건**: 실제 MySQL 8이 가용해야 하며 Alembic 마이그레이션(`uv run alembic upgrade head`
상당)이 하네스(`conftest.py`)에 의해 적용된다. **DB 미가용은 스킵이 아니라 실패(FAILURE)로
처리한다** — 미검증이 통과로 오인되는 것을 막기 위함이다(design §Error Handling · L1TestHarness
Validation).

## 3. G-1 게이트 판정 기준 (Req 8.1, 8.2)

- **G-1 통과 조건**: `uv run pytest tests/integration_L1` 전체(Requirement 2~7 스위트 —
  계약 대조 `test_contract_conformance.py`, 계정 생명주기↔로그인 `test_account_lifecycle_login.py`,
  INV-4 보존 `test_soft_delete_preservation.py`)가 **전부 green**이면 G-1 통과다(Req 8.1).
- **G-1 미통과 조건**: 위 실행에서 **하나라도 실패하면** G-1 미통과이며, L2(`s05-workspace`)
  impl 착수는 **차단**된다(Req 8.2).
- **판정의 권위**: 판정은 이 문서의 선언이 아니라 위 명령의 실행 결과에서 **파생(derived)**된다.
  전부 통과한 실행 그 자체가 곧 판정이다(design §GateVerdict — 수동 선언 금지).

**현재 근거(latest basis)**: `uv run pytest tests/integration_L1` 최신 전체 실행 결과
**29 passed** (2026-07-16 관측). 이 green 실행이 현 시점 G-1 통과의 근거다. 이 수치는 선언이
아니라 명령 재실행으로 재현·갱신되는 관측값이다.

## 4. L2 게이팅 (Req 8.1 · roadmap §게이트 G-1)

- **G-1 통과 = L2 착수 선행 조건 충족**: L2(`s05-workspace`) impl 착수의 전제 조건이 충족된다.
- **G-1 미통과 = L2 착수 차단**: 위 스위트 중 하나라도 실패하면 L2 impl 착수가 금지된다.
- roadmap 원칙(§게이트): 각 `integration-check-L{n}`은 바로 위 계층 impl 착수의 선행 조건이다.

## 5. 재검증 트리거 (Req 8.3 · design §Revalidation Triggers · roadmap §재검증 트리거)

이 체크포인트는 **재검증 트리거 규칙의 최초 소비 지점**이다. s01·s02·s03 중 **하나라도 아래
계약 표면이 수정되면**, 이 체크포인트 **및 로드맵상 이후 모든 체크포인트(L2~L6)**를 누적 집합
기준으로 **재실행**해야 한다. 재실행 시에도 mock 없이 실제 구현을 결합한 상태로 검증한다.

- **s01(계약) 수정 시** — 모든 체크포인트 재실행:
  - DB 스키마(컬럼·제약·ENUM·인덱스)
  - 공통 에러 응답·에러 코드 카탈로그
  - 세션 인증 의존성·권한 resolver 시그니처
  - `{Resource}Create/Read/Update` 규약·엔드포인트 카탈로그(경로·메서드·요구 role·소유권)
  - 불변식 카탈로그(INV-*)
- **s02(auth) 수정 시** — L1 및 이후 체크포인트 재실행:
  - 인증 엔드포인트 경로·메서드·인증 요구
  - 세션 write/clear·payload(세션 키)
  - 로그인 상태 게이트 규칙(비활동·삭제 거부)
  - 로그인/비밀번호 변경 실패의 에러 코드·상태 매핑
- **s03(admin-account) 수정 시** — L1 및 이후 체크포인트 재실행:
  - 계정관리 엔드포인트 경로·메서드·admin 요구·스키마 이름
  - 계정 상태(`is_active`/`is_deleted`) 표현·독립성
  - 비밀번호 재설정 동작

## 6. 실패 처리 원칙 (Req 1.4)

검증이 실패하면 **원인 upstream spec(s01/s02/s03)에서 수정하고 재실행**한다. 체크포인트는 계약·
경계 회귀를 **포착·보고만** 하며, 위반을 우회하기 위해 feature 로직이나 테스트 기대치를 바꾸지
않는다. 실패 유형별 지목:

- 계약 드리프트(스키마/API/에러 형태 불일치) → 계약 대조 스위트 실패 → 원인 spec 수정.
- 경계 회귀(상태 전이가 로그인 결과에 미반영) → 계정 생명주기↔로그인 스위트 실패 →
  상태 표현(s03)/상태 해석(s02) 중 원인 spec 수정.
- 불변식 위반(물리 삭제 발생) → INV-4 보존 스위트 실패 → s03 수정.

## 참조

- 요구사항: `.kiro/specs/s04-integration-check-L1/requirements.md` (Req 1.4, 8.1, 8.2, 8.3)
- 설계: `.kiro/specs/s04-integration-check-L1/design.md`
  (§Components → GateVerdict, §Boundary Commitments → Revalidation Triggers, §Testing Strategy → G-1 판정)
- 대조 기준 단일 소스: `.kiro/specs/s01-contract-foundation/design.md`
- 게이트·재검증 트리거: `.kiro/steering/roadmap.md` (§게이트 · §재검증 트리거)
