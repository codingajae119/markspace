# Requirements Document

## Introduction

`s02-auth`는 MarkSpace 폐쇄형 서비스의 **자격 증명 기반 인증** 기능을 소유한다. 사용자는 `login_id`/`password`로
로그인하여 세션을 발급받고, 로그아웃으로 세션을 종료하며, 본인 비밀번호를 변경할 수 있다. 자격 증명이 올바르더라도
비활동(`is_active=false`) 또는 삭제(`is_deleted=true`) 상태의 계정은 로그인이 차단된다.

이 spec은 상위 계약 `s01-contract-foundation`이 확정한 **단일 소스**를 재사용하며 재정의하지 않는다.

- **user 스키마**(login_id·password_hash·is_active·is_deleted·is_admin 등, s01 §Physical Data Model)
- **세션 인증 의존성**(`get_current_user`/`AuthContext`)과 세션 미들웨어(서명 쿠키, payload=user_id) — s01 소유
- **비밀번호 해싱 헬퍼**(`hash_password`/`verify_password`, Argon2id) — s01 소유
- **공통 에러 모델**(`ErrorResponse`/`ErrorCode`/`DomainError`) — s01 소유
- **API 엔드포인트 카탈로그**의 인증·계정 항목(1~4번: `/auth/login`, `/auth/logout`, `/auth/me`, `/auth/password`)과
  `{Resource}Create/Read/Update` 스키마 규약 — s01 소유

s02는 위 계약 위에서 로그인 자격증명 검증·세션 write/clear·본인 비밀번호 변경의 **동작(behavior)**만 구현한다.
계정 생성·삭제·비활동/재활성화·admin 비밀번호 재설정 등 계정 생명주기는 `s03-admin-account`가 소유한다.

산출물 언어는 한국어이며, 원 명세 `docs/projects.md` §3 REQ-1(1.1~1.5, 1.7)을 상위 근거로 참조한다.

## Boundary Context

- **In scope (이 spec이 소유)**:
  - `login_id`/`password` 자격 증명 검증과 세션 발급(로그인).
  - 세션 종료(로그아웃).
  - 현재 인증 사용자 정보 조회(세션 확인 경유).
  - 본인 비밀번호 변경(현재 비밀번호 확인 후 새 비밀번호로 갱신).
  - 로그인 경로의 계정 상태 게이트(비활동·삭제 거부).
- **Out of scope (다른 spec이 소유)**:
  - 사용자 계정 생성·삭제·비활동/재활성화, admin에 의한 비밀번호 재설정 — `s03-admin-account`.
  - 워크스페이스 권한·멤버십 판정 — `s05-workspace`(권한 resolver 자체는 s01 소유).
  - self sign-up(자가 가입)·비밀번호 분실 자가 재설정·SSO/OAuth — 프로젝트 범위 밖(`docs/projects.md` §6, roadmap).
  - user 스키마·세션 미들웨어·해싱 헬퍼·에러 모델·엔드포인트 카탈로그의 **정의** — `s01-contract-foundation`.
- **Adjacent expectations (s02가 s01 계약에 기대하는 것)**:
  - s01이 등록한 세션 미들웨어가 서명 쿠키 세션을 제공하여 s02가 세션에 `user_id`를 write/clear 할 수 있다.
  - s01 `get_current_user`가 보호 엔드포인트(로그아웃·me·비밀번호 변경)에서 현재 사용자를 확정하고,
    비활동/삭제 사용자·미인증 세션을 401로 거부한다.
  - s01 `verify_password`/`hash_password`가 `user.password_hash`와 동일 스킴으로 검증·갱신을 수행한다.
  - s01 `create_app`이 feature 라우터 조립 지점을 제공하여 s02 인증 라우터가 등록된다.

## Requirements

### Requirement 1: 자격 증명 로그인 및 세션 발급

**Objective:** As a 폐쇄형 서비스 사용자, I want `login_id`와 `password`로 로그인하여 세션을 발급받기를,
so that 이후 보호된 기능을 인증된 상태로 사용할 수 있다.

#### Acceptance Criteria

1. When 사용자가 올바른 `login_id`와 `password`를 제출하면, the Auth Service shall 저장된 비밀번호 해시로 자격 증명을 검증하고 세션을 생성하여 사용자를 로그인 상태로 만든다.
2. When 로그인이 성공하면, the Auth Service shall 현재 사용자의 비민감 식별 정보(식별자, `login_id`, 이름, admin 여부 등)를 반환한다.
3. If 제출된 `login_id`에 해당하는 사용자가 없거나 `password`가 일치하지 않으면, the Auth Service shall 401 공통 에러 응답으로 로그인을 거부하며 어떤 조건이 실패했는지 구분하지 않는다.
4. If 자격 증명이 올바르더라도 대상 계정이 비활동(`is_active=false`) 상태이면, the Auth Service shall 로그인을 거부하고 세션을 생성하지 않는다.
5. If 자격 증명이 올바르더라도 대상 계정이 삭제(`is_deleted=true`) 상태이면, the Auth Service shall 로그인을 거부하고 세션을 생성하지 않는다.
6. When 세션이 생성되면, the Auth Service shall 세션 payload에 사용자 식별자만 저장하고 비밀번호 등 민감 정보를 포함하지 않는다.
7. Where 로그인 성공 응답이 사용자 정보를 포함하는 경우, the Auth Service shall `password_hash` 등 민감 필드를 응답에서 제외한다.

### Requirement 2: 로그아웃 및 세션 종료

**Objective:** As a 인증된 사용자, I want 로그아웃으로 현재 세션을 종료하기를,
so that 동일 쿠키로의 후속 요청이 더 이상 인증되지 않는다.

#### Acceptance Criteria

1. When 인증된 사용자가 로그아웃을 요청하면, the Auth Service shall 현재 세션을 종료한다.
2. While 세션이 종료된 상태에서, the Auth Service shall 동일 세션 쿠키로의 후속 보호 요청을 인증 실패(401)로 처리한다.
3. If 인증되지 않은 요청이 로그아웃을 호출하면, the Auth Service shall 401 공통 에러 응답을 반환한다.

### Requirement 3: 현재 인증 사용자 정보 조회

**Objective:** As a 인증된 사용자, I want 현재 세션이 가리키는 내 정보를 조회하기를,
so that 클라이언트가 로그인 상태와 사용자 신원을 확인할 수 있다.

#### Acceptance Criteria

1. When 인증된 사용자가 자신의 정보를 요청하면, the Auth Service shall 현재 세션이 가리키는 사용자의 비민감 식별 정보를 반환한다.
2. If 세션이 없거나 유효하지 않으면, the Auth Service shall 401 공통 에러 응답을 반환한다.
3. If 세션이 비활동(`is_active=false`) 또는 삭제(`is_deleted=true`) 사용자를 가리키면, the Auth Service shall 인증을 거부(401)한다.

### Requirement 4: 본인 비밀번호 변경

**Objective:** As a 인증된 사용자, I want 현재 비밀번호 확인 후 새 비밀번호로 변경하기를,
so that 본인 계정의 자격 증명을 스스로 안전하게 갱신할 수 있다.

#### Acceptance Criteria

1. When 인증된 사용자가 올바른 현재 비밀번호와 새 비밀번호를 제출하면, the Auth Service shall 저장된 비밀번호 해시를 새 비밀번호의 해시로 갱신한다.
2. If 제출된 현재 비밀번호가 저장된 값과 일치하지 않으면, the Auth Service shall 변경을 거부하고 도메인 규칙 위반(422) 공통 에러 응답을 반환한다.
3. If 새 비밀번호가 정책(최소 길이 등)을 만족하지 못하면, the Auth Service shall 필드 단위 검증 오류(422)를 포함한 공통 에러 응답을 반환한다.
4. The Auth Service shall 비밀번호를 평문으로 저장하지 않고 s01 공용 해싱 스킴으로만 저장한다.
5. The Auth Service shall 비밀번호 변경 대상을 항상 현재 인증 사용자로 한정하여 타인의 비밀번호를 변경하지 못하게 한다.
6. If 인증되지 않은 요청이 비밀번호 변경을 호출하면, the Auth Service shall 401 공통 에러 응답을 반환한다.

### Requirement 5: 계약·경계 준수

**Objective:** As a 하위 spec·통합 체크포인트, I want s02가 s01 계약을 재정의 없이 재사용하고 경계를 지키기를,
so that 인증 경로가 단일 계약 소스와 정합하고 계약 드리프트가 발생하지 않는다.

#### Acceptance Criteria

1. The Auth Service shall s01 계약의 세션 인증 의존성, 비밀번호 해싱 헬퍼, 공통 에러 모델, user 스키마를 재구현하지 않고 재사용한다.
2. The Auth Service shall s01 엔드포인트 카탈로그가 정의한 인증 경로(`/auth/login`, `/auth/logout`, `/auth/me`, `/auth/password`)와 요구 권한(로그인·me·로그아웃·비밀번호 변경의 인증 요구 여부)을 그대로 구현한다.
3. The Auth Service shall self sign-up(자가 가입) 및 비밀번호 분실 자가 재설정 엔드포인트를 제공하지 않는다.
4. The Auth Service shall 계정 생성·삭제·비활동/재활성화·admin 비밀번호 재설정을 수행하지 않는다.
5. The Auth Service shall 모든 오류를 s01 공통 에러 응답(`ErrorResponse`) 형태로 반환한다.
