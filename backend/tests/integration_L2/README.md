# L2 누적 통합 검증 체크포인트 (s06-integration-check-L2)

> 게이트 **G-1** 산출 지점(계층 2). 이 문서는 게이트 판정 기준과 재검증 트리거를 기록하는 참조 문서다.
> **판정은 이 문서가 선언하지 않는다.** 판정은 오직 `uv run pytest tests/integration_L2`의
> 재현 가능한 실행 결과로만 산출된다(design.md §GateVerdict: "판정은 실제 테스트 실행 결과로만
> 산출한다 — 수동 선언 금지"). 아래 서술은 그 명령이 권위(authority)이며, 이 문서는 그 명령의
> 기준·범위·후속 조치를 기록할 뿐이다.

## 1. 이 체크포인트는 무엇인가

L2 계층 경계에서 수행하는 **누적 통합 검증 체크포인트**다. 이 시점까지 완성된 upstream 누적 집합
**s01-contract-foundation ⊕ s02-auth ⊕ s03-admin-account ⊕ s05-workspace**를 대상으로 다음을 검증한다.
(주의: 이번 계층에서 **s05**가 새로 결합되며, `s04-integration-check-L1`은 이 체크포인트가 **재사용**하는
L1 하네스일 뿐 검증 대상 feature 코드가 아니다 — s04의 feature 코드는 존재하지 않는다.)

- **계약 정합(Req 2)**: 결합된 시스템의 `workspace`·`workspace_member` 스키마 · 워크스페이스/멤버십/소유권
  API 노출(카탈로그 9~17) · 공통 에러 모델 · Base Schemas 규약이 **s01 단일 소스**와 일치하는가.
- **권한 경계 INV-1·2(Req 3)**: `s01` `require_ws_role` resolver가 `s05`가 채운 **실제 workspace_member
  데이터** 위에서 owner/editor/viewer 위계를 계약대로 판정하는가 — viewer 게이트 role별 통과, viewer 읽기
  전용(owner 게이트 403), editor 중간 위계, 비멤버 차단.
- **admin override INV-3(Req 4)**: admin이 자신이 멤버가 아닌 워크스페이스의 viewer·owner 게이트를 모두
  bypass하고 전체 목록 가시성을 가지는가.
- **admin 소유권 변경(Req 5)**: admin이 소유권을 변경(upsert-to-owner)하면 새 owner가 owner 게이트를
  통과하고, 비-admin은 403, 미존재 대상은 404로 거부되는가.
- **계정상태 ↔ 멤버십 결합 INV-4(Req 6)**: 유일 owner 비활동/삭제(s03) 시 타 멤버 활동이 무영향인가,
  삭제/비활동 멤버의 `workspace_member` 행·사용자 이름이 물리 삭제 없이 보존되며 로그인은 401(s02)인가.
- **워크스페이스 설정(Req 7)**: owner/admin이 `is_shareable`·`trash_retention_days`를 설정하면 실제 결합
  상태에 반영·조회되고, 0 이하 retention은 422로 거부되며, 생성 기본값(`is_shareable=false`·s01 `Settings`
  retention)이 성립하는가.

대조의 유일한 기준은 개별 spec(s02·s03·s05) design이 아니라 **s01 단일 소스**
(§Physical Data Model `workspace`·`workspace_member` · §API Endpoint Catalog 9~17 · §Errors 코드 카탈로그 ·
§Invariants Catalog INV-1·2·3·4 · §Common/Permissions `Role`·`require_ws_role`·admin bypass)다(Req 1.2).

**mock 없음(Req 1.1)**: 모든 검증은 실제 결합 상태 — 마이그레이션이 적용된 실제 MySQL 8 +
`create_app()`로 부팅된 실제 애플리케이션(s02·s03·**s05 라우터 조립**) + 실제 서명 쿠키 세션 + 실제
`workspace_member` 데이터 — 에서 수행한다. stub·가짜 구현을 쓰지 않는다.

**feature 미구현(Req 1.3)**: 이 체크포인트는 어떤 엔드포인트·서비스·스키마·마이그레이션도 신규로
구현하지 않는다. 소유물은 `tests/integration_L2/` 테스트 자산과 본 문서(게이트 기록)뿐이며, `s04`
`tests/integration_L1/` 하네스는 **재사용**한다(무수정, Req 1.4).

## 2. 검증되는 것 (Req 2~7 스위트)

| 요구 | 검증 관심사 | 스위트 파일 |
|------|-------------|-------------|
| Req 2 | 계약 대조(스키마·API 9~17·에러 모델·Base 규약) | `test_workspace_contract_conformance.py` |
| Req 3 | 권한 경계 INV-1·2(role 위계·viewer 읽기전용·비멤버 차단) | `test_permission_boundary.py` |
| Req 4 | admin override INV-3(비멤버 WS bypass·전체 목록) | `test_admin_override.py` |
| Req 5 | admin 소유권 변경(upsert-to-owner·새 owner 권한·403·404) | `test_owner_change.py` |
| Req 6 | 계정상태 ↔ 멤버십 결합 INV-4(무영향·보존·로그인 401) | `test_account_state_membership.py` |
| Req 7 | 워크스페이스 설정(is_shareable·retention·기본값·admin bypass) | `test_workspace_settings.py` |

> 위 6개 스위트가 Req 2~7을 담당하며, `test_harness_smoke.py`·`test_helpers_smoke.py`는 L2 하네스
> (L1 하네스 재사용 + 워크스페이스 시나리오 헬퍼)의 자체 점검이다. 게이트 판정은 스위트 전체
> (전체 `tests/integration_L2`)의 실행 결과로 집계된다.

## 3. 실행 방법

```bash
# backend/ 디렉터리에서
uv run pytest tests/integration_L2
```

**전제 조건**: 실제 MySQL 8이 가용해야 하며 Alembic 마이그레이션(`uv run alembic upgrade head`
상당)이 하네스(`conftest.py` — L1 하네스 재사용)에 의해 적용된다. **DB 미가용은 스킵이 아니라 실패
(FAILURE)로 처리한다** — 미검증이 통과로 오인되는 것을 막기 위함이다(design §Error Handling ·
L2TestHarness Validation).

## 4. G-1 게이트 판정 기준 (Req 8.1, 8.2)

- **G-1 통과 조건**: `uv run pytest tests/integration_L2` 전체(Requirement 2~7 스위트 — §2 표의 6개
  스위트)가 **전부 green**이면 G-1 통과다(Req 8.1).
- **G-1 미통과 조건**: 위 실행에서 **하나라도 실패하면** G-1 미통과이며, L3(`s07-document-core`)
  impl 착수는 **차단**된다(Req 8.2).
- **판정의 권위**: 판정은 이 문서의 선언이 아니라 위 명령의 실행 결과에서 **파생(derived)**된다.
  전부 통과한 실행 그 자체가 곧 판정이다(design §GateVerdict — 수동 선언 금지).

**현재 근거(latest basis)**: `uv run pytest tests/integration_L2` 최신 전체 실행 결과
**43 passed** (2026-07-16 관측). 누적 집합 확인용 `uv run pytest tests/integration_L2 tests/integration_L1`은
**72 passed** (43 L2 + 29 L1, 2026-07-16 관측)으로 L1 회귀가 없음을 함께 확인한다. 이 green 실행이
현 시점 G-1 통과의 근거다. 이 수치는 선언이 아니라 명령 재실행으로 재현·갱신되는 **관측값**이다.

## 5. L3 게이팅 (Req 8.1 · roadmap §게이트 G-1)

- **G-1 통과 = L3 착수 선행 조건 충족**: L3(`s07-document-core`) impl 착수의 전제 조건이 충족된다.
- **G-1 미통과 = L3 착수 차단**: 위 스위트 중 하나라도 실패하면 L3 impl 착수가 금지된다.
- roadmap 원칙(§게이트): 각 `integration-check-L{n}`은 바로 위 계층 impl 착수의 선행 조건이다.

## 6. 재검증 트리거 (Req 8.3 · design §Revalidation Triggers · roadmap §재검증 트리거)

s01·s02·s03·**s05** 중 **하나라도 아래 계약 표면이 수정되면**, 이 체크포인트 **및 로드맵상 이후 모든
체크포인트(L3~L6)**를 누적 집합 기준으로 **재실행**해야 한다. 재실행 시에도 mock 없이 실제 구현을
결합한 상태로 검증한다. **s01(계약) 수정 시에는 모든 체크포인트(L1~L6)를 재실행**한다.

- **s01(계약) 수정 시** — 모든 체크포인트 재실행:
  - DB 스키마(`workspace`·`workspace_member` 포함, 컬럼·제약·ENUM·인덱스)
  - 권한 resolver(`Role` 위계·`require_ws_role`·admin bypass) 시그니처·판정 규칙
  - 세션 인증 의존성(`get_current_user`/`AuthContext`)
  - 공통 에러 응답·에러 코드 카탈로그
  - `{Resource}Create/Read/Update`·`Page[T]` 규약·엔드포인트 카탈로그(행 9~17: 경로·메서드·요구 role·소유권)
  - 불변식 카탈로그(INV-1·2·3·4)
- **s02(auth) 수정 시** — L2 및 이후 체크포인트 재실행(계정상태↔멤버십 결합에 영향):
  - 인증 엔드포인트 경로·메서드·인증 요구
  - 세션 write/clear·payload(세션 키)
  - 로그인 상태 게이트 규칙(비활동·삭제 거부 → 멤버 로그인 401)
  - 로그인/비밀번호 변경 실패의 에러 코드·상태 매핑
- **s03(admin-account) 수정 시** — L2 및 이후 체크포인트 재실행(유일 owner 전이에 영향):
  - 계정관리 엔드포인트 경로·메서드·admin 요구·스키마 이름
  - 계정 상태(`is_active`/`is_deleted`) 표현·독립성·전이 동작
  - 비밀번호 재설정 동작
- **s05(workspace) 수정 시** — L2 및 이후 체크포인트 재실행(이번 계층 신규 결합):
  - 워크스페이스/멤버십 엔드포인트 경로·메서드·요구 role·스키마 이름
    (`/workspaces` 생성·목록·상세·수정·삭제, `/workspaces/{id}/members` 추가·변경·제거)
  - `workspace_member` role 판정 데이터 계약 · resolver 활성화 방식
    (admin만 통과하던 상태 → 실제 role 판정으로의 전환)
  - 소유권 변경 의미(`POST /admin/workspaces/{id}/owner`, upsert-to-owner)
  - `is_shareable`·`trash_retention_days` 설정 규약(기본값·검증 경계 포함)

## 7. 실패 처리 원칙 (Req 1.5)

검증이 실패하면 **원인 upstream spec(s01/s02/s03/s05)에서 수정하고 재실행**한다. 체크포인트는 계약·
경계 회귀를 **포착·보고만** 하며, 위반을 우회하기 위해 feature 로직이나 테스트 기대치를 바꾸지
않는다. 실패 유형별 지목:

- 계약 드리프트(워크스페이스 스키마/API/에러 형태 불일치) → 계약 대조 스위트 실패 → s01(스키마·카탈로그)
  또는 원인 spec 수정.
- 권한 경계 회귀(role 위계·viewer 읽기전용·비멤버 차단 불성립) → 권한 경계 스위트 실패 →
  resolver 판정(s01) 또는 멤버십 데이터(s05) 중 원인 spec 수정.
- admin bypass 회귀(비멤버 admin이 게이트에서 차단됨) → admin override 스위트 실패 → s01(resolver bypass)
  또는 s05(게이트 부착) 수정.
- 소유권 변경 회귀(새 owner 권한 미반영·403/404 미성립) → 소유권 변경 스위트 실패 → s05 수정.
- 계정↔멤버십 결합 회귀(타 멤버 영향·멤버십/이름 소실·삭제 멤버 로그인 허용) → 계정상태↔멤버십 스위트
  실패 → 상태 표현/전이(s03)·상태 해석(s02)·멤버십(s05) 중 원인 spec 수정.
- 불변식 위반(물리 삭제 발생, INV-4) → 계정상태↔멤버십 스위트 실패 → s03/s05 수정.
- 설정 회귀(설정 미반영·기본값 불일치·admin bypass 실패) → 설정 스위트 실패 → s05 수정.

## 참조

- 요구사항: `.kiro/specs/s06-integration-check-L2/requirements.md` (Req 1.5, 8.1, 8.2, 8.3)
- 설계: `.kiro/specs/s06-integration-check-L2/design.md`
  (§Components → GateVerdict, §Boundary Commitments → Revalidation Triggers, §Testing Strategy → G-1 판정)
- 대조 기준 단일 소스: `.kiro/specs/s01-contract-foundation/design.md`
  (§Physical Data Model `workspace`·`workspace_member` · §API Endpoint Catalog 9~17 · §Errors ·
  §Invariants Catalog INV-1·2·3·4 · §Common/Permissions)
- 재사용 하네스: `.kiro/specs/s04-integration-check-L1/design.md` · `backend/tests/integration_L1/`
- 게이트·재검증 트리거: `.kiro/steering/roadmap.md` (§게이트 · §재검증 트리거)
