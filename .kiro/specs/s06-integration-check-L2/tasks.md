# Implementation Plan — s06-integration-check-L2

> **통합 검증 체크포인트(L2)** — feature 로직을 구현하지 않는다. 산출물은 `backend/tests/integration_L2/`의
> integration/e2e 테스트 자산과 게이트(G-1 규칙, L2→L3) 판정뿐이다. 모든 명령은 `backend/`에서 `uv run` 기준,
> 산출물 언어 한국어, 코드 식별자는 영어. **mock 금지**(실제 `s01`·`s02`·`s03`·`s05` 구현 + 실제 workspace_member
> 데이터 결합). 계약 대조 기준은 개별 spec design이 아니라 **`s01-contract-foundation` 단일 소스**다. 애플리케이션
> 코드(`app/*`)·마이그레이션·`s04` L1 자산(`tests/integration_L1/*`)은 수정하지 않는다 — L1 하네스는 **재사용·확장**한다.

- [ ] 1. Foundation: L2 실제 결합 검증 하네스 (L1 재사용·확장)
- [ ] 1.1 L2 통합 테스트 하네스 구성 (L1 하네스 재사용 + 워크스페이스·role 세션 픽스처)
  - `tests/integration_L2/conftest.py`에서 `s04` `tests/integration_L1`의 하네스 픽스처(실제 MySQL 8에 `alembic
    upgrade head` 적용·`s01` `create_app()` 부팅·admin 시드·세션 유지 `TestClient` 팩토리·고유 login_id 생성기)를
    재사용하고, 부팅 앱이 s02·s03·**s05 라우터가 조립된 상태**(워크스페이스·소유권 라우트 노출)임을 전제로 한다.
    admin으로 여러 사용자를 생성해 각자 세션을 유지하는 role별 클라이언트(owner/editor/viewer/비멤버/admin)와,
    워크스페이스를 생성해 지정 role로 멤버를 구성하는 셋업 픽스처를 신규 추가
  - mock·stub을 사용하지 않으며, DB 미가용 시 스킵이 아니라 실패로 처리. 설정은 s01 `Settings` 재사용, 애플리케이션
    코드와 L1 자산은 수정하지 않음(재사용만). 동일 하네스를 중복 신설하지 않음
  - 관찰 가능 완료: 픽스처가 마이그레이션된 DB + 부팅 앱(s05 라우트 포함) + admin 시드 + role별 세션 클라이언트 +
    구성된 워크스페이스/멤버십을 제공하고, admin 클라이언트가 `GET /workspaces`에서 200을 받는 스모크 검증이 통과한다
  - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - _Boundary: L2TestHarness_
- [ ] 1.2 워크스페이스 시나리오 헬퍼 구성 (멤버·소유권·설정 래퍼, L1 계정 헬퍼 재사용)
  - `tests/integration_L2/helpers.py`에 워크스페이스 생성(`POST /workspaces`), 멤버 추가(`POST
    /workspaces/{id}/members`, role 지정), role 변경(`PATCH .../members/{uid}`), 멤버 제거(`DELETE
    .../members/{uid}`), 소유권 변경(`POST /admin/workspaces/{id}/owner`), 설정 변경(`PATCH /workspaces/{id}`)
    호출을 감싸는 헬퍼를 제공. 계정 생성·로그인·상태 전이(비활동/삭제) 헬퍼는 `s04` L1 `helpers.py`를 재사용(중복
    정의 금지)
  - 관찰 가능 완료: 헬퍼로 owner가 워크스페이스를 만들고 editor·viewer를 추가한 뒤 각 role 클라이언트가 자기
    세션으로 `GET /workspaces/{id}` 200을 받는 스모크 검증이 통과한다
  - _Requirements: 1.4, 3.1_
  - _Boundary: Helpers_
  - _Depends: 1.1_

- [ ] 2. Core: 계약 대조·권한 경계·override·소유권·계정결합·설정 검증 스위트
- [ ] 2.1 (P) 워크스페이스 계약 대조 스위트 — 스키마·API(9~17)·에러 모델·Base 규약
  - `tests/integration_L2/test_workspace_contract_conformance.py`에: (1) 마이그레이션된 `workspace`(name·
    is_shareable·trash_retention_days·타임스탬프)와 `workspace_member`(workspace_id/user_id FK·role
    ENUM(owner/editor/viewer)·UNIQUE(workspace_id,user_id)·INDEX(user_id))가 s01 물리 모델과 일치, (2) 부팅 앱
    라우트가 s01 카탈로그 행 10~17(워크스페이스·멤버십)·행 9(admin 소유권 변경) 경로·메서드·요구 role대로 노출,
    (3) 미인증 401·권한 부족 403·미존재 404·중복 멤버 409·검증 실패 422(retention ≤ 0)를 실제 유발해 응답이
    `ErrorResponse`(code/message/field_errors) 형태이고 상태 코드가 s01 에러 카탈로그와 일치, (4) `WorkspaceRead`가
    `TimestampedRead` 상속·목록이 `Page[WorkspaceRead]` 규약이고 s05가 새 마이그레이션 없이 s01 스키마만 사용함을
    검증. 대조 기준은 s01 단일 소스
  - 관찰 가능 완료: 스키마(2)·API 노출(9~17)·에러 형태·Base 규약 4개 대조 그룹이 실제 결합 런타임에서 모두 통과하고,
    불일치 시 어느 계약 요소가 드리프트했는지 assertion 메시지가 지목한다
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  - _Boundary: WorkspaceContractConformanceSuite_
  - _Depends: 1.1_
- [ ] 2.2 (P) 권한 경계 스위트 — role 위계·viewer 읽기전용·비멤버 차단 (INV-1·2)
  - `tests/integration_L2/test_permission_boundary.py`에 owner가 WS 생성 + editor·viewer 추가 후 role별 독립
    세션으로: (1) viewer 게이트(`GET /workspaces/{id}`)에서 owner·editor·viewer 모두 200 (3.1)·비멤버 403 (3.3),
    (2) owner 게이트(`PATCH /workspaces/{id}`·멤버 추가·제거)에서 owner 200 (3.4)·editor·viewer 403 (3.2, INV-2)·
    비멤버 403 (3.3), (3) editor가 viewer 게이트는 통과하되 owner 게이트는 거부되어 위계상 중간 등급임을 대조 (3.5)
    를 실제 세션 쿠키 자로 e2e 검증. 판정은 s05가 채운 실제 workspace_member 데이터 위에서 이뤄짐
  - 관찰 가능 완료: viewer/owner 게이트 × (owner/editor/viewer/비멤버) 매트릭스가 실제 결합에서 모두 예상대로
    통과/거부되고, viewer 읽기 전용(INV-2)·비멤버 차단(INV-1)·editor 중간 위계가 확인된다
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  - _Boundary: PermissionBoundarySuite_
  - _Depends: 1.2_
- [ ] 2.3 (P) admin override 스위트 — 비멤버 WS bypass·전체 목록 (INV-3)
  - `tests/integration_L2/test_admin_override.py`에: (1) admin이 자신이 멤버가 아닌 워크스페이스의 viewer 게이트
    (`GET /workspaces/{id}`) 접근 성공 (4.1), (2) 같은 비멤버 워크스페이스의 owner 게이트(`PATCH
    /workspaces/{id}`·멤버 추가) 접근 성공 (4.2, INV-3), (3) admin의 `GET /workspaces`가 멤버 스코프에 제한되지
    않고 전체 워크스페이스를 반환 (4.3)을 실제 세션으로 e2e 검증. admin은 하네스 시드 `is_admin=true` 단일 출처
  - 관찰 가능 완료: 비멤버 admin이 viewer·owner 게이트를 모두 bypass하고 전체 목록 가시성을 가짐이 확인되어 INV-3가
    모든 워크스페이스 게이트에서 성립함이 관찰된다
  - _Requirements: 4.1, 4.2, 4.3_
  - _Boundary: AdminOverrideSuite_
  - _Depends: 1.2_
- [ ] 2.4 (P) admin 소유권 변경 스위트 — upsert·새 owner 권한·403·404
  - `tests/integration_L2/test_owner_change.py`에: (1) admin `POST /admin/workspaces/{id}/owner`로 사용자를 새
    owner 지정 → 그 사용자가 이후 owner 게이트를 자기 세션으로 통과 (5.1), (2) 유일 owner를 제거해 owner 부재로
    만든 뒤 새 owner 지정 성공·권한 획득 (5.2, docs 3.7), (3) 비-admin의 소유권 변경 호출 → 403 (5.3), (4) 존재하지
    않는 워크스페이스/대상 사용자로 소유권 변경 → 404 (5.4)를 실제 세션으로 e2e 검증. 소유권 변경은 upsert-to-owner
    (멤버면 role 갱신, 아니면 신규 등록, 기존 owner 유지)
  - 관찰 가능 완료: 소유권 변경 후 새 owner의 owner 게이트 통과·owner 부재 복구·비-admin 403·미존재 404가 모두
    실제 결합에서 통과한다
  - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - _Boundary: OwnerChangeSuite_
  - _Depends: 1.2_
- [ ] 2.5 (P) 계정상태 ↔ 멤버십 결합 스위트 — 유일 owner 전이·보존 (L1 결합, INV-4)
  - `tests/integration_L2/test_account_state_membership.py`에 owner가 WS 생성 + editor·viewer 추가 후: (1) admin이
    유일 owner를 비활동(`is_active=false`) 또는 삭제(`is_deleted=true`) 처리 → editor·viewer 세션이 자신의 role
    라우트에 계속 정상 접근(무영향) (6.1, docs 3.7), (2) 삭제된 멤버의 `workspace_member` 행·사용자 이름이 DB에
    물리적으로 보존됨을 직접 조회로 확인 (6.2, INV-4), (3) 삭제/비활동 멤버 로그인 시도 → 401 (6.3, s02 게이트),
    (4) 시나리오 전반에서 `workspace`·`workspace_member`·`user` 레코드에 예기치 않은 물리 삭제가 없었음을 확인
    (6.4)를 실제 결합으로 e2e 검증. 계정 상태 전이는 s04 L1 헬퍼 재사용. 워크스페이스 owner는 시스템 admin과
    별개이므로 s03 admin 잠금 가드 비대상
  - 관찰 가능 완료: 유일 owner 비활동/삭제 후 editor·viewer 무영향·멤버십/이름 보존·삭제 멤버 로그인 401·물리 삭제
    부재가 실제 DB·세션 관찰로 모두 통과한다
  - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - _Boundary: AccountStateMembershipSuite_
  - _Depends: 1.2_
- [ ] 2.6 (P) 워크스페이스 설정 스위트 — is_shareable·retention·기본값·admin bypass
  - `tests/integration_L2/test_workspace_settings.py`에: (1) owner가 `PATCH /workspaces/{id}`로 `is_shareable`
    변경 → 이후 `GET`에 갱신 값 반영 (7.1), (2) `trash_retention_days`를 양의 정수로 변경 → 반영, 0 이하 → 422
    (7.2), (3) admin이 비멤버 워크스페이스 설정 변경 성공 (7.3, INV-3), (4) 신규 워크스페이스 기본값이
    `is_shareable=false`·`trash_retention_days`=s01 `Settings` 기본값임 (7.4)을 실제 세션으로 e2e 검증
  - 관찰 가능 완료: 설정 반영·retention 422 경계·admin bypass·생성 기본값이 실제 결합에서 모두 통과한다
  - _Requirements: 7.1, 7.2, 7.3, 7.4_
  - _Boundary: WorkspaceSettingsSuite_
  - _Depends: 1.2_

- [ ] 3. Validation: 게이트 판정 및 재검증 트리거
- [ ] 3.1 전체 스위트 결합 실행 및 게이트(L2→L3) 판정·재검증 트리거 기록
  - `uv run pytest tests/integration_L2` 전체를 실제 결합(마이그레이션 DB + 부팅 앱 + 실제 멤버십 데이터, mock 없음)
    에서 실행하여 Requirement 2~7 스위트가 전부 통과하면 게이트(G-1 규칙) 통과(=L3 `s07-document-core` impl 착수
    선행 조건 충족)로, 하나라도 실패하면 미통과(=L3 착수 차단)로 판정. 검증 실패는 원인 spec(s01/s02/s03/s05)에서
    수정 후 재실행하며 체크포인트에서 feature 로직을 변경해 우회하지 않음. 재검증 트리거(`s01`/`s02`/`s03`/`s05`
    수정 시 이 체크포인트 및 로드맵상 그 이후 모든 체크포인트를 누적 집합 기준 재실행, `s01` 수정 시 모든 체크포인트
    재실행)를 스위트 문서/주석으로 명시
  - 관찰 가능 완료: `uv run pytest tests/integration_L2`가 전부 통과하여 게이트 통과가 성립하고, 재검증 트리거
    대상과 L3 착수 가부가 명확히 기록된다
  - _Requirements: 1.5, 8.1, 8.2, 8.3_
  - _Depends: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
