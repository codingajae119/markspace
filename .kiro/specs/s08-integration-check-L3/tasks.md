# Implementation Plan — s08-integration-check-L3

> **통합 검증 체크포인트(L3)** — feature 로직을 구현하지 않는다. 산출물은 `backend/tests/integration_L3/`의
> integration/e2e 테스트 자산과 게이트(G-1 규칙, L3→L4) 판정뿐이다. 모든 명령은 `backend/`에서 `uv run` 기준,
> 산출물 언어 한국어, 코드 식별자는 영어. **mock 금지**(실제 `s01`·`s02`·`s03`·`s05`·`s07` 구현 + 실제
> workspace_member·document 데이터 + 실제 `DocumentStateEngine` 결합; 엔진 primitive 직접 호출은 실제 s07 코드
> 실행이므로 허용). 계약 대조 기준은 개별 spec design이 아니라 **`s01-contract-foundation` 단일 소스**다. 애플리케이션
> 코드(`app/*`)·마이그레이션·하위 하네스(`tests/integration_L2/*`·`tests/integration_L1/*`)는 수정하지 않는다 —
> L2 하네스는 **재사용·확장**한다.

- [ ] 1. Foundation: L3 실제 결합 검증 하네스 (L2 재사용·확장)
- [ ] 1.1 L3 통합 테스트 하네스 구성 (L2 하네스 재사용 + 문서 트리·엔진 세션 픽스처)
  - `tests/integration_L3/conftest.py`에서 `s06` `tests/integration_L2`의 하네스 픽스처(실제 MySQL 8에 `alembic
    upgrade head` 적용·`s01` `create_app()` 부팅·admin 시드·세션 유지 `TestClient` 팩토리·고유 login_id 생성기·
    워크스페이스 생성·멤버 추가(role)·role별 세션 클라이언트)를 재사용하고, 부팅 앱이 s02·s03·s05·**s07 문서 라우터가
    조립된 상태**(문서 CRUD·이동·삭제 라우트 노출)임을 전제로 한다. 워크스페이스와 role별 멤버(editor/viewer/비멤버/
    admin)를 구성하고 문서 트리(루트·하위·손자)를 생성하는 셋업 픽스처, 그리고 부팅 앱과 **동일한 `SessionLocal`/
    `get_db` 세션 팩토리**로 `s07` `DocumentStateEngine`(+`DocumentRepository`)을 인스턴스화하는 엔진 접근 픽스처를 신규 추가
  - mock·stub을 사용하지 않으며(엔진 직접 호출은 실제 s07 코드), DB 미가용 시 스킵이 아니라 실패로 처리. 설정은
    s01 `Settings` 재사용, 애플리케이션 코드와 하위 하네스 자산은 수정하지 않음(재사용만). 동일 하네스를 중복 신설하지 않음
  - 관찰 가능 완료: 픽스처가 마이그레이션된 DB + 부팅 앱(s07 문서 라우트 포함) + admin 시드 + role별 세션 클라이언트 +
    구성된 워크스페이스/멤버/문서 트리 + 엔진 인스턴스를 제공하고, editor 클라이언트가 `POST /workspaces/{id}/documents`
    에서 201을, 엔진 픽스처가 `identify_bundles(workspace_id)` 호출에서 결과를 반환하는 스모크 검증이 통과한다
  - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - _Boundary: L3TestHarness_
- [ ] 1.2 문서·엔진 시나리오 헬퍼 구성 (문서 CRUD·이동·삭제·엔진 primitive 래퍼, L2/L1 헬퍼 재사용)
  - `tests/integration_L3/helpers.py`에 문서 생성(`POST /workspaces/{id}/documents`, parent 지정 하위문서 포함)·
    조회(`GET /documents/{id}`)·목록(`GET /workspaces/{id}/documents`)·제목 수정(`PATCH /documents/{id}`)·이동
    (`POST /documents/{id}/move`)·삭제(`DELETE /documents/{id}`) 호출을 감싸는 헬퍼와, 엔진 primitive 호출 래퍼
    (`identify_bundles`·`get_bundle`·`restore_bundle`·`purge_bundle`·`active_descendants`)를 하네스 엔진 인스턴스로
    호출하는 래퍼를 제공. 워크스페이스 생성·멤버 추가(role)·role별 세션 클라이언트·계정 생성·로그인·상태 전이(비활동/
    삭제) 헬퍼는 `s06` L2 `helpers.py`(및 그것이 재사용하는 L1 헬퍼)를 재사용(중복 정의 금지)
  - 관찰 가능 완료: 헬퍼로 editor가 루트·하위 문서를 만들고 이동·삭제한 뒤 `get_bundle(root_id)`가 묶음 구성원을
    반환하는 스모크 검증이 통과한다
  - _Requirements: 1.4, 3.1_
  - _Boundary: Helpers_
  - _Depends: 1.1_

- [ ] 2. Core: 계약 대조·권한 게이팅·계층 이동·bundle 캐스케이드·복구/완전삭제·엣지케이스 검증 스위트
- [ ] 2.1 (P) 문서 계약 대조 스위트 — 스키마·API(18~23)·status·에러·Base 규약
  - `tests/integration_L3/test_document_contract_conformance.py`에: (1) 마이그레이션된 `document`(workspace_id/
    parent_id/title/status ENUM(active/trashed/deleted)/sort_order DECIMAL/current_version_id/trashed_at/
    created_by/타임스탬프, 인덱스 `(workspace_id, status, parent_id)`·`(workspace_id, status, trashed_at)`)와
    `document_version`(document_id FK·content·created_by·created_at·INDEX(document_id, created_at))이 s01 물리
    모델과 일치하고 s07이 새 마이그레이션을 추가하지 않았음, (2) 부팅 앱 라우트가 s01 카탈로그 행 18~23 경로·메서드·
    요구 role대로 노출, (3) 미인증 401·viewer 변경 403·미존재 404·비active 재삭제/순환 이동 409·빈 제목 422를 실제
    유발해 응답이 `ErrorResponse`(code/message/field_errors) 형태이고 상태 코드가 s01 에러 카탈로그와 일치, (4)
    `DocumentRead`가 `TimestampedRead` 상속·목록이 `Page[DocumentRead]` 규약·`status` 값이 s01 ENUM 집합과 동일,
    (5) active→trashed만 라우터 노출·trashed→deleted 종착(INV-7)·물리 삭제 없음(INV-4)을 검증. 대조 기준은 s01 단일 소스
  - 관찰 가능 완료: 스키마(2)·API 노출(18~23)·에러 형태·Base 규약·status 전이 대조 그룹이 실제 결합 런타임에서 모두
    통과하고, 불일치 시 어느 계약 요소가 드리프트했는지 assertion 메시지가 지목한다
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  - _Boundary: DocumentContractConformanceSuite_
  - _Depends: 1.1_
- [ ] 2.2 (P) 문서 권한 게이팅 스위트 — editor/viewer 게이트·비멤버 차단·admin bypass·어댑터 (INV-1·2·3)
  - `tests/integration_L3/test_document_permission_gating.py`에 owner가 WS 생성 + editor·viewer 추가 후 role별 독립
    세션으로: (1) editor 게이트(생성·수정·이동·삭제)에서 editor·owner 통과 (3.1)·viewer 403 (3.2, INV-2)·비멤버 403
    (3.4), (2) viewer 게이트(조회·목록)에서 owner·editor·viewer 통과 (3.3)·비멤버 403 (3.4, INV-1), (3) admin이
    비멤버 WS의 문서 조회·목록·생성·수정·이동·삭제 모두 접근 성공 (3.5, INV-3), (4) `/documents/{id}` 라우트가 문서→WS
    어댑터로 게이트되어 존재하지 않는 문서 404·권한 미충족 403 (3.6)을 실제 세션 쿠키 자로 e2e 검증. 판정은 s05가 채운
    실제 workspace_member 데이터 위에서 이뤄짐
  - 관찰 가능 완료: editor/viewer 게이트 × (owner/editor/viewer/비멤버) 매트릭스·admin bypass·어댑터 404/403이 실제
    결합에서 모두 예상대로 통과/거부되고, viewer 읽기 전용(INV-2)·비멤버 차단(INV-1)·admin bypass(INV-3)가 확인된다
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_
  - _Boundary: DocumentPermissionGatingSuite_
  - _Depends: 1.2_
- [ ] 2.3 (P) 문서 계층·이동 스위트 — 같은 WS 이동/재정렬·순환·타 WS·중간삽입 (INV-5·6)
  - `tests/integration_L3/test_document_hierarchy_move.py`에 editor 세션으로 문서 트리 구성 후: (1) 같은 WS 내 다른
    부모 밑 이동·형제 사이 재정렬 성공, 이후 조회에서 새 부모·정렬 반영 (4.1), (2) 자기 자신·후손 밑 이동 거부(409/422,
    INV-5) (4.2), (3) 다른 WS 문서 밑 이동 거부(INV-6) (4.3), (4) 두 형제 사이 이동 시 대상만 인접 sort_order 값을 받고
    다른 형제는 재배치되지 않음 (4.4), (5) 존재하지 않는 부모(404)·비active 부모(409) 이동 거부 (4.5)를 실제 세션 e2e로
    검증. 거부 상태 코드는 s01 에러 카탈로그 4xx 범위 내인지 대조하되 구체 코드는 s07 구현 확정 값 허용
  - 관찰 가능 완료: 같은 WS 이동·순환 거부·타 WS 거부·중간 삽입 정렬·부모 검증이 실제 결합에서 모두 예상대로 통과/거부된다
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
  - _Boundary: DocumentHierarchyMoveSuite_
  - _Depends: 1.2_
- [ ] 2.4 (P) bundle 삭제 캐스케이드 스위트 — active만 포착·비흡수·독립 묶음·원자성 (INV-10·11)
  - `tests/integration_L3/test_bundle_delete_cascade.py`에 editor가 다단계 문서 트리 구성 후: (1) active 하위를 가진
    문서 `DELETE /documents/{id}` → 그 시점 active 하위(루트 포함)만 trashed·공통 trashed_at, `identify_bundles`/
    `get_bundle`로 구성원·trashed_at 동치 확인 (5.1·5.5), (2) 자식 먼저(t1) 삭제 → 부모 나중(t2) 삭제 시 자식 비흡수·
    자기 trashed_at(t1) 유지·`child.trashed_at ≤ parent.trashed_at`·두 묶음 별개 루트 식별 (5.2, INV-11), (3) 일부
    하위만 먼저 삭제된 상태에서 부모 삭제 시 두 묶음 독립 루트 식별 (5.3, 6.3), (4) 이미 trashed 문서 재삭제 → 409
    (5.4), (5) 포착 구성원 전이가 단일 원자 조작·물리 삭제 없음을 DB 관찰로 확인 (5.5, INV-4·10)을 API 경유(삭제)+엔진
    primitive(묶음 식별) 직접 호출로 검증. 둘 다 실제 구현
  - 관찰 가능 완료: 캐스케이드 포착·비흡수(INV-11)·독립 묶음·비active 재삭제 409·원자성/물리보존이 실제 결합에서 모두 통과한다
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_
  - _Boundary: BundleDeleteCascadeSuite_
  - _Depends: 1.2_
- [ ] 2.5 (P) bundle 복구·완전삭제 스위트 — 복구 위치·완전삭제 원자성·묶음 독립·상태/잠금 독립 (INV-10·12)
  - `tests/integration_L3/test_bundle_restore_purge.py`에 API(`DELETE`)로 묶음을 trashed로 만든 뒤 부팅 앱과 동일 DB
    세션의 엔진 primitive를 직접 호출: (1) 부모 active 묶음 `restore_bundle(root)` → 루트 원래 부모 밑 복귀·sort_order
    원위치(또는 폴백) 복원·구성원 active·trashed_at=NULL (6.1, 6.5.1·6.7.1), (2) 부모 non-active/부재 묶음 복구 →
    parent_id=NULL root 맨 뒤 append·내부 계층 유지·자동 재중첩 없음 (6.2, 6.5.2·6.5.3·6.7.2), (3) `purge_bundle(root)`
    → 구성원 전체 deleted·물리 보존·종착 (6.3, INV-10·4·7), (4) 여러 독립 묶음 중 하나 복구/완전삭제 시 다른 묶음의
    구성원·trashed_at·보관 기준 불변 (6.4, INV-12), (5) `lock_user_id`를 직접 세팅한 문서도 삭제·복구·완전삭제 정상
    전이·체크포인트가 lock 값을 스스로 설정하지 않음 (6.5, §4.3)을 검증. 복구·완전삭제 API는 L4(s10)에만 존재하므로
    엔진 primitive 직접 호출로 검증(실제 s07 코드, s10 소비 계약 선검증)
  - 관찰 가능 완료: 복구 위치(부모 active/non-active)·sort_order 복원·완전삭제 원자성·묶음 독립·상태/잠금 독립이 실제
    엔진 호출에서 모두 통과한다
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  - _Boundary: BundleRestorePurgeSuite_
  - _Depends: 1.2_
- [ ] 2.6 (P) 결합 엣지케이스 스위트 — trashed_at 초 단위 묶음 경계·삭제 사용자 작성자 보존·문서 보유 WS 삭제 거부 (INV-4·FK RESTRICT)
  - `tests/integration_L3/test_combination_edge.py`에: (1) 부모-자식이 동일 초에 trashed될 수 있는 경계(자식 먼저 삭제
    → 곧바로 부모 삭제)를 구성해 각 삭제가 자기 묶음 구성원을 삭제 시점에 결정적으로 확정하고 `identify_bundles`/
    `get_bundle` 재구성이 루트+동일 trashed_at 연결 서브트리 기준으로 독립 묶음을 오병합 없이 식별 (7.1), 초 단위 경계
    병합 회귀 관측 시 실패 보고 + `trashed_at` 정밀도 승격을 s01 계약 개정 대상으로 기록(체크포인트는 수정하지 않음)
    (7.2), (2) 문서 작성자(`created_by`)를 admin이 삭제(`is_deleted=true`) 처리한 뒤 그 문서의 `created_by` 참조·사용자
    이름이 물리 삭제 없이 DB 보존됨을 직접 조회로 확인 (7.3, INV-4), (3) 삭제·완전삭제 시나리오 전반에서 `document`·
    `document_version`·`user` 물리 삭제 부재 (7.4), (4) owner가 워크스페이스를 만들고 s07 문서 생성
    (`POST /workspaces/{id}/documents`)으로 문서를 하나 추가한 뒤 그 워크스페이스 삭제(`DELETE /workspaces/{id}`, 행 14
    — s05 엔드포인트, L2 워크스페이스 헬퍼 재사용)를 요청 → **409 conflict** 거부·워크스페이스·문서·멤버십 물리 보존을
    DB 직접 조회로 확인(`s01` `workspace` 참조 FK `ON DELETE RESTRICT`·INV-4 정합), 이어서 빈 워크스페이스 삭제는 여전히
    성공(워크스페이스·멤버십 제거)하여 삭제가 오직 빈 워크스페이스에만 허용되는 경계(s05 삭제 ↔ s07 문서 존재)를 확인
    (7.5·7.6)를 API+엔진 primitive+DB 관찰로 검증. 계정 상태 전이·워크스페이스 생성/멤버/삭제 헬퍼는 s06 L2(및 L1)
    헬퍼 재사용, 문서 생성은 s07 헬퍼 재사용
  - 관찰 가능 완료: 초 단위 trashed_at 묶음 경계 무오병합·삭제 사용자 작성자 보존·물리 삭제 부재·문서 보유 WS 삭제 409
    거부·빈 WS 삭제 성공이 실제 DB·엔진 관찰로 모두 통과하고, 정밀도 회귀 시 s01 승격 대상이 기록된다
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_
  - _Boundary: CombinationEdgeSuite_
  - _Depends: 1.2_

- [ ] 3. Validation: 게이트 판정 및 재검증 트리거
- [ ] 3.1 전체 스위트 결합 실행 및 게이트(L3→L4) 판정·재검증 트리거 기록
  - `uv run pytest tests/integration_L3` 전체를 실제 결합(마이그레이션 DB + 부팅 앱 + 실제 멤버십/문서 데이터 + 실제
    `DocumentStateEngine`, mock 없음)에서 실행하여 Requirement 2~7 스위트가 전부 통과하면 게이트(G-1 규칙) 통과
    (=L4 `s09-lock-version`·`s10-trash` impl 착수 선행 조건 충족)로, 하나라도 실패하면 미통과(=L4 착수 차단)로 판정.
    검증 실패는 원인 spec(s01/s02/s03/s05/s07)에서 수정 후 재실행하며 체크포인트에서 feature 로직을 변경해 우회하지
    않음. 검증 대상 환경(MySQL 8·부팅 앱) 미충족은 스킵이 아니라 실패로 처리. 재검증 트리거(`s01`/`s02`/`s03`/`s05`/
    `s07` 수정 시 이 체크포인트 및 로드맵상 그 이후 모든 체크포인트를 누적 집합 기준 재실행, `s01` 수정 시 모든
    체크포인트 재실행)를 스위트 문서/주석으로 명시
  - 관찰 가능 완료: `uv run pytest tests/integration_L3`가 전부 통과하여 게이트 통과가 성립하고, 재검증 트리거 대상과
    L4 착수 가부가 명확히 기록된다
  - _Requirements: 1.5, 8.1, 8.2, 8.3, 8.4_
  - _Depends: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
