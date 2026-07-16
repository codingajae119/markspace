# Implementation Plan — s04-integration-check-L1

> **통합 검증 체크포인트(L1)** — feature 로직을 구현하지 않는다. 산출물은 `backend/tests/integration_L1/`의
> integration/e2e 테스트 자산과 G-1 판정뿐이다. 모든 명령은 `backend/`에서 `uv run` 기준, 산출물 언어 한국어,
> 코드 식별자는 영어. **mock 금지**(실제 `s01`·`s02`·`s03` 구현 결합). 계약 대조 기준은 개별 spec design이 아니라
> **`s01-contract-foundation` 단일 소스**다. 애플리케이션 코드(`app/*`)·마이그레이션은 수정하지 않는다.

- [ ] 1. Foundation: 실제 결합 검증 하네스
- [ ] 1.1 L1 통합 테스트 하네스 구성 (마이그레이션·앱 부팅·admin 시드·세션 클라이언트)
  - `tests/integration_L1/conftest.py`에 실제 MySQL 8에 `alembic upgrade head`를 적용해 s01 스키마를 준비하고,
    `s01` `create_app()`으로 s02·s03 라우터가 조립된 앱을 부팅하며, 세션 쿠키를 유지하는 `TestClient`를 제공하는
    픽스처를 구성. admin 생성 경로가 없으므로 s01 user 모델/직접 INSERT로 `is_admin=true` 사용자를 DB에 시드
  - mock·stub을 사용하지 않으며, DB 미가용 시 스킵이 아니라 실패로 처리(미검증이 통과로 오인되지 않게 함). 설정은
    s01 `Settings` 재사용, 애플리케이션 코드는 수정하지 않음
  - 관찰 가능 완료: 픽스처가 마이그레이션된 DB + 부팅 앱 + 시드된 admin 계정 + 세션 유지 클라이언트를 제공하고,
    admin으로 로그인한 클라이언트가 `GET /auth/me`에서 200을 받는 스모크 검증이 통과한다
  - _Requirements: 1.1, 1.2, 1.3_
  - _Boundary: L1TestHarness_
- [ ] 1.2 시나리오 헬퍼 구성 (로그인·계정 생성·상태 전이 호출 래퍼)
  - `tests/integration_L1/helpers.py`에 admin 계정 생성(`POST /admin/users`), 사용자 로그인(`POST /auth/login`),
    상태 전이(`PATCH /admin/users/{id}` is_active/is_deleted), admin 비밀번호 재설정
    (`POST /admin/users/{id}/password`), 본인 비밀번호 변경(`POST /auth/password`) 호출을 감싸는 헬퍼와 고유
    login_id 생성기를 제공(테스트 간 상태 격리)
  - 관찰 가능 완료: 헬퍼로 admin이 생성한 신규 사용자가 그 자격으로 로그인 200을 받고, 각 테스트가 충돌 없는 고유
    login_id를 사용함이 스모크 검증으로 확인된다
  - _Requirements: 1.1, 3.1_
  - _Boundary: Helpers_
  - _Depends: 1.1_

- [ ] 2. Core: 계약 대조·경계·불변식 검증 스위트
- [ ] 2.1 (P) 계약 대조 스위트 — user 스키마·인증/계정 API·에러 모델·민감필드
  - `tests/integration_L1/test_contract_conformance.py`에: (1) 마이그레이션된 `user` 테이블의 컬럼·유일제약
    (`login_id`)·flag(`is_admin`/`is_active`/`is_deleted`)·`password_hash`가 s01 물리 데이터 모델과 일치, (2) 부팅
    앱 라우트가 s01 카탈로그 1~4(auth)·5~8(admin) 경로·메서드·요구 인증/admin 게이트대로 노출, (3) 미인증 401·
    비-admin 403·미존재 404·중복 login_id 409·검증 실패 422를 실제 유발해 응답이 `ErrorResponse`(code/message/
    field_errors) 형태이고 상태 코드가 s01 에러 카탈로그와 일치, (4) `/auth/me`·`/auth/login`·`/admin/users`
    응답에 `password_hash` 부재를 검증. 대조 기준은 s01 단일 소스
  - 관찰 가능 완료: 스키마·API 노출(1~8)·에러 형태·민감필드 4개 대조 그룹이 실제 결합 런타임에서 모두 통과하고,
    불일치 시 어느 계약 요소가 드리프트했는지 assertion 메시지가 지목한다
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 7.2_
  - _Boundary: ContractConformanceSuite_
  - _Depends: 1.1_
- [ ] 2.2 (P) 계정 생명주기 ↔ 로그인 경계 스위트 — 활성/비활성/삭제/재활성화/재설정/본인변경
  - `tests/integration_L1/test_account_lifecycle_login.py`에 비-admin 사용자를 대상으로: (1) 생성→로그인 200+세션
    (3.1), (2) admin 비밀번호 재설정→새 비번 200·옛 비번 401 (3.2, 3.3), (3) 비활동(is_active=false)→로그인 401·
    세션 미발급 (4.1), (4) 삭제(is_deleted=true)→로그인 401 (4.2)·보유 세션의 후속 `/auth/me` 401 (4.3), (5)
    재활성화(is_deleted=false)→로그인 200 (5.1)·비활동 유지 시 삭제 flag만 되돌려도 여전히 401 (5.2), (6) 본인
    비밀번호 변경→새 비번 200·옛 비번 401 (6.1, 6.2) 시나리오를 실제 세션 쿠키 자로 e2e 검증
  - 관찰 가능 완료: 6개 cross-spec 시나리오 그룹이 s03로 상태를 만들고 s02로 로그인 결과를 관찰하는 실제 결합에서
    모두 통과하며, 로그인 실패는 사유 불문 401 동일 응답임이 확인된다
  - _Requirements: 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 5.1, 5.2, 6.1, 6.2_
  - _Boundary: AccountLifecycleLoginSuite_
  - _Depends: 1.2_
- [ ] 2.3 (P) 물리 삭제 없음(INV-4) 보존 스위트
  - `tests/integration_L1/test_soft_delete_preservation.py`에: (1) admin 삭제(is_deleted=true) 후 DB에서 해당
    user 레코드가 물리적으로 존재하고 flag만 전환됨을 직접 조회로 확인 (7.1), (2) 삭제된 사용자의 이름·식별 정보가
    보존되어 `GET /admin/users`에 삭제 상태로 계속 노출됨을 확인 (7.2), (3) 생성→삭제→재활성화 왕복 전반에서 user
    레코드 수가 물리 삭제로 감소하지 않음을 확인 (7.3)
  - 관찰 가능 완료: 삭제 처리 후 레코드 물리 존재·이름 보존·목록 노출·레코드 수 불감소가 실제 DB 관찰로 모두
    통과한다
  - _Requirements: 7.1, 7.2, 7.3_
  - _Boundary: SoftDeletePreservationSuite_
  - _Depends: 1.2_

- [ ] 3. Validation: G-1 판정 및 재검증 트리거
- [ ] 3.1 전체 스위트 결합 실행 및 G-1 판정·재검증 트리거 기록
  - `uv run pytest tests/integration_L1` 전체를 실제 결합(마이그레이션 DB + 부팅 앱, mock 없음)에서 실행하여
    Requirement 2~7 스위트가 전부 통과하면 G-1 통과(=L2 `s05-workspace` impl 착수 선행 조건 충족)로, 하나라도
    실패하면 미통과(=L2 착수 차단)로 판정. 검증 실패는 원인 spec(s01/s02/s03)에서 수정 후 재실행하며 체크포인트에서
    feature 로직을 변경해 우회하지 않음. 재검증 트리거(`s01`/`s02`/`s03` 수정 시 이 체크포인트 및 이후 모든
    체크포인트를 누적 집합 기준 재실행)를 스위트 문서/주석으로 명시
  - 관찰 가능 완료: `uv run pytest tests/integration_L1`가 전부 통과하여 G-1 통과가 성립하고, 재검증 트리거 대상과
    L2 착수 가부가 명확히 기록된다
  - _Requirements: 1.4, 8.1, 8.2, 8.3_
  - _Depends: 2.1, 2.2, 2.3_
