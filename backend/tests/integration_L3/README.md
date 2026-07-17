# L3 누적 통합 검증 체크포인트 (s08-integration-check-L3)

> 게이트 **G-1** 산출 지점(계층 3). 이 문서는 게이트 판정 기준과 재검증 트리거를 기록하는 참조 문서다.
> **판정은 이 문서가 선언하지 않는다.** 판정은 오직 `uv run pytest tests/integration_L3`의
> 재현 가능한 실행 결과로만 산출된다(design.md §GateVerdict: "판정은 실제 테스트 실행 결과로만
> 산출한다 — 수동 선언 금지"). 아래 서술은 그 명령이 권위(authority)이며, 이 문서는 그 명령의
> 기준·범위·후속 조치를 기록할 뿐이다.

## 1. 이 체크포인트는 무엇인가

L3 계층 경계에서 수행하는 **누적 통합 검증 체크포인트**다. 이 시점까지 완성된 upstream 누적 집합
**s01-contract-foundation ⊕ s02-auth ⊕ s03-admin-account ⊕ s05-workspace ⊕ s07-document-core**를
대상으로 다음을 검증한다. (주의: 이번 계층에서 **s07**이 새로 결합되며, `s04-integration-check-L1`·
`s06-integration-check-L2`는 이 체크포인트가 **재사용**하는 하네스일 뿐 검증 대상 feature 코드가 아니다 —
s04/s06의 feature 코드는 존재하지 않는다.)

- **계약 정합(Req 2)**: 결합된 시스템의 `document`·`document_version` 스키마 · 문서 CRUD·이동·삭제 API
  노출(카탈로그 18~23) · status 전이 계약(active→trashed→deleted, deleted 종착 INV-7, 물리 삭제 없음 INV-4) ·
  공통 에러 모델 · Base Schemas 규약(`DocumentRead`⊂`TimestampedRead`, `Page[DocumentRead]`)이 **s01
  단일 소스**와 일치하는가.
- **문서 권한 게이팅 INV-1·2·3(Req 3)**: `s01` `require_ws_role` resolver가 문서 라우트에서 `s05`가 채운
  **실제 workspace_member 데이터** 위에서 editor/viewer 위계를 계약대로 판정하는가 — editor 이상 변경 통과,
  viewer 변경 403(INV-2 읽기 전용)·조회 통과, 비멤버 403(INV-1), 비멤버 admin bypass(INV-3), 문서→WS
  어댑터가 문서 id로 workspace_id를 추출해 게이트(미존재 404·권한 미충족 403)하는가.
- **문서 계층·이동 정합 INV-5·6(Req 4)**: 같은 WS 내 이동·재정렬(중간 삽입 포함) 성공, 자기 자신·후손으로의
  이동 거부(INV-5 순환 방지), 다른 WS로의 이동 거부(INV-6 WS 경계 유지), 미존재·비active 부모 이동 거부.
- **bundle 삭제 캐스케이드·비흡수 INV-10·11(Req 5)**: `DELETE /documents/{id}`가 그 시점 active 하위만
  묶음으로 포착(6.2)하고 공통 `trashed_at`을 부여, 이미 trashed된 자식을 흡수하지 않으며(6.4, INV-11) 독립
  묶음으로 식별(6.3), `child.trashed_at ≤ parent.trashed_at` 성립, 비active 재삭제 409, 단일 원자적 전이·물리
  보존(INV-4·10).
- **bundle 복구·완전삭제 정합 INV-10·12(Req 6)**: 엔진 복구 primitive가 복구 위치를 루트 부모 상태로 결정
  (부모 active면 부모 밑 sort_order 원위치, non-active/부재면 root 맨 뒤; 6.5.1/6.5.2/6.7), 완전삭제가 묶음
  단위로 원자적(INV-10)이며 다른 독립 묶음은 불변(INV-12), 상태 전이가 편집 잠금과 독립(§4.3). 복구·완전삭제
  API는 L4(s10)에만 존재하므로 `DocumentStateEngine` primitive 직접 호출로 **s10 소비 계약을 선검증**한다.
- **결합 엣지케이스(Req 7)**: `trashed_at` 초 단위(`DATETIME(0)`) 경계에서 묶음 멤버십이 오병합 없이 유지됨
  (s07 flagged Risk), 삭제(`is_deleted=true`) 처리된 사용자(L1)의 이름·`created_by`가 문서 작성자 표시로 보존됨
  (INV-4), 문서를 하나라도 보유한 워크스페이스의 삭제가 409로 거부(FK `ON DELETE RESTRICT`)되고 빈 워크스페이스
  삭제는 성공(s05 삭제 ↔ s07 문서 존재 경계).

대조의 유일한 기준은 개별 spec(s02·s03·s05·s07) design이 아니라 **s01 단일 소스**
(§Physical Data Model `document`·`document_version` · §API Endpoint Catalog 18~23 · §Errors 코드 카탈로그 ·
§Invariants Catalog INV-1·2·3·4·5·6·10·11·12 · §Common/Permissions `Role`·`require_ws_role`·admin bypass ·
§Base Schemas)다(Req 1.2).

**mock 없음(Req 1.1)**: 모든 검증은 실제 결합 상태 — 마이그레이션이 적용된 실제 MySQL 8 +
`create_app()`로 부팅된 실제 애플리케이션(s02·s03·s05·**s07 문서 라우터 조립**) + 실제 서명 쿠키 세션 +
실제 `workspace_member`·`document` 데이터 + 실제 `DocumentStateEngine` — 에서 수행한다. stub·가짜 구현을
쓰지 않는다. 엔진 primitive 직접 호출은 실제 s07 코드 실행이므로 mock이 아니다.

**feature 미구현(Req 1.3)**: 이 체크포인트는 어떤 엔드포인트·서비스·스키마·마이그레이션·상태 엔진도 신규로
구현하지 않는다. 소유물은 `tests/integration_L3/` 테스트 자산과 본 문서(게이트 기록)뿐이며, `s04`
`tests/integration_L1/`·`s06` `tests/integration_L2/` 하네스는 **재사용**한다(무수정, Req 1.4).

## 2. 검증되는 것 (Req 2~7 스위트)

| 요구 | 검증 관심사 | 스위트 파일 |
|------|-------------|-------------|
| Req 2 | 계약 대조(document·document_version 스키마·API 18~23·status 전이·에러 모델·Base 규약) | `test_document_contract_conformance.py` |
| Req 3 | 문서 권한 게이팅 INV-1·2·3(editor/viewer 게이트·비멤버 차단·admin bypass·문서→WS 어댑터) | `test_document_permission_gating.py` |
| Req 4 | 문서 계층·이동 INV-5·6(같은 WS 이동/재정렬·순환 거부·타 WS 거부·중간 삽입·부모 검증) | `test_document_hierarchy_move.py` |
| Req 5 | bundle 삭제 캐스케이드 INV-10·11(active만 포착·비흡수·독립 묶음·비active 재삭제 409·원자성) | `test_bundle_delete_cascade.py` |
| Req 6 | bundle 복구·완전삭제 INV-10·12(복구 위치·sort_order·완전삭제 원자성·묶음 독립·상태/잠금 독립) | `test_bundle_restore_purge.py` |
| Req 7 | 결합 엣지케이스(trashed_at 초 단위 묶음 경계·삭제 사용자 작성자 보존·문서 보유 WS 삭제 거부) | `test_combination_edge.py` |

> 위 6개 스위트가 Req 2~7을 담당하며, `test_harness_smoke.py`·`test_helpers_smoke.py`는 L3 하네스
> (L2 하네스 재사용 + 문서 트리·엔진 세션 픽스처, 문서/엔진 primitive 호출 헬퍼)의 자체 점검이다. 게이트
> 판정은 스위트 전체(전체 `tests/integration_L3`)의 실행 결과로 집계된다.

## 3. 실행 방법

```bash
# backend/ 디렉터리에서
uv run pytest tests/integration_L3
```

**전제 조건**: 실제 MySQL 8이 가용해야 하며 Alembic 마이그레이션(`uv run alembic upgrade head`
상당)이 하네스(`conftest.py` — L2/L1 하네스 재사용)에 의해 적용된다. 부팅 앱은 s02·s03·s05·**s07 문서
라우터가 조립된 상태**여야 한다(문서 CRUD·이동·삭제 라우트 노출). **DB 미가용·부팅 앱 미충족은 스킵이
아니라 실패(FAILURE)로 처리한다** — 미검증이 통과로 오인되는 것을 막기 위함이다(Req 8.4, design §Error
Handling · GateVerdict).

## 4. G-1 게이트 판정 기준 (Req 8.1, 8.2)

- **G-1 통과 조건**: `uv run pytest tests/integration_L3` 전체(Requirement 2~7 스위트 — §2 표의 6개
  스위트)가 **전부 green**이면 G-1 통과다(Req 8.1).
- **G-1 미통과 조건**: 위 실행에서 **하나라도 실패하면** G-1 미통과이며, L4(`s09-lock-version`·`s10-trash`)
  impl 착수는 **차단**된다(Req 8.2).
- **판정의 권위**: 판정은 이 문서의 선언이 아니라 위 명령의 실행 결과에서 **파생(derived)**된다.
  전부 통과한 실행 그 자체가 곧 판정이다(design §GateVerdict — 수동 선언 금지).

**현재 근거(latest basis)**: `uv run pytest tests/integration_L3` 최신 전체 실행 결과
**64 passed** (`64 passed, 789 warnings in 68.53s`, 2026-07-17 관측). 누적 집합 무회귀 확인용
`uv run pytest tests/integration_L1 tests/integration_L2`는 **87 passed** (29 L1 + 58 L2, 2026-07-17
관측), 원인 spec s05 회귀 확인용 `uv run pytest tests/workspace`는 **141 passed** (2026-07-17 관측)으로
하위 계층·수정 대상 spec의 회귀가 없음을 함께 확인한다. 이 green 실행이 현 시점 G-1 통과의 근거다. 이
수치는 선언이 아니라 명령 재실행으로 재현·갱신되는 **관측값**이다.

## 5. L4 게이팅 (Req 8.1 · roadmap §게이트 G-1)

- **G-1 통과 = L4 착수 선행 조건 충족**: L4(`s09-lock-version`·`s10-trash`) impl 착수의 전제 조건이 충족된다.
  특히 s10은 L3에서 선검증된 `DocumentStateEngine` 복구·완전삭제·묶음 열거 primitive 재사용 계약 위에 휴지통
  API를 얹으므로, 이 게이트 통과는 s10 소비 계약이 라우터 밖에서 불변식을 유지함을 확인한 상태를 보장한다.
- **G-1 미통과 = L4 착수 차단**: 위 스위트 중 하나라도 실패하면 L4 impl 착수가 금지된다.
- roadmap 원칙(§게이트): 각 `integration-check-L{n}`은 바로 위 계층 impl 착수의 선행 조건이다.

## 6. 재검증 트리거 (Req 8.3 · design §Revalidation Triggers · roadmap §재검증 트리거)

s01·s02·s03·s05·**s07** 중 **하나라도 아래 계약 표면이 수정되면**, 이 체크포인트 **및 로드맵상 이후 모든
체크포인트(L4~L6)**를 누적 집합 기준으로 **재실행**해야 한다. 재실행 시에도 mock 없이 실제 구현을 결합한
상태로 검증한다. **s01(계약) 수정 시에는 모든 체크포인트(L1~L6)를 재실행**한다.

- **s01(계약) 수정 시** — 모든 체크포인트 재실행:
  - `document`·`document_version` 스키마(컬럼·제약·ENUM·인덱스), **`trashed_at` 물리 정밀도**(현 `DATETIME(0)`)
  - 권한 resolver(`Role` 위계·`require_ws_role`·admin bypass) 시그니처·판정 규칙
  - 세션 인증 의존성(`get_current_user`/`AuthContext`)
  - 공통 에러 응답·에러 코드 카탈로그
  - `{Resource}Create/Read/Update`·`Page[T]`·`ErrorResponse` 규약·엔드포인트 카탈로그(행 18~23: 경로·메서드·요구 role)
  - 불변식 카탈로그(INV-1·2·3·4·5·6·10·11·12)
- **s02(auth) 수정 시** — L3 및 이후 체크포인트 재실행(작성자 삭제 후 로그인 게이트 검증에 영향):
  - 로그인 상태 게이트·세션 write/clear·payload 키
  - 로그인/비밀번호 변경 실패의 에러 코드·상태 매핑
- **s03(admin-account) 수정 시** — L3 및 이후 체크포인트 재실행(작성자 삭제 시 보존 검증에 영향):
  - 계정 상태(`is_active`/`is_deleted`) 표현·독립성·전이 동작
  - 비밀번호 재설정 동작
- **s05(workspace) 수정 시** — L3 및 이후 체크포인트 재실행(문서 게이팅 판정 근거·WS 삭제 경계에 영향):
  - `workspace_member` role 판정 데이터 계약 · resolver 활성화 방식
  - 워크스페이스 삭제(`DELETE /workspaces/{id}`, 행 14) 의미·원자성(멤버십·워크스페이스 단일 트랜잭션)
- **s07(document-core) 수정 시** — L3 및 이후 체크포인트 재실행(이번 계층 신규 결합):
  - 상태 엔진 primitive 시그니처·의미(삭제 캐스케이드 포착 범위·복구 위치 규칙·완전삭제 원자성·묶음 식별 방식):
    `trash_document`·`restore_bundle`·`purge_bundle`·`identify_bundles`·`get_bundle`·`active_descendants`·`Bundle` DTO
  - 문서 CRUD·이동·삭제 엔드포인트 경로·메서드·요구 role·스키마 이름(카탈로그 18~23)
  - 이동 규칙 판정 기준(순환 방지·WS 경계·중간 삽입 정렬)
  - 문서→WS 어댑터 게이팅 방식, markdown 렌더 규약

## 7. 실패 처리 원칙 — origin-spec 수정 (Req 1.5 · design §Out of Boundary)

검증이 실패하면 **원인 upstream spec(s01/s02/s03/s05/s07)에서 수정하고 재실행**한다. 체크포인트는 계약·
경계 회귀를 **포착·보고만** 하며, 위반을 우회하기 위해 feature 로직이나 테스트 기대치를 바꾸지 않는다.
실패 유형별 지목:

- 계약 드리프트(문서 스키마/API 18~23/에러 형태/status ENUM 불일치) → 계약 대조 스위트 실패 → s01(스키마·카탈로그)
  또는 원인 spec 수정.
- 권한 게이팅 회귀(editor/viewer 게이트·viewer 읽기 전용·비멤버 차단·admin bypass·어댑터 404/403 불성립) →
  게이팅 스위트 실패 → resolver 판정(s01)·문서→WS 어댑터(s07)·멤버십 데이터(s05) 중 원인 spec 수정.
- 계층/이동 회귀(순환 미차단 INV-5·타 WS 이동 허용 INV-6·중간 삽입 오작동) → 이동 스위트 실패 → s07 수정.
- 캐스케이드/비흡수 회귀(active 외 포착·이미 trashed 흡수·묶음 병합·비active 재삭제 미차단) → 캐스케이드
  스위트 실패 → s07 엔진 수정.
- 복구/완전삭제 회귀(복구 위치 오판·sort_order 미복원·완전삭제 비원자·묶음 간섭·상태/잠금 결합) → 복구·완전삭제
  스위트 실패 → s07 엔진 수정.
- 엣지케이스 회귀(초 단위 묶음 오병합·작성자 소실·물리 삭제 발생·문서 보유 WS 삭제 허용) → 엣지케이스 스위트
  실패 → s07(엔진)·s03/s02(작성자·로그인)·s05(WS 삭제) 중 원인 spec 수정.

### 7.1 실증 사례 — s05 워크스페이스 삭제 원자성 결함 포착·원인 spec 수정

이 체크포인트가 origin-spec 라우팅 정책을 실제로 적용한 사례를 기록한다(tasks.md task 2.6 → Implementation Notes).

- **포착**: L3 7.5(문서 보유 워크스페이스 삭제 409 거부·물리 보존) 검증이 **s05 실 결함**을 노출했다.
  `WorkspaceService.delete_workspace`가 멤버십 제거(`remove_all_for_workspace` 내부 commit)를 워크스페이스
  물리 삭제 **이전에 커밋**해, 비-empty(문서 보유) 워크스페이스 삭제가 FK `ON DELETE RESTRICT`
  IntegrityError→rollback 될 때 이미 커밋된 멤버십 제거는 되돌지 못했다 → 409 응답인데도 멤버십(오너 포함)이
  물리 소실되는 데이터 손실. s05 design §Invariants "단일 서비스 트랜잭션" 위반.
- **원인 spec(s05)에서 수정 — 체크포인트에서 우회하지 않음**: `remove_all_for_workspace`·
  `WorkspaceRepository.delete`에 `commit: bool = True`를 추가하고 서비스가 둘을 `commit=False`로 호출한 뒤 try
  안에서 단일 `db.commit()`으로 묶었다 → 비-empty는 한 번의 rollback으로 멤버십 복원(아무것도 제거 안 됨),
  empty는 204. FK RESTRICT를 거부 트리거로 유지(문서 카운트 선검사 미도입). s05 단위 테스트 fake가 독립 commit을
  모델링하지 않아 통과했던 fidelity gap을 L3 mock-free 실 DB 오라클이 노출했다.
- **재검증 파급**: s05 수정이므로 이 체크포인트 및 이후 체크포인트를 누적 집합 기준으로 재실행했다(§6). 위 §4의
  `tests/workspace` 141 passed가 수정된 s05 자체 스위트의 green을, L3 64 passed가 결합 검증의 green을 확인한다.

## 8. 미래 s01 계약 개정 후보 — trashed_at DATETIME(0) 정밀도 (Req 7.2)

`trashed_at`은 `sa.DateTime()` → MySQL `DATETIME(0)`으로 저장되어 소수 초를 (버림이 아니라) **반올림**한다.
서로 다른 삭제 조작이 **저장된** `trashed_at`에서 동일 초로 반올림되면 묶음 재구성이 독립 묶음을 오병합할 수
있다. 이 체크포인트(task 2.6 / `test_combination_edge.py`)는 자식의 저장된 `trashed_at` + 2s 여유만큼 대기한
뒤 부모를 삭제하는 margin-based 방식으로 경계를 **오병합 없이** 확정하며, 현 시점 이 검증은 **통과**한다
(현재 실패가 아님). 초 단위 경계에서 독립 묶음 병합 회귀가 **관측되면**, Req 7.2에 따라 이를 실패로 보고하고
`trashed_at` 정밀도 승격(예: `DATETIME(6)`)을 **`s01` 계약 개정 대상**(전 체크포인트 재검증 동반)으로 기록한다.
체크포인트는 이 정밀도를 스스로 바꾸지 않는다 — 이는 문서화된 **미래 s01-contract-revision 후보**이지 현재
게이트 실패가 아니다.

## 9. 현재 판정 (verdict, 2026-07-17 관측)

**게이트 통과 — 64 passed.** L4(`s09-lock-version`·`s10-trash`) impl 착수 선행 조건 충족.

| 실행 | 명령 | 요약 |
|------|------|------|
| L3 게이트(권위) | `uv run pytest tests/integration_L3` | `64 passed, 789 warnings in 68.53s` |
| 누적 무회귀(L1+L2) | `uv run pytest tests/integration_L1 tests/integration_L2` | `87 passed, 489 warnings in 66.05s` (29 L1 + 58 L2) |
| 수정 대상 s05 무회귀 | `uv run pytest tests/workspace` | `141 passed, 150 warnings in 20.25s` |

> 이 수치는 명령 재실행으로 재현·갱신되는 관측값이다. upstream(s01·s02·s03·s05·s07) 수정 시 §6 재검증
> 트리거에 따라 재실행하고 본 §9 판정을 최신 관측으로 갱신한다.

## 참조

- 요구사항: `.kiro/specs/s08-integration-check-L3/requirements.md` (Req 1.5, 8.1, 8.2, 8.3, 8.4)
- 설계: `.kiro/specs/s08-integration-check-L3/design.md`
  (§Components → GateVerdict, §Boundary Commitments → Revalidation Triggers, §계약 대조 판정, §Testing Strategy)
- 대조 기준 단일 소스: `.kiro/specs/s01-contract-foundation/design.md`
  (§Physical Data Model `document`·`document_version` · §API Endpoint Catalog 18~23 · §Errors ·
  §Invariants Catalog INV-1·2·3·4·5·6·10·11·12 · §Common/Permissions · §Base Schemas)
- 검증 대상 동작: `.kiro/specs/s07-document-core/design.md` (`DocumentStateEngine`·`DocumentWsAdapter`·
  삭제 캐스케이드·복구·완전삭제·묶음 식별·정밀도 Risk)
- 재사용 하네스: `.kiro/specs/s06-integration-check-L2/design.md`·`backend/tests/integration_L2/`,
  및 그것이 재사용하는 `.kiro/specs/s04-integration-check-L1/design.md`·`backend/tests/integration_L1/`
- 게이트·재검증 트리거: `.kiro/steering/roadmap.md` (§게이트 · §재검증 트리거)
