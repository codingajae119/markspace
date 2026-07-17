# L4 누적 통합 검증 체크포인트 (s11-integration-check-L4)

> 게이트 **G-1** 산출 지점(계층 4). 이 문서는 게이트 판정 기준과 재검증 트리거를 기록하는 참조 문서다.
> **판정은 이 문서가 선언하지 않는다.** 판정은 오직 `uv run pytest tests/integration_L4`의
> 재현 가능한 실행 결과로만 산출된다(design.md §GateVerdict: "게이트 판정 결과는 테스트 실행 결과로
> 산출된다 — 전부 통과 = 게이트 통과, 수동 선언 금지"). 아래 서술은 그 명령이 권위(authority)이며,
> 이 문서는 그 명령의 기준·범위·후속 조치를 기록할 뿐이다.

## 1. 이 체크포인트는 무엇인가

L4 계층 경계에서 수행하는 **누적 통합 검증 체크포인트**다. 이 시점까지 완성된 upstream 누적 집합
**s01-contract-foundation ⊕ s02-auth ⊕ s03-admin-account ⊕ s05-workspace ⊕ s07-document-core ⊕
s09-lock-version ⊕ s10-trash**를 대상으로 다음을 검증한다. (주의: 이번 계층에서 **s09**·**s10**이 새로
결합되며, `s04-integration-check-L1`·`s06-integration-check-L2`·`s08-integration-check-L3`은 이
체크포인트가 **재사용**하는 하네스일 뿐 검증 대상 feature 코드가 아니다 — s04/s06/s08의 feature 코드는
존재하지 않는다.)

- **누적 계약 정합(Req 2)**: 결합된 시스템의 `document` lock 컬럼(`lock_user_id`·`lock_acquired_at`·
  `current_version_id`)·`document_version` 스키마 · 잠금·버전·휴지통 API 노출(카탈로그 24~31) ·
  공통 에러 모델 · Base Schemas 규약(`DocumentLockRead`·`DocumentVersionRead`·`TrashBundleRead`,
  `Page[T]`) · additive `trash_sweep_interval_seconds` Settings 로딩 · APScheduler 결합 부팅이 **s01
  단일 소스**와 일치하고 s09·s10이 새 마이그레이션을 추가하지 않았는가.
- **잠금·버전 흐름 INV-9(Req 3)**: 두 editor(A·B)·owner·viewer·비멤버·admin 결합 위에서 잠금 시작 →
  타인 차단(409, 문서당 최대 1인) → 저장(새 버전 생성·`current_version_id` 갱신·잠금 해제, 원자 결과) →
  취소(버전 미생성) → 강제해제(owner/admin만, editor 403) → 타임아웃 없음(명시적 해제로만) → 버전 무한
  누적(rollback/과거 본문 조회 경로 부재) → role 게이팅(INV-1·2·3)이 실제 세션·멤버십 위에서 성립하는가.
- **휴지통 흐름 INV-2·10(Req 4)**: `GET /workspaces/{id}/trash`가 WS 전체 trashed 묶음만 `expires_at`
  포함 반환, `restore_bundle` 위임 복구(복구 위치 = 복구 시점 루트 부모 상태), `purge_bundle` 위임
  완전삭제(원자적 deleted 종착·물리 보존·요청 묶음에만 적용), viewer/비멤버 403(INV-1·2)·admin bypass
  (INV-3), 문서 부재 bundleId 404가 실제 라우터+엔진+DB 관찰로 성립하는가.
- **잠금↔삭제 독립 §4.3(Req 5)**: 잠긴 문서를 trashed 전이해도 `lock_user_id`가 상태 전이로 변경되지
  않음, trashed 문서에 잠금/저장/취소가 status를 검사하지 않고 작동(상태 전이 미유발), s10 복구·완전삭제·
  스윕이 status/trashed_at을 직접 갱신하지 않고 s07 엔진 primitive에 위임(lock 필드 불변), s09·s10 라우트가
  권한 판정을 재구현하지 않고 s01 `require_ws_role`·s07 어댑터를 재사용, 잠금 유무와 무관한 완전삭제/복구가
  성립하는가.
- **묶음 보관 타이머 독립성 INV-12(Req 6)**: `now` 주입 `RetentionSweepService.sweep_expired_bundles`가
  `trashed_at + retention <= now` 묶음만 deleted 전환(미만료 불변), 만료 처리가 타 묶음에 무영향, 자식
  묶음 선만료 수용, 멱등(이미 처리 묶음 skip·중복 전이/예외 전파 없음), WS별 `trash_retention_days` 독립
  적용, 실제 purge DB 관찰(물리 삭제 부재)·엔진 `identify_bundles`/`purge_bundle` 의존이 성립하는가.
- **아래 계층 결합 엣지(Req 7)**: role별 잠금·버전·휴지통 라우트 접근 경계가 아래 계층(s02 세션·s05
  멤버십) 결합 위에서 성립(viewer 변경 거부 INV-2·비멤버 차단 INV-1·admin 비멤버 WS 전면 접근 INV-3),
  삭제(`is_deleted=true`) 처리된 사용자의 `created_by`·이름이 문서·버전에서 물리 보존되고 삭제 사용자의
  후속 잠금·저장 요청이 401 로그인 게이트로 차단됨(INV-4), 잠금·저장·취소·강제해제·복구·완전삭제·스윕
  전반에서 `document`·`document_version`·`user` 물리 삭제 부재(INV-4)가 API+엔진+스윕+DB 관찰로 성립하는가.

대조의 유일한 기준은 개별 spec(s02·s03·s05·s07·s09·s10) design이 아니라 **s01 단일 소스**
(§Physical Data Model `document` lock 필드·`document_version` · §API Endpoint Catalog 24~31 ·
§Errors 코드 카탈로그 · §Invariants Catalog INV-1·2·3·4·7·9·10·11·12 · §Common/Permissions
`Role`·`require_ws_role`·admin bypass · §Base Schemas · §Settings `default_trash_retention_days` +
additive 확장)다(Req 1.2).

**mock 없음(Req 1.1)**: 모든 검증은 실제 결합 상태 — 마이그레이션이 적용된 실제 MySQL 8 +
`create_app()`로 부팅된 실제 애플리케이션(s02·s03·s05·s07 + **s09 잠금·버전 라우터 + s10 휴지통
라우터·APScheduler 스케줄러 조립**) + 실제 서명 쿠키 세션 + 실제 `workspace_member`·`document`·
`document_version`·lock 필드 데이터 + 실제 `DocumentStateEngine` + 실제 `RetentionSweepService` — 에서
수행한다. stub·가짜 구현을 쓰지 않는다. 엔진·스윕 서비스 직접 호출(`now` 주입 포함)은 실제 s07·s10 코드
실행이므로 mock이 아니다.

**feature 미구현(Req 1.3)**: 이 체크포인트는 어떤 엔드포인트·서비스·스키마·마이그레이션·상태 엔진·스윕
서비스도 신규로 구현하지 않는다. 소유물은 `tests/integration_L4/` 테스트 자산과 본 문서(게이트 기록)뿐이며,
`s08` `tests/integration_L3/`(및 그것이 재사용하는 L2/L1) 하네스는 **재사용·확장**한다(하위 하네스 무수정,
Req 1.4).

## 2. 검증되는 것 (Req 2~7 스위트)

| 요구 | 태스크 | 검증 관심사 | 스위트 파일 |
|------|--------|-------------|-------------|
| Req 2 | 2.1 | 누적 계약 대조(lock 필드·document_version·API 24~31·에러·Base 규약·Settings additive·APScheduler 결합 부팅) | `test_cumulative_contract_conformance.py` |
| Req 3 | 2.2 | 잠금·버전 흐름 INV-9(시작·차단·저장·취소·강제해제·타임아웃 없음·버전 무한 누적·role 게이팅) | `test_lock_version_flow.py` |
| Req 4 | 2.3 | 휴지통 흐름 INV-2·10(열람·복구·복구 위치·완전삭제 원자성·viewer 거부·admin bypass·404 경계) | `test_trash_flow.py` |
| Req 5 | 2.4 | 잠금↔삭제 독립 §4.3(s09 미전이·s10 lock 미변경·엔진 위임·게이팅 재사용·잠긴 상태 완전삭제/복구) | `test_lock_delete_independence.py` |
| Req 6 | 2.5 | 묶음 보관 타이머 독립성 INV-12(만료분만 purge·독립 타이머·자식 선만료·멱등·WS 스코프·purge DB 관찰) | `test_retention_sweep_independence.py` |
| Req 7 | 2.6 | 아래 계층 결합 엣지(role별 접근 경계·admin override·삭제 사용자 작성자 보존·로그인 게이트·물리 삭제 부재) | `test_combination_layer_edge.py` |

> 위 6개 스위트가 Req 2~7을 담당하며, `test_harness_smoke.py`·`test_helpers_smoke.py`는 L4 하네스
> (L3 하네스 재사용·확장 + 두 editor(A·B) 세션·잠금/휴지통/스윕 시나리오 픽스처, 잠금·버전·휴지통·스윕
> 호출 헬퍼)의 자체 점검이다. 게이트 판정은 스위트 전체(전체 `tests/integration_L4`)의 실행 결과로
> 집계된다.

현 시점 테스트 분포(관측값, 총 **65**): 계약 대조 25 · 잠금·버전 흐름 7 · 휴지통 흐름 9 · 잠금↔삭제
독립 7 · 보관 타이머 독립성 6 · 결합 엣지 4 · 하네스 스모크 4 · 헬퍼 스모크 3.

## 3. 실행 방법

```bash
# backend/ 디렉터리에서
uv run pytest tests/integration_L4
```

**전제 조건(env prerequisites)**:
- 실제 MySQL 8이 가용해야 하며 Alembic 마이그레이션(`uv run alembic upgrade head` 상당)이
  하네스(`conftest.py` — L3/L2/L1 하네스 재사용)에 의해 적용된다.
- 부팅 앱은 s02·s03·s05·s07 + **s09 잠금·버전 라우터 + s10 휴지통 라우터·APScheduler 스케줄러가
  조립된 상태**여야 한다(잠금·저장·취소·강제해제·버전 목록·휴지통 목록·복구·완전삭제 라우트 노출, lifespan
  스케줄러 훅 결합).
- 실제 `DocumentStateEngine`·`RetentionSweepService`를 부팅 앱과 동일 DB 세션으로 직접 호출한다
  (스윕은 `now` 주입으로 결정성 확보, 스케줄러 job 대기·실시간 sleep 없음). **mock 금지.**

**DB 미가용·부팅 앱 미충족·APScheduler 결합 미충족은 스킵이 아니라 실패(FAILURE)로 처리한다** — 미검증이
통과로 오인되는 것을 막기 위함이다(Req 8.4, §4.4·design §Error Handling · GateVerdict).

## 4. G-1 게이트 판정 기준

### 4.1 통과/미통과 조건 (Req 8.1, 8.2)

- **G-1 통과 조건**: `uv run pytest tests/integration_L4` 전체(Requirement 2~7 스위트 — §2 표의 6개
  스위트 + 하네스/헬퍼 스모크)가 **전부 green**이면 G-1 통과다(Req 8.1).
- **G-1 미통과 조건**: 위 실행에서 **하나라도 실패하면** G-1 미통과이며, L5(`s12-attachment`) impl 착수는
  **차단**된다(Req 8.2).
- **판정의 권위**: 판정은 이 문서의 선언이 아니라 위 명령의 실행 결과에서 **파생(derived)**된다. 전부 통과한
  실행 그 자체가 곧 판정이다(design §GateVerdict — 수동 선언 금지).

### 4.2 L5 게이팅 (roadmap §게이트 G-1)

- **G-1 통과 = L5 착수 선행 조건 충족**: L5(`s12-attachment`) impl 착수의 전제 조건이 충족된다. 특히 s12는
  L4에서 검증된 s09의 "저장 = 버전 생성" 이벤트와 s10의 "완전삭제 = deleted 전이" 계약 위에 첨부·이미지·
  보관 폴더 이동(8.6)·저장 참조 소멸 아카이브(8.7)를 얹으므로, 이 게이트 통과는 그 소비 계약이 라우터·스윕
  밖에서 불변식을 유지함을 확인한 상태를 보장한다.
- **G-1 미통과 = L5 착수 차단**: 위 스위트 중 하나라도 실패하면 L5 impl 착수가 금지된다.
- roadmap 원칙(§게이트): 각 `integration-check-L{n}`은 바로 위 계층 impl 착수의 선행 조건이다.

### 4.3 실패 처리 원칙 — origin-spec 수정 (Req 1.5 · design §Out of Boundary)

검증이 실패하면 **원인 upstream spec(s01/s02/s03/s05/s07/s09/s10)에서 수정하고 재실행**한다. 체크포인트는
계약·경계 회귀를 **포착·보고만** 하며, 위반을 우회하기 위해 feature 로직이나 테스트 기대치를 바꾸지 않는다.
실패 유형별 지목:

- 계약 드리프트(lock 컬럼/document_version/API 24~31/에러 형태/Settings additive 불일치) → 계약 대조
  스위트 실패 → s01(스키마·카탈로그) 또는 원인 spec 수정.
- 잠금·버전 회귀(중복 잠금 허용·저장 비원자·취소 시 버전 생성·강제해제 게이팅 오작동·타임아웃 발생·rollback
  경로 노출) → 잠금·버전 흐름 스위트 실패 → s09 수정.
- 휴지통 회귀(목록 누락/오포함·복구 위치 오판·완전삭제 비원자·게이팅 불성립·404 경계 오작동) → 휴지통 흐름
  스위트 실패 → s10(위임)·s07(엔진) 중 원인 spec 수정.
- 잠금↔삭제 결합 회귀(상태 전이가 lock 필드 변경·trashed 문서 잠금 거부·s10 직접 status 갱신·권한 재구현) →
  독립 스위트 실패 → s09·s10 중 원인 spec 수정.
- 보관 타이머 회귀(미만료 오purge·타 묶음 간섭·멱등 위반·WS 스코프 누출·묶음 경계 재구성) → 스윕 독립성
  스위트 실패 → s10(스윕)·s07(엔진) 수정.
- 결합 엣지 회귀(role 경계 불성립·작성자 소실·로그인 게이트 미차단·물리 삭제 발생) → 엣지 스위트 실패 →
  s02/s03/s05(세션·계정·멤버십)·s07(엔진)·s09/s10 중 원인 spec 수정.

### 4.4 환경 미충족 = 실패, 스킵 아님 (Req 8.4)

검증 대상 환경(마이그레이션된 MySQL 8 · 부팅 앱 · APScheduler 결합)이 미충족이면 이를 **스킵이 아니라
실패로 처리**한다. 미검증(unverified)이 게이트 통과로 오인되어서는 안 된다. 하네스는 DB 미가용·부팅 실패·
스케줄러 결합 실패 시 에러/실패로 노출하며, 그런 실행은 G-1 통과 근거가 될 수 없다.

## 5. 재검증 트리거 (Req 8.3 · design §Revalidation Triggers · roadmap §재검증 트리거)

`s01`·`s02`·`s03`·`s05`·`s07`·`s09`·`s10` 중 **하나라도 아래 계약 표면이 수정되면**, 이 체크포인트 **및
로드맵상 이후 모든 체크포인트(L5~L6)**를 누적 집합 기준으로 **재실행**해야 한다. 재실행 시에도 mock 없이 실제
구현을 결합한 상태로 검증한다. **s01(계약) 수정 시에는 모든 체크포인트(L1~L6)를 재실행**한다.

- **s01(계약) 수정 시** — 모든 체크포인트 재실행:
  - `document` lock 필드(`lock_user_id`·`lock_acquired_at`·`current_version_id`)·`document_version`
    스키마(컬럼·제약·FK·INDEX), **`trashed_at` 물리 정밀도**(현 `DATETIME(0)`)
  - 카탈로그 행 24~31 경로·메서드·요구 role·요청/응답 스키마 이름(`DocumentLockRead`·
    `DocumentVersionRead`·`TrashBundleRead`·`Page[T]`)
  - 권한 resolver(`Role` 위계·`require_ws_role`·admin bypass) 시그니처·판정 규칙
  - 세션 인증 의존성(`get_current_user`/`AuthContext`)
  - 공통 에러 응답·에러 코드 카탈로그
  - `Settings` 스키마(특히 `default_trash_retention_days` 및 additive `trash_sweep_interval_seconds`
    확장 계약)·단일 접근자
  - 불변식 카탈로그(INV-1·2·3·4·7·9·10·11·12)
- **s09(lock-version) 수정 시** — L4 및 이후 체크포인트 재실행:
  - 잠금 획득/저장/취소/강제해제의 충돌·멱등·보유자 판정 규칙(INV-9 강제 방식)
  - 저장 트랜잭션 원자 경계(버전 생성·`current_version_id` 갱신·잠금 해제 결합)
  - 카탈로그 행 24~28 계약, 잠금·삭제 독립(§4.3) 규칙, `DocumentVersionRead` 본문 포함 여부
- **s10(trash) 수정 시** — L4 및 이후 체크포인트 재실행:
  - 휴지통 엔드포인트(행 29~31) 계약, 보관 만료 산정 규약(만료 기준 시각·묶음별 독립성 INV-12)
  - 묶음 id 해석·묶음→WS 매핑, 자동 영구삭제 배치 실행 계약(멱등성·묶음 독립성)
  - `trash_sweep_interval_seconds` Settings 필드 규약·APScheduler 결합(lifespan 기동/정지)
- **s07(document-core) 수정 시** — 해당 계층 이후 모든 체크포인트 재실행:
  - 상태 엔진 primitive 시그니처·의미(복구 위치·완전삭제 원자성·묶음 식별):
    `restore_bundle`·`purge_bundle`·`identify_bundles`·`get_bundle` 등
  - 문서→WS(묶음→WS) 어댑터 게이팅 방식
- **s02(auth) 수정 시** — 해당 계층 이후 모든 체크포인트 재실행:
  - 로그인/세션 게이트(삭제 사용자 후속 요청 401 차단에 영향)·세션 write/clear·payload 키
- **s03(admin-account) 수정 시** — 해당 계층 이후 모든 체크포인트 재실행:
  - 계정 상태(`is_active`/`is_deleted`) 표현·독립성·전이 동작(작성자 삭제 후 보존 검증에 영향)
- **s05(workspace) 수정 시** — 해당 계층 이후 모든 체크포인트 재실행:
  - `workspace_member` role 판정 데이터 계약 · resolver 활성화 방식(문서·잠금·휴지통 게이팅 판정 근거)

## 6. 현재 판정 (verdict, 2026-07-17 관측)

**게이트 통과 — 65 passed.** L5(`s12-attachment`) impl 착수 선행 조건 충족.

| 실행 | 명령 | 요약 |
|------|------|------|
| L4 게이트 run 1(권위) | `uv run pytest tests/integration_L4` | `65 passed, 589 warnings in 72.60s` |
| L4 게이트 run 2(안정성 재확인) | `uv run pytest tests/integration_L4` | `65 passed, 589 warnings in 73.04s` |

두 차례 연속 전량 green으로 게이트 통과가 안정적으로 재현됨을 확인했다(계약 대조 25 · 잠금·버전 흐름 7 ·
휴지통 흐름 9 · 잠금↔삭제 독립 7 · 보관 타이머 독립성 6 · 결합 엣지 4 · 하네스 스모크 4 · 헬퍼 스모크 3
= 65). 이 수치는 선언이 아니라 명령 재실행으로 재현·갱신되는 **관측값**이다. upstream
(s01·s02·s03·s05·s07·s09·s10) 수정 시 §5 재검증 트리거에 따라 재실행하고 본 §6 판정을 최신 관측으로
갱신한다.

## 참조

- 요구사항: `.kiro/specs/s11-integration-check-L4/requirements.md` (Req 1.5, 8.1, 8.2, 8.3, 8.4)
- 설계: `.kiro/specs/s11-integration-check-L4/design.md`
  (§Components → GateVerdict, §Revalidation Triggers, §계약 대조 판정, §Testing Strategy)
- 대조 기준 단일 소스: `.kiro/specs/s01-contract-foundation/design.md`
  (§Physical Data Model `document` lock 필드·`document_version` · §API Endpoint Catalog 24~31 · §Errors ·
  §Invariants Catalog INV-1·2·3·4·7·9·10·11·12 · §Common/Permissions · §Base Schemas · §Settings)
- 검증 대상 동작: `.kiro/specs/s09-lock-version/design.md`(잠금·버전 원자 경계)·
  `.kiro/specs/s10-trash/design.md`(휴지통·보관 스윕)·`.kiro/specs/s07-document-core/design.md`
  (`DocumentStateEngine` 복구·완전삭제·묶음 식별)
- 재사용 하네스: `.kiro/specs/s08-integration-check-L3/design.md`·`backend/tests/integration_L3/`,
  및 그것이 재사용하는 L2(`backend/tests/integration_L2/`)·L1(`backend/tests/integration_L1/`) 하네스
- 게이트·재검증 트리거: `.kiro/steering/roadmap.md` (§게이트 · §재검증 트리거 · §Shared seams to watch)
