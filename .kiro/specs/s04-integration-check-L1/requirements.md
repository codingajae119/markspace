# Requirements Document

## Introduction

`s04-integration-check-L1`은 **계층 1(L1)의 누적 통합 검증 체크포인트**다. 이 시점까지 완성된 upstream 누적
집합(`s01-contract-foundation` ⊕ `s02-auth` ⊕ `s03-admin-account`)이 공유 계약과 정합하는지, 그리고 이번 계층에서
처음 결합되는 **경계(계정 생명주기 ↔ 로그인)**가 실제 결합 상태에서 성립하는지 mock 없이 검증한다.

이 체크포인트는 **feature 로직을 구현하지 않는다.** 새 엔드포인트·서비스·스키마·마이그레이션을 추가하지 않으며,
오직 (1) 누적 upstream의 계약·경계 정합 검증과 (2) 그 검증을 실제 구현 결합으로 실행하는 integration/e2e 테스트만
소유한다. 검증의 유일한 대조 기준은 개별 spec(s02·s03)의 design이 아니라 **`s01-contract-foundation`의 단일 소스**
(데이터 스키마 · 세션/인증 API 계약 · 공통 에러 모델 · 불변식 카탈로그 INV-1~12)다.

이 체크포인트는 로드맵의 **게이트 G-1**을 담당한다: 이 체크포인트가 통과하기 전에는 L2(`s05-workspace`)의 impl을
착수할 수 없다. 또한 upstream(s01·s02·s03) 중 하나라도 수정되면 이 체크포인트를 누적 집합 기준으로 재실행하는
**재검증 트리거**의 최초 지점이다.

산출물 언어는 한국어이며, 상위 근거로 `docs/projects.md` §3 REQ-1·REQ-2, §5 INV-3·INV-4,
`s01-contract-foundation/design.md`(§Physical Data Model · §API Endpoint Catalog · §Errors · §Invariants Catalog),
`.kiro/steering/roadmap.md`(게이트·재검증 트리거)를 참조한다.

## Boundary Context

- **In scope (이 체크포인트가 소유)**:
  - **계약 대조 검증**: 실제 결합된 시스템의 user 스키마·세션/인증 API·admin 계정관리 API·공통 에러 모델이
    `s01` 단일 소스와 일치하는지 대조.
  - **cross-spec 경계 검증(이번 계층 신규 경계 = 계정 상태 ↔ 로그인)**:
    - admin 사용자 생성 → 그 사용자의 로그인 성공.
    - admin 비활동 처리(`is_active=false`) → 자격 증명이 맞아도 로그인 거부.
    - admin 삭제(`is_deleted=true`) → 로그인 거부.
    - admin 삭제 flag 되돌림(재활성화) → 다시 로그인 성공.
    - admin 비밀번호 재설정 → 새 비밀번호로 로그인 성공(이전 비밀번호 거부).
    - 사용자 본인 비밀번호 변경 → 새 비밀번호로 로그인, 이전 비밀번호 거부.
  - **불변식 보존 검증**: 물리 삭제 없음(INV-4) — 삭제 처리된 사용자 레코드·이름이 보존됨을 확인.
  - **게이트·재검증 판정**: 위 검증 전부가 mock 없이 통과함을 G-1 통과 조건으로 기록하고, 재검증 트리거 대상을 명시.
- **Out of scope (이 체크포인트가 소유하지 않음)**:
  - 새로운 feature 동작·엔드포인트·서비스·스키마·마이그레이션 구현(모두 s02·s03·s01 소유, 이미 완료 가정).
  - 검증 중 발견된 계약 위반의 **수정** — 원인 spec(s01/s02/s03)에서 고쳐야 하며, 체크포인트는 회귀를 포착·보고만 한다.
  - 워크스페이스·문서 등 상위 계층(L2 이상) 관심사(후속 체크포인트 s06 이상 담당).
  - 개별 spec 단위 검증의 재실행(각 spec의 자체 테스트 소유). 체크포인트는 **결합·경계**만 본다.
- **Adjacent expectations (인접 spec/계약에 대한 기대)**:
  - `s01`이 전체 DB 스키마 마이그레이션·세션 미들웨어·`get_current_user`·해싱 헬퍼·공통 에러 모델·라우터 조립
    지점·엔드포인트 카탈로그·불변식 카탈로그를 단일 소스로 제공한다.
  - `s02`가 카탈로그 1~4번(`/auth/login`·`/auth/logout`·`/auth/me`·`/auth/password`)의 동작과 로그인 계정 상태
    게이트(비활동·삭제 거부)를 구현하여 배치되어 있다.
  - `s03`가 카탈로그 5~8번(`/admin/users` CRUD·`/admin/users/{id}/password`)의 동작과 계정 생명주기(생성·비활동·
    삭제·재활성화·비밀번호 재설정)를 flag 전환(물리 삭제 없음)으로 구현하여 배치되어 있다.
  - `s02`·`s03`가 모두 `s01` 계약을 재정의 없이 재사용한다(계정 상태 표현·세션·에러 형태 정합).

## Requirements

### Requirement 1: 검증 방법론 및 대조 기준 (mock 없는 실제 결합 · s01 단일 소스)

**Objective:** As a L1 통합 체크포인트, I want 누적 upstream을 실제 구현으로 결합한 상태에서 단일 계약 소스에 대조
검증하기를, so that 계층 경계 회귀가 상위 계층으로 전파되기 전에 조기에 포착된다.

#### Acceptance Criteria

1. The L1 Integration Checkpoint shall 모든 검증을 mock·stub·가짜 구현 없이 실제 `s01`·`s02`·`s03` 구현을 결합한
   상태(마이그레이션 적용된 실제 DB + 실제 부팅된 애플리케이션 + 실제 서명 쿠키 세션)에서 수행한다.
2. The L1 Integration Checkpoint shall 계약 정합의 대조 기준을 항상 `s01-contract-foundation`의 단일 소스
   (데이터 스키마·엔드포인트 카탈로그·공통 에러 모델·불변식 카탈로그)로 삼으며, 개별 spec(s02·s03)의 design을
   기준으로 삼지 않는다.
3. The L1 Integration Checkpoint shall 어떤 feature 동작·엔드포인트·서비스·스키마·마이그레이션도 신규로 구현하지
   않고 검증 및 그 테스트 자산만 산출한다.
4. If 검증 대상 시스템에 계약을 위반하는 결합 회귀가 발견되면, the L1 Integration Checkpoint shall 이를 실패로
   보고하되 원인 spec에서의 수정을 유발할 뿐 체크포인트 내부에서 feature 로직을 변경하여 우회하지 않는다.

### Requirement 2: 계약 대조 — user 스키마 · 세션/인증 API · admin API · 에러 모델

**Objective:** As a L1 통합 체크포인트, I want 결합된 시스템의 스키마·API·에러 형태가 `s01` 단일 소스와 일치함을
확인하기를, so that s02·s03가 계약을 벗어난 드리프트 없이 동일 기준 위에 얹혀 있음을 보장한다.

#### Acceptance Criteria

1. The L1 Integration Checkpoint shall 마이그레이션이 적용된 실제 DB의 `user` 테이블이 `s01` 물리 데이터 모델
   (`login_id` UNIQUE, `password_hash`, `name`, `email`, `is_admin`, `is_active`, `is_deleted`, 타임스탬프)과
   컬럼·제약 면에서 일치함을 확인한다.
2. The L1 Integration Checkpoint shall 부팅된 애플리케이션에 `s01` 엔드포인트 카탈로그 1~4번(`/auth/login`,
   `/auth/logout`, `/auth/me`, `/auth/password`)이 카탈로그가 정한 경로·메서드·인증 요구대로 노출됨을 확인한다.
3. The L1 Integration Checkpoint shall 부팅된 애플리케이션에 `s01` 엔드포인트 카탈로그 5~8번(`/admin/users` 생성·
   목록·수정, `/admin/users/{id}/password`)이 카탈로그가 정한 경로·메서드·admin 요구대로 노출됨을 확인한다.
4. When 결합된 시스템의 임의 엔드포인트가 오류를 반환하면, the L1 Integration Checkpoint shall 응답이 `s01` 공통
   에러 응답 형태(`code`·`message`·선택적 `field_errors`)이고 상태 코드가 에러 코드 카탈로그(401/403/404/409/422)와
   일치함을 확인한다.
5. The L1 Integration Checkpoint shall 인증·계정 응답 본문에 `password_hash` 등 민감 필드가 포함되지 않음을 확인한다.

### Requirement 3: 계정 활성 경로 ↔ 로그인 허용 (생성 · 비밀번호 재설정)

**Objective:** As a L1 통합 체크포인트, I want admin이 만든 활성 계정과 admin이 재설정한 자격 증명이 로그인 경로에서
성립함을 확인하기를, so that 계정 생성·자격 관리(s03)와 로그인(s02)의 정방향 경계가 실제 결합에서 성립함을 보장한다.

#### Acceptance Criteria

1. When admin이 신규 사용자를 생성한 뒤 그 사용자가 올바른 자격 증명으로 로그인하면, the L1 Integration Checkpoint
   shall 로그인이 성공하고 세션이 발급됨을 확인한다.
2. When admin이 사용자의 비밀번호를 재설정한 뒤 그 사용자가 새 비밀번호로 로그인하면, the L1 Integration Checkpoint
   shall 로그인이 성공함을 확인한다.
3. If admin 비밀번호 재설정 이후 사용자가 재설정 이전의 옛 비밀번호로 로그인하면, the L1 Integration Checkpoint
   shall 로그인이 거부(401)됨을 확인한다.

### Requirement 4: 계정 비활성/삭제 경로 ↔ 로그인 거부

**Objective:** As a L1 통합 체크포인트, I want admin이 비활동·삭제 처리한 계정이 로그인 게이트에서 거부됨을 확인하기를,
so that 계정 상태 변경(s03)이 로그인 허용(s02)에 즉시·정확히 반영되는 경계가 성립함을 보장한다.

#### Acceptance Criteria

1. When admin이 사용자를 비활동(`is_active=false`) 처리한 뒤 그 사용자가 올바른 자격 증명으로 로그인을 시도하면,
   the L1 Integration Checkpoint shall 로그인이 거부(401)되고 세션이 발급되지 않음을 확인한다.
2. When admin이 사용자를 삭제(`is_deleted=true`) 처리한 뒤 그 사용자가 올바른 자격 증명으로 로그인을 시도하면,
   the L1 Integration Checkpoint shall 로그인이 거부(401)되고 세션이 발급되지 않음을 확인한다.
3. While 사용자가 이미 세션을 보유한 상태에서 admin이 그 사용자를 비활동 또는 삭제 처리하면, the L1 Integration
   Checkpoint shall 동일 세션 쿠키의 후속 보호 요청(예: `/auth/me`)이 401로 거부됨을 확인한다.

### Requirement 5: 재활성화 경로 ↔ 로그인 재허용

**Objective:** As a L1 통합 체크포인트, I want admin이 삭제 flag를 되돌린 계정이 다시 로그인 가능해짐을 확인하기를,
so that 재활성화(s03)와 로그인(s02)의 복원 경계가 성립하고 상태 독립성이 유지됨을 보장한다.

#### Acceptance Criteria

1. When admin이 삭제(`is_deleted=true`)된 사용자의 삭제 flag를 되돌리면(`is_deleted=false`), the L1 Integration
   Checkpoint shall 그 사용자가 올바른 자격 증명으로 다시 로그인에 성공함을 확인한다.
2. The L1 Integration Checkpoint shall 삭제 flag 되돌림이 `is_active` 상태를 자동으로 변경하지 않으며, 비활동 상태가
   유지된 계정은 삭제 flag를 되돌려도 여전히 로그인이 거부됨을 확인한다.

### Requirement 6: 본인 비밀번호 변경 ↔ 로그인 정합

**Objective:** As a L1 통합 체크포인트, I want 사용자가 본인 비밀번호를 변경한 뒤 로그인 자격이 정확히 갱신됨을
확인하기를, so that 본인 비밀번호 변경(s02)과 로그인(s02)의 자격 갱신 경계가 실제 결합에서 성립함을 보장한다.

#### Acceptance Criteria

1. When 인증된 사용자가 현재 비밀번호 확인 후 본인 비밀번호를 새 값으로 변경하면, the L1 Integration Checkpoint
   shall 그 사용자가 새 비밀번호로 로그인에 성공함을 확인한다.
2. If 본인 비밀번호 변경 이후 사용자가 변경 이전의 옛 비밀번호로 로그인하면, the L1 Integration Checkpoint shall
   로그인이 거부(401)됨을 확인한다.

### Requirement 7: 물리 삭제 없음(INV-4) 보존

**Objective:** As a L1 통합 체크포인트, I want 삭제 처리가 레코드를 물리적으로 제거하지 않고 이름 등 데이터를
보존함을 확인하기를, so that soft-delete 불변식(INV-4)이 계정 생명주기 경로 전반에서 유지됨을 보장한다.

#### Acceptance Criteria

1. When admin이 사용자를 삭제(`is_deleted=true`) 처리하면, the L1 Integration Checkpoint shall 해당 사용자 레코드가
   DB에 물리적으로 존재하며 flag만 전환되었음을 확인한다.
2. The L1 Integration Checkpoint shall 삭제 처리된 사용자의 이름·식별 정보가 보존되어 admin 목록 조회에서 삭제 상태로
   계속 노출됨을 확인한다.
3. The L1 Integration Checkpoint shall 계정 생명주기 검증 시나리오 어디에서도 user 레코드에 대한 물리 삭제가 발생하지
   않았음을 확인한다.

### Requirement 8: 게이트 G-1 판정 및 재검증 트리거

**Objective:** As a 로드맵 게이트 관리자, I want L1 검증 결과가 G-1 통과 여부와 재검증 대상을 명확히 산출하기를,
so that L2 impl 착수 가부와 upstream 변경 시 재실행 범위를 예측 가능하게 통제할 수 있다.

#### Acceptance Criteria

1. When Requirement 2~7의 모든 검증이 실제 결합 상태에서 통과하면, the L1 Integration Checkpoint shall G-1을 통과로
   판정하여 L2(`s05-workspace`) impl 착수의 선행 조건 충족을 기록한다.
2. If Requirement 2~7 중 하나라도 실패하면, the L1 Integration Checkpoint shall G-1을 미통과로 판정하고 L2 impl 착수를
   차단 상태로 표시한다.
3. The L1 Integration Checkpoint shall 재검증 트리거 대상을 명시한다: `s01`·`s02`·`s03` 중 어느 것이 수정되어도 이
   체크포인트(및 로드맵상 그 이후 모든 체크포인트)를 누적 집합 기준으로 재실행해야 한다.
