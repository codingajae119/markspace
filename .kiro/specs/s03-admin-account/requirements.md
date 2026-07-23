# Requirements Document

## Introduction

`s03-admin-account`는 폐쇄형(closed) MarkSpace 서비스에서 회원 가입이 없는 대신 **단일 admin이 사용자
계정 생명주기를 수동 관리**하는 동작을 구현한다. 대상은 계정의 생성·목록 조회·삭제(flag)·비활동·재활성화와
admin에 의한 비밀번호 재설정이다.

이 spec은 `s01-contract-foundation`의 **단일 계약 소스**를 재사용하며 어떤 계약 엔티티도 재정의하지 않는다.
구체적으로 다음을 소비한다.

- **user 스키마**: `s01` 마이그레이션이 생성한 `user` 테이블(`login_id` UNIQUE, `is_admin`, `is_active`,
  `is_deleted`, `password_hash`, `name`, `email`, 타임스탬프).
- **세션 인증 의존성**: 현재 사용자·admin 여부를 담은 인증 컨텍스트(`s01` 세션 인증).
- **에러 모델**: 공통 에러 응답 스키마와 에러 코드 카탈로그(401/403/404/409/422/500).
- **스키마 규약**: `{Resource}Create/Read/Update` 명명과 Read 공통 베이스·`Page[T]` 목록 규약.
- **보안 헬퍼**: 비밀번호 해싱 단일 스킴(비밀번호 생성·재설정 시 사용).
- **불변식**: INV-3(admin 접근 무제약), INV-4(물리 삭제 없음).

산출물 언어는 한국어이며, 상위 근거로 `docs/projects.md` §3 REQ-1.6·REQ-2, §2.1 user 모델, §5 불변식을
참조한다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - admin에 의한 신규 사용자 계정 생성(REQ-2.2).
  - admin에 의한 사용자 계정 목록 조회(관리 대상 식별, REQ-2.2 지원).
  - admin에 의한 사용자 삭제 = `is_deleted = true` 전환(물리 삭제 없음, REQ-2.3, INV-4).
  - admin에 의한 사용자 비활동 처리 = `is_active = false`(로그인 금지, REQ-2.4).
  - admin에 의한 재활성화 = 삭제 flag 되돌림(REQ-2.5), `is_active`/`is_deleted`는 별개 상태로 관리.
  - admin에 의한 비밀번호 재설정(사용자 self-reset 없음, REQ-1.6).
  - 위 계정관리 엔드포인트의 admin 전용 접근 통제(비-admin 거부).
- **Out of scope (다른 spec이 소유)**:
  - 로그인·로그아웃·세션 발급·본인 비밀번호 변경(s02). 이 spec은 계정 상태(활동/삭제/비밀번호)만 생성하고
    로그인 시 그 상태를 해석하는 동작은 s02가 소유한다.
  - 워크스페이스 소유권 변경(REQ-2.7)은 **s05-workspace**가 소유한다. workspace 멤버십 자원이 필요하며
    roadmap과 brief가 s05로 배정한다. (참고: `s01` API 카탈로그 초기 기준선의 소유권 표기 조정 사항은 §Boundary
    Context 및 design의 Out of Boundary에서 명시.)
  - admin의 문서·데이터 무제약 접근(INV-3)은 `s01` 권한 resolver가 전 계층 공통으로 처리한다.
  - 문서·워크스페이스·첨부 등 계정 외 자원(s05 이상).
  - 프론트엔드 화면.
- **Adjacent expectations (인접 spec/계약에 대한 기대)**:
  - 계정 상태(`is_active`, `is_deleted`, `password_hash`)의 저장 형태는 `s01` user 스키마를 그대로 따르며,
    s02는 로그인 시 이 상태를 소비한다(비활동/삭제 로그인 거부는 s02 동작).
  - 모든 응답·오류는 `s01` 공통 스키마 규약·에러 모델을 따른다. 계약 시그니처를 벗어나는 구현은 계약 위반이다.

## Requirements

### Requirement 1: admin 전용 접근 통제

**Objective:** As a 서비스 운영자, I want 계정관리 엔드포인트가 admin 사용자에게만 허용되기를,
so that 일반 사용자가 타인 계정을 생성·삭제·재설정하지 못하도록 폐쇄형 관리 통제가 보장된다.

#### Acceptance Criteria

1. When 인증된 admin 사용자가 계정관리 엔드포인트에 접근하면, the Admin Account Service shall 요청을 허용하고
   해당 동작을 수행한다.
2. If 인증되었으나 admin이 아닌 사용자가 계정관리 엔드포인트에 접근하면, the Admin Account Service shall 요청을
   거부하고 403 공통 에러 응답을 반환한다.
3. If 인증되지 않은(세션 없음·무효) 요청이 계정관리 엔드포인트에 도달하면, the Admin Account Service shall 요청을
   거부하고 401 공통 에러 응답을 반환한다.
4. The Admin Account Service shall admin 여부 판정의 근거를 사용자 계정의 단일 admin 표시(`is_admin`)로만
   삼으며, 애플리케이션을 통한 admin 계정 생성·승격 수단을 제공하지 않는다.

### Requirement 2: 사용자 생성

**Objective:** As a admin, I want 신규 사용자 계정을 등록하기를, so that 회원 가입이 없는 폐쇄형 서비스에서
통제된 방식으로 사용자가 서비스에 접근할 수 있다.

#### Acceptance Criteria

1. When admin이 로그인 식별자·비밀번호·이름을 담아 사용자 생성을 요청하면, the Admin Account Service shall
   신규 user 계정을 생성하고 생성된 계정 정보를 반환한다.
2. The Admin Account Service shall 신규 계정을 활동 상태(`is_active = true`)·비삭제 상태(`is_deleted = false`)·
   비관리자(`is_admin = false`)로 생성한다.
3. When 사용자 생성 시 비밀번호가 제공되면, the Admin Account Service shall 비밀번호를 평문으로 저장하지 않고
   공통 해싱 스킴으로 변환하여 저장한다.
4. If 생성 요청의 로그인 식별자가 이미 존재하면, the Admin Account Service shall 계정을 생성하지 않고 409
   공통 에러 응답을 반환한다.
5. If 필수 항목(로그인 식별자·비밀번호·이름)이 누락되거나 형식이 유효하지 않으면, the Admin Account Service shall
   422 공통 에러 응답을 필드 단위 오류와 함께 반환한다.
6. Where 생성 요청에 관리자 표시나 상태 flag를 지정하려는 입력이 포함되어도, the Admin Account Service shall
   해당 입력을 계정 관리자 승격 수단으로 사용하지 않는다(관리자 여부는 애플리케이션에서 설정 불가).

### Requirement 3: 사용자 목록 조회

**Objective:** As a admin, I want 전체 사용자 계정 목록을 조회하기를, so that 삭제·비활동 대상 식별과 후속
계정관리 작업의 대상 계정을 확인할 수 있다.

#### Acceptance Criteria

1. When admin이 사용자 목록 조회를 요청하면, the Admin Account Service shall 사용자 계정 목록과 전체 개수를
   공통 목록 응답 규약으로 반환한다.
2. The Admin Account Service shall 목록 응답에 각 계정의 식별자·로그인 식별자·이름·관리자 여부·활동 여부·삭제
   여부·타임스탬프를 포함한다.
3. The Admin Account Service shall 삭제(`is_deleted = true`) 또는 비활동(`is_active = false`) 상태의 계정도
   목록에서 제외하지 않고 관리 대상으로 노출한다.
4. Where 사용자 수가 많은 경우, the Admin Account Service shall 페이지네이션 규약(항목·전체 개수)으로 목록을
   분할 조회할 수 있게 한다.

### Requirement 4: 사용자 삭제 (soft-delete)

**Objective:** As a admin, I want 사용자 계정을 삭제 처리하기를, so that 더 이상 활동하지 않는 계정을 정리하되
작성 이력과 참조 무결성은 보존된다.

#### Acceptance Criteria

1. When admin이 특정 사용자의 삭제를 요청하면, the Admin Account Service shall 해당 사용자의 `is_deleted`를
   true로 설정하고 레코드는 물리적으로 제거하지 않는다.
2. The Admin Account Service shall 삭제 처리 시 계정 레코드와 그 이름을 보존하여 문서 작성자·버전 히스토리
   표시가 유지될 수 있게 한다.
3. If 삭제 대상 사용자 식별자가 존재하지 않으면, the Admin Account Service shall 404 공통 에러 응답을 반환한다.
4. If 삭제 대상이 관리자(`is_admin = true`) 계정이면, the Admin Account Service shall 삭제를 거부하여 단일 admin
   잠금 상황을 방지한다.
5. The Admin Account Service shall 삭제 상태(`is_deleted`)를 비활동 상태(`is_active`)와 독립적으로 취급하여
   한 상태 변경이 다른 상태를 자동으로 바꾸지 않게 한다.

### Requirement 5: 사용자 비활동 처리

**Objective:** As a admin, I want 사용자 계정을 비활동 처리하기를, so that 계정을 삭제하지 않고도 로그인을
일시적으로 금지할 수 있다.

#### Acceptance Criteria

1. When admin이 특정 사용자의 비활동 처리를 요청하면, the Admin Account Service shall 해당 사용자의 `is_active`를
   false로 설정한다.
2. The Admin Account Service shall 비활동 상태를 로그인 금지의 근거 상태로 저장하되, 로그인 거부 동작 자체는
   인증 spec(s02)이 소비하도록 상태만 제공한다.
3. When admin이 비활동 계정을 다시 활동 처리하면, the Admin Account Service shall `is_active`를 true로 설정한다.
4. If 비활동 처리 대상 사용자 식별자가 존재하지 않으면, the Admin Account Service shall 404 공통 에러 응답을
   반환한다.
5. If 비활동 처리 대상이 관리자(`is_admin = true`) 계정이면, the Admin Account Service shall 비활동 처리를
   거부하여 단일 admin 잠금 상황을 방지한다.

### Requirement 6: 사용자 재활성화

**Objective:** As a admin, I want 삭제 처리된 사용자 계정을 되돌리기를, so that 실수 삭제나 재합류 시 기존
계정을 재사용할 수 있다.

#### Acceptance Criteria

1. When admin이 삭제된(`is_deleted = true`) 사용자의 삭제 flag 되돌림을 요청하면, the Admin Account Service shall
   `is_deleted`를 false로 설정하여 계정을 재활성화한다.
2. The Admin Account Service shall 재활성화가 삭제 flag만 되돌리며, 활동 여부(`is_active`)는 별개 상태로 유지되어
   자동으로 변경되지 않게 한다.
3. If 재활성화 대상 사용자 식별자가 존재하지 않으면, the Admin Account Service shall 404 공통 에러 응답을 반환한다.

### Requirement 7: admin 비밀번호 재설정

**Objective:** As a admin, I want 사용자의 비밀번호를 재설정하기를, so that 비밀번호를 분실한 사용자가 self-reset
없이 통제된 경로로 다시 접근할 수 있다.

#### Acceptance Criteria

1. When admin이 특정 사용자의 새 비밀번호를 담아 재설정을 요청하면, the Admin Account Service shall 해당 사용자의
   저장된 비밀번호를 새 값으로 갱신한다.
2. The Admin Account Service shall 새 비밀번호를 평문으로 저장하지 않고 공통 해싱 스킴으로 변환하여 저장한다.
3. The Admin Account Service shall 비밀번호 재설정을 admin 전용으로만 허용하며 사용자 self-reset 경로를 제공하지
   않는다.
4. If 재설정 대상 사용자 식별자가 존재하지 않으면, the Admin Account Service shall 404 공통 에러 응답을 반환한다.
5. If 새 비밀번호가 누락되거나 형식이 유효하지 않으면, the Admin Account Service shall 422 공통 에러 응답을
   반환한다.

### Requirement 8: 계약·에러·soft-delete 정합

**Objective:** As a 하위 spec 구현자·통합 체크포인트, I want 계정관리 동작이 `s01` 계약(스키마 규약·에러 모델·
soft-delete)을 벗어나지 않기를, so that 계약 드리프트 없이 s02·s04 체크포인트가 동일 기준으로 검증할 수 있다.

#### Acceptance Criteria

1. The Admin Account Service shall 모든 요청·응답 스키마를 `{Resource}Create/Read/Update` 명명·형태 규약과
   Read 공통 베이스·목록 규약(`Page`)에 맞춰 정의한다.
2. The Admin Account Service shall 모든 오류를 `s01` 공통 에러 응답 스키마·에러 코드 카탈로그로 반환한다.
3. Where 계정 삭제·비활동이 발생하는 경우, the Admin Account Service shall 레코드를 물리적으로 제거하지 않고
   flag 전환으로만 표현한다(INV-4).
4. The Admin Account Service shall `s01`이 정의한 user 스키마·세션 인증 의존성·보안 해싱 헬퍼·권한 컨텍스트를
   재구현하지 않고 재사용한다.
5. The Admin Account Service shall 계정관리 라우터를 `s01`이 제공하는 라우터 조립 지점에 연결하여 애플리케이션
   부트스트랩에 통합되게 한다.
