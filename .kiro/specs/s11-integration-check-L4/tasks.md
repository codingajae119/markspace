# Implementation Plan — s11-integration-check-L4

> **통합 검증 체크포인트(L4)** — feature 로직을 구현하지 않는다. 산출물은 `backend/tests/integration_L4/`의
> integration/e2e 테스트 자산과 게이트(G-1 규칙, L4→L5) 판정뿐이다. 모든 명령은 `backend/`에서 `uv run` 기준,
> 산출물 언어 한국어, 코드 식별자는 영어. **mock 금지**(실제 `s01`·`s02`·`s03`·`s05`·`s07`·`s09`·`s10` 구현 +
> 실제 workspace_member·document·document_version·lock 필드 데이터 + 실제 `DocumentStateEngine` + 실제
> `RetentionSweepService` 결합; 엔진·스윕 서비스 직접 호출은 실제 s07·s10 코드 실행이므로 허용). 계약 대조 기준은
> 개별 spec design이 아니라 **`s01-contract-foundation` 단일 소스**다. 애플리케이션 코드(`app/*`)·`config.yml`·
> 마이그레이션·하위 하네스(`tests/integration_L3/*`·`L2`·`L1`)는 수정하지 않는다 — L3 하네스는 **재사용·확장**한다.

- [ ] 1. Foundation: L4 실제 결합 검증 하네스 (L3 재사용·확장)
- [x] 1.1 L4 통합 테스트 하네스 구성 (L3 하네스 재사용 + 두 editor 세션·잠금/휴지통/스윕 시나리오 픽스처)
  - `tests/integration_L4/conftest.py`에서 `s08` `tests/integration_L3`의 하네스 픽스처(실제 MySQL 8에 `alembic
    upgrade head` 적용·`s01` `create_app()` 부팅·admin 시드·세션 유지 `TestClient` 팩토리·고유 login_id 생성기·
    워크스페이스 생성·멤버 추가(role)·role별 세션 클라이언트·문서 트리 생성·부팅 앱과 동일 `SessionLocal`/`get_db`
    세션의 `DocumentStateEngine` 접근)를 재사용하고, 부팅 앱이 s02·s03·s05·s07·**s09 잠금·버전 라우터 + s10 휴지통
    라우터·스케줄러가 조립된 상태**(잠금·저장·취소·강제해제·버전 목록·휴지통 목록·복구·완전삭제 라우트 노출, lifespan
    스케줄러 훅 결합)임을 전제로 한다. 동일 워크스페이스에 **두 editor(A·B)**와 owner/viewer/비멤버/admin 세션을
    구성하는 픽스처, 문서 트리를 `DELETE /documents/{id}`로 trashed 시켜 서로 다른 `trashed_at`의 독립 묶음을 만드는
    픽스처, 워크스페이스 `trash_retention_days`를 알려진 값으로 세팅하는 픽스처, 그리고 부팅 앱과 동일 DB 세션으로
    `s10` `RetentionSweepService.sweep_expired_bundles`(또는 `run_sweep`)를 **`now` 주입**으로 호출하는 스윕 접근
    픽스처를 신규 추가
  - mock·stub을 사용하지 않으며(엔진·스윕 직접 호출은 실제 s07·s10 코드), DB 미가용·부팅 실패 시 스킵이 아니라 실패로
    처리. 설정은 s01 `Settings` 재사용(additive `trash_sweep_interval_seconds` 포함), 애플리케이션 코드·`config.yml`·
    하위 하네스 자산은 수정하지 않음(재사용만). 동일 하네스를 중복 신설하지 않음
  - 관찰 가능 완료: 픽스처가 마이그레이션된 DB + 부팅 앱(s09·s10 라우트·스케줄러 포함) + admin 시드 + role별·두
    editor(A·B) 세션 클라이언트 + 구성된 워크스페이스/멤버/문서 트리/독립 묶음 + 엔진 인스턴스 + `now` 주입 스윕
    호출 헬퍼를 제공하고, editor A가 `POST /documents/{id}/lock`에서 200을, `GET /workspaces/{id}/trash`가 묶음을,
    스윕 픽스처가 `sweep_expired_bundles(db, now)` 호출에서 결과를 반환하는 스모크 검증이 통과한다
  - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - _Boundary: L4TestHarness_
- [x] 1.2 잠금·버전·휴지통·스윕 시나리오 헬퍼 구성 (호출 래퍼, L3/L2/L1 헬퍼 재사용)
  - `tests/integration_L4/helpers.py`에 잠금·버전 헬퍼(`POST /documents/{id}/lock`·`/save`(content)·`/cancel`·
    `/force-unlock`·`GET /documents/{id}/versions`), 휴지통 헬퍼(`GET /workspaces/{id}/trash`·`POST
    /trash/{bundleId}/restore`·`DELETE /trash/{bundleId}`), 스윕 헬퍼(하네스 세션으로
    `RetentionSweepService.sweep_expired_bundles(db, now)` 또는 `run_sweep` 호출·결과/DB 상태 관찰, `now` 인자 주입)를
    제공. 문서 생성·하위 문서·이동·삭제·엔진 primitive(`identify_bundles`·`get_bundle`·`restore_bundle`·
    `purge_bundle`) 호출 래퍼와 워크스페이스 생성·멤버 추가(role)·role별 세션 클라이언트·계정 생성·로그인·상태 전이
    (비활동/삭제) 헬퍼는 `s08` L3 `helpers.py`(및 그것이 재사용하는 L2/L1 헬퍼)를 재사용(중복 정의 금지)
  - 관찰 가능 완료: 헬퍼로 editor A가 문서를 잠그고 저장한 뒤 `GET /versions`가 버전을 반환하고, editor가 문서를 삭제해
    `GET /workspaces/{id}/trash`가 묶음을 반환하며, 스윕 헬퍼가 `now` 주입 호출로 처리 묶음 수를 반환하는 스모크
    검증이 통과한다
  - _Requirements: 1.4, 3.1, 4.1, 6.1_
  - _Boundary: Helpers_
  - _Depends: 1.1_

- [ ] 2. Core: 계약 대조·잠금흐름·휴지통흐름·독립·스윕·아래계층 엣지 검증 스위트
- [x] 2.1 (P) 누적 계약 대조 스위트 — lock 필드·document_version·API(24~31)·에러·Base·Settings additive
  - `tests/integration_L4/test_cumulative_contract_conformance.py`에: (1) 마이그레이션된 `document` lock 컬럼
    (`lock_user_id BIGINT FK NULL`·`lock_acquired_at DATETIME NULL`·`current_version_id BIGINT FK NULL`)과
    `document_version`(`document_id` FK·`content`·`created_by` FK·`created_at`·INDEX(document_id, created_at))이 s01
    물리 모델과 일치하고 s09·s10이 새 마이그레이션을 추가하지 않았음, (2) 부팅 앱 라우트가 s01 카탈로그 행 24~31
    (`POST /documents/{id}/lock`·`/save`·`/cancel`·`/force-unlock`, `GET /documents/{id}/versions`, `GET
    /workspaces/{id}/trash`, `POST /trash/{bundleId}/restore`, `DELETE /trash/{bundleId}`) 경로·메서드·요구 role대로
    노출, (3) 미인증 401·viewer 변경 403·미존재 404·타인 잠금/보유자 아닌 저장 409·저장 본문 형식 422를 실제 유발해
    응답이 `ErrorResponse`(code/message/field_errors) 형태이고 상태 코드가 s01 에러 카탈로그와 일치, (4)
    `DocumentLockRead`·`DocumentVersionRead`·`TrashBundleRead`가 s01 Base 규약·목록 `Page[T]`를 따르고
    `DocumentVersionRead`에 본문 필드 부재, (5) s10 additive `trash_sweep_interval_seconds`가 존재하는 실제 결합
    부팅에서 `s01` `Settings`/`get_settings` 로딩 정상 성공·기존 필드(`default_trash_retention_days` 등) 보존·단일
    접근자 유지, (6) APScheduler 결합 부팅에서 `create_app()` 정상 부팅·`trash_sweep_interval_seconds` `>0` 기동/
    `<=0` 미기동·기존 부팅 계약 무회귀를 검증. 대조 기준은 s01 단일 소스
  - 관찰 가능 완료: 스키마(lock 필드·document_version)·API 노출(24~31)·에러 형태·Base 규약·Settings additive 로딩·
    스케줄러 결합 대조 그룹이 실제 결합 런타임에서 모두 통과하고, 불일치 시 어느 계약 요소가 드리프트했는지 assertion
    메시지가 지목한다
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  - _Boundary: CumulativeContractConformanceSuite_
  - _Depends: 1.1_
- [x] 2.2 (P) 잠금·버전 흐름 스위트 — 시작→차단→저장·해제→취소→강제해제→타임아웃없음→버전무한·게이팅 (INV-9)
  - `tests/integration_L4/test_lock_version_flow.py`에 동일 WS의 두 editor(A·B)·owner·viewer·비멤버·admin 세션으로:
    (1) A `POST /lock` 성공 → B `POST /lock` 409("편집 중")·문서당 잠금 최대 1인 (3.1, INV-9, 5.2), (2) A `POST
    /save`(content) → 새 `document_version` 생성·`current_version_id` 갱신·잠금 해제 → B `POST /lock` 성공 (3.2, 5.3),
    (3) A 재잠금 후 `POST /cancel` → 잠금 해제·새 버전 미생성·버전 목록 불변 (3.3, 5.4), (4) A 잠금 후 owner/admin
    `POST /force-unlock` 해제·버전 미생성·editor(비 owner) force-unlock 403 (3.4, 5.6), (5) 잠금 획득 후 시간 경과
    (또는 시간 진행 시뮬레이션)에도 잠금 유지·명시적 해제로만 해제 (3.5, 5.5), (6) 여러 번 저장 시 버전 누적(기존 버전
    삭제·수정 없음)·`GET /versions` 최신순 메타데이터·rollback/과거 본문 조회 경로 부재 (3.6, 5.7), (7) lock/save/
    cancel=editor(viewer 403·비멤버 403)·force-unlock=owner(editor 403)·versions=viewer(비멤버 403)·admin bypass·
    미존재 문서 404 (3.7, INV-1·2·3)을 실제 세션 쿠키 자로 e2e 검증. 판정은 s05 실제 멤버십 데이터 위에서 이뤄짐
  - 관찰 가능 완료: 시작·타인 차단·저장 원자 결과·취소 폐기·강제해제 게이팅·타임아웃 없음·버전 무한 누적·rollback 없음·
    role 게이팅이 실제 결합에서 모두 예상대로 통과/거부된다
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_
  - _Boundary: LockVersionFlowSuite_
  - _Depends: 1.2_
- [x] 2.3 (P) 휴지통 흐름 스위트 — 열람·복구·완전삭제·viewer거부·admin bypass·복구위치·원자성 (INV-2·10)
  - `tests/integration_L4/test_trash_flow.py`에 editor가 문서 트리를 `DELETE /documents/{id}`로 trashed 시킨 뒤:
    (1) `GET /workspaces/{id}/trash` → `Page[TrashBundleRead]`로 trashed 묶음(본인 삭제분 외 WS 전체 포함)만 반환·각
    묶음 `expires_at = trashed_at + trash_retention_days` 포함 (4.1, 6.11), (2) `POST /trash/{bundleId}/restore` →
    엔진 `restore_bundle` 위임·구성원 active·`trashed_at=NULL`·복구 위치 복구 시점 루트 부모 상태로 결정(부모 active면
    부모 밑, non-active/부재면 root 맨 뒤; 6.5)·복구 후 목록에서 사라짐 (4.2), (3) `DELETE /trash/{bundleId}` → 엔진
    `purge_bundle` 위임·구성원 전체 원자적 deleted(종착 INV-7)·물리 보존(INV-10·4)·요청 묶음에만 적용·타 묶음 불변
    (4.3, 6.9), (4) viewer/비멤버 목록·복구·완전삭제 403(INV-1·2)·admin 비멤버 WS 접근 성공(INV-3) (4.4), (5) 문서
    부재 bundleId 게이트 404·유효 trashed 묶음 루트 아님 엔진 404 (4.5)을 API 경유(실제 라우터)+엔진/DB 관찰로 검증.
    복구·완전삭제 상태 전이는 s07 엔진 소관이며 s10은 위임만. mock 없음
  - 관찰 가능 완료: 목록·복구·복구 위치·완전삭제 원자성·게이팅·404 경계가 실제 결합에서 모두 예상대로 통과/거부되고,
    상태 전이가 엔진 위임으로 수행됨이 확인된다
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
  - _Boundary: TrashFlowSuite_
  - _Depends: 1.2_
- [ ] 2.4 (P) 잠금↔삭제 독립 + 엔진 결합 스위트 — §4.3·s09 미전이·s10 lock 미변경·게이팅 재사용
  - `tests/integration_L4/test_lock_delete_independence.py`에: (1) editor A `POST /lock`으로 잠근 문서를 editor `DELETE
    /documents/{id}`로 trashed 전이 → 상태 전이 정상·`lock_user_id`가 상태 전이로 변경되지 않음 DB 관찰 (5.1), (2)
    trashed 상태 문서에 `POST /lock`·`/save`·`/cancel` → 각 동작이 문서 `status`를 검사하지 않고 잠금 필드/버전
    append에만 작용·상태 전이 미유발 (5.2), (3) 복구·완전삭제·스윕이 s10에서 `status`/`trashed_at` 직접 갱신 없이 엔진
    primitive(`restore_bundle`·`purge_bundle`·`identify_bundles`) 위임·lock 필드 미변경 관찰 (5.3), (4) s09 잠금·버전
    라우트와 s10 휴지통 라우트가 권한 판정을 재구현하지 않고 s01 `require_ws_role`·s07 문서→WS(묶음→WS) 어댑터를
    재사용함을 게이팅 관찰(동일 role 매트릭스 결과) (5.4, INV-1), (5) 잠금 필드가 설정된 채 trashed된 문서를
    `purge_bundle` 완전삭제·`restore_bundle` 복구해도 상태 전이가 잠금 유무와 무관하게 정상 수행 (5.5, §4.3)을 검증.
    잠금 상태는 실제 `POST /lock`으로 설정(테스트가 lock 컬럼 임의 조작 금지). mock 없음
  - 관찰 가능 완료: 잠긴 문서 trashed·trashed 문서 잠금 동작·s10 위임/lock 불변·게이팅 재사용·잠긴 상태 완전삭제/복구가
    실제 결합에서 모두 통과하고, 잠금↔삭제 독립(§4.3)이 확인된다
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  - _Boundary: LockDeleteIndependenceSuite_
  - _Depends: 1.2_
- [ ] 2.5 (P) 묶음 보관 타이머 독립성 스위트 — 만료분만 purge·독립 타이머·자식 선만료·멱등·WS 스코프 (INV-12)
  - `tests/integration_L4/test_retention_sweep_independence.py`에 여러 묶음을 서로 다른 `trashed_at`으로 구성하고
    워크스페이스 `trash_retention_days`를 알려진 값으로 세팅한 뒤 부팅 앱과 동일 DB 세션의
    `RetentionSweepService.sweep_expired_bundles(db, now)`(또는 `run_sweep`)를 **`now` 주입**으로 호출: (1) `trashed_at
    + retention <= now` 묶음만 구성원 `deleted` 전환·미만료 묶음 불변(status·trashed_at 유지) (6.1), (2) 만료 묶음
    처리가 다른(미만료) 묶음의 구성원·`trashed_at`·보관 기준에 영향 없음 (6.2, INV-12), (3) 자식 묶음이 더 이른
    `trashed_at`이면 부모 묶음보다 먼저 만료되어 독립 영구삭제되는 케이스 허용 (6.3, 6.4.1), (4) 이미 deleted/복구된
    묶음 포함 스윕 반복 실행 → 이미 처리 묶음 오류 없이 skip·중복 전이/예외 전파 없음 (6.4, 멱등), (5) 여러 워크스페이스
    에서 각 `trash_retention_days`가 자기 WS 묶음 만료에만 적용·타 WS 미만료 묶음 불변 (6.5), (6) 만료 묶음이 실제
    `deleted`로 전환된 결과를 DB 관찰(구성원 `status=deleted`·물리 삭제 부재)로 확인·스윕이 묶음 경계를 재구성하지 않고
    엔진 `identify_bundles`·`purge_bundle`에만 의존 (6.6)을 검증. `now` 주입으로 만료 경계 결정성 확보(스케줄러 job
    대기·실시간 sleep 금지). 스윕·엔진 직접 호출은 실제 s10·s07 코드. mock 없음
  - 관찰 가능 완료: 만료분만 purge·묶음별 독립 타이머·자식 선만료 수용·멱등·워크스페이스 스코프 독립·실제 purge DB
    관찰이 실제 결합에서 모두 통과하고, 묶음 보관 만료가 각 `trashed_at` 기준 독립 산정됨(INV-12)이 확인된다
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_
  - _Boundary: RetentionSweepIndependenceSuite_
  - _Depends: 1.2_
- [ ] 2.6 (P) 아래 계층 결합 엣지 스위트 — role별 접근 경계·admin override·작성자 보존·물리삭제 부재 (INV-1·2·3·4)
  - `tests/integration_L4/test_combination_layer_edge.py`에: (1) owner/editor/viewer/비멤버/admin 세션으로 잠금·버전·
    휴지통 라우트 접근 경계 관찰 → viewer 잠금·저장·취소·강제해제·휴지통 변경 거부(INV-2)·비멤버 차단(INV-1)·admin
    비멤버 WS 전면 접근(INV-3)이 아래 계층(s02 세션·s05 멤버십) 결합 위에서 성립 (7.1), (2) 문서·`document_version`을
    만든 사용자(`created_by`)를 admin이 삭제(`is_deleted=true`) 처리한 뒤 그 문서·버전의 `created_by` 참조·사용자 이름이
    물리 삭제 없이 DB 보존·삭제 사용자의 잠금·저장 후속 요청 401 로그인 게이트 차단 (7.2, INV-4), (3) 잠금·저장·취소·
    강제해제·복구·완전삭제·보관 스윕 시나리오 전반에서 `document`·`document_version`·`user` 물리 삭제 부재 (7.3, INV-4)를
    API+엔진+스윕+DB 관찰로 검증. 계정 상태 전이 헬퍼는 s08 L3(및 L2/L1) 헬퍼 재사용
  - 관찰 가능 완료: role별 접근 경계·admin override·삭제 사용자 문서/버전 작성자 보존·로그인 게이트·물리 삭제 부재가
    실제 DB·엔진·스윕 관찰로 모두 통과한다
  - _Requirements: 7.1, 7.2, 7.3_
  - _Boundary: CombinationLayerEdgeSuite_
  - _Depends: 1.2_

- [ ] 3. Validation: 게이트 판정 및 재검증 트리거
- [ ] 3.1 전체 스위트 결합 실행 및 게이트(L4→L5) 판정·재검증 트리거 기록
  - `uv run pytest tests/integration_L4` 전체를 실제 결합(마이그레이션 DB + 부팅 앱(s09·s10 라우터·스케줄러 포함) +
    실제 멤버십/문서/버전 데이터 + 실제 `DocumentStateEngine` + 실제 `RetentionSweepService` + APScheduler 결합, mock
    없음)에서 실행하여 Requirement 2~7 스위트가 전부 통과하면 게이트(G-1 규칙) 통과(=L5 `s12-attachment` impl 착수
    선행 조건 충족)로, 하나라도 실패하면 미통과(=L5 착수 차단)로 판정. 검증 실패는 원인 spec(s01/s02/s03/s05/s07/s09/
    s10)에서 수정 후 재실행하며 체크포인트에서 feature 로직을 변경해 우회하지 않음. 검증 대상 환경(MySQL 8·부팅 앱·
    APScheduler 결합) 미충족은 스킵이 아니라 실패로 처리. 재검증 트리거(`s01`/`s02`/`s03`/`s05`/`s07`/`s09`/`s10`
    수정 시 이 체크포인트 및 로드맵상 그 이후 모든 체크포인트를 누적 집합 기준 재실행, `s01` 수정 시 모든 체크포인트
    재실행)를 스위트 문서/주석으로 명시
  - 관찰 가능 완료: `uv run pytest tests/integration_L4`가 전부 통과하여 게이트 통과가 성립하고, 재검증 트리거 대상과
    L5 착수 가부가 명확히 기록된다
  - _Requirements: 1.5, 8.1, 8.2, 8.3, 8.4_
  - _Depends: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
