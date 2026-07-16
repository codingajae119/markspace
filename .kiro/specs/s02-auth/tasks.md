# Implementation Plan — s02-auth

> s01 계약·공용 인프라를 재사용하는 인증 동작 spec. 모든 명령은 `backend/`에서 `uv run` 기준. 산출물 언어 한국어,
> 코드 식별자는 영어. 세션 의존성·해싱 헬퍼·에러 모델·user 모델은 s01 소유이므로 **재정의 없이 재사용**하며
> `app/common/*`은 수정하지 않는다(단, s01 `create_app`의 feature 라우터 조립 지점 연결만 예외).

- [ ] 1. Foundation: 인증 스키마·데이터 접근
- [x] 1.1 (P) 인증 요청/응답 스키마 정의
  - `app/auth/schemas.py`에 `LoginRequest`(login_id, password), `AuthUserRead`(id, login_id, name, email, is_admin — s01 `ORMReadModel` 상속), `PasswordChangeRequest`(current_password, new_password + 최소 길이 등 정책 검증) 정의
  - `AuthUserRead`는 `password_hash` 등 민감 필드를 절대 포함하지 않음
  - 관찰 가능 완료: User ORM 객체로부터 `AuthUserRead`가 직렬화되며 결과에 `password_hash`가 없고, `PasswordChangeRequest`의 정책 위반 입력이 pydantic 검증 오류를 발생시키는 단위 테스트가 통과한다
  - _Requirements: 1.2, 1.7, 4.3, 5.5_
  - _Boundary: AuthSchemas_
- [x] 1.2 (P) 인증용 user 저장소 구현
  - `app/auth/repository.py`에 `AuthUserRepository` 구현: `find_by_login_id`(상태 무관 조회), `get_by_id`, `update_password_hash`(commit 포함). s01 `User` 모델과 `get_db` 세션 재사용
  - 계정 생성·삭제·플래그 전환은 구현하지 않음(s03 경계)
  - 관찰 가능 완료: `find_by_login_id`가 비활동/삭제 사용자도 반환하고, `update_password_hash` 후 재조회 시 저장 해시가 교체됨이 단위/통합 테스트로 확인된다
  - _Requirements: 1.1, 4.1, 5.1_
  - _Boundary: AuthUserRepository_

- [ ] 2. Core: 인증 서비스 동작
- [x] 2.1 로그인 자격 검증·계정 상태 게이트·세션 발급 서비스
  - `app/auth/service.py`의 `AuthService.authenticate` 구현: `find_by_login_id` → s01 `verify_password` → `is_active`/`is_deleted` 게이트. 성공 시 라우터가 전달한 세션 매핑에 s01 세션 키(상수 재사용)로 `user_id` 기록 후 `AuthUserRead` 반환
  - 실패(미존재·비밀번호 불일치·비활동·삭제)는 사유 불문 `DomainError(UNAUTHENTICATED, 401)` 동일 코드·메시지로 계정 열거 방지
  - 관찰 가능 완료: 올바른 자격 → 세션에 user_id 기록·`AuthUserRead` 반환, 미존재/비밀번호 불일치/`is_active=false`/`is_deleted=true` → 각각 동일한 401을 반환하는 단위 테스트가 통과한다
  - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.6, 5.4_
  - _Boundary: AuthService_
  - _Depends: 1.2_
- [x] 2.2 로그아웃·현재 사용자 조회 서비스
  - `AuthService.logout`(세션 clear)과 `AuthService.get_me`(`AuthContext.user_id`로 사용자 로드 → `AuthUserRead` 매핑) 구현
  - 관찰 가능 완료: `logout` 호출 후 세션 매핑에 `user_id`가 없고, `get_me`가 컨텍스트 사용자의 `AuthUserRead`를 반환하는 단위 테스트가 통과한다
  - _Requirements: 2.1, 3.1_
  - _Boundary: AuthService_
  - _Depends: 1.1, 1.2_
- [x] 2.3 본인 비밀번호 변경 서비스
  - `AuthService.change_password` 구현: `ctx.user_id`로 사용자 로드 → 현재 비밀번호 `verify_password`(불일치 시 `DomainError(UNPROCESSABLE, 422)`) → s01 `hash_password` → `update_password_hash`. 대상은 항상 현재 인증 사용자로 한정
  - 관찰 가능 완료: 올바른 현재 비밀번호 → 저장 해시가 새 비밀번호 해시로 갱신되고, 현재 비밀번호 불일치 → 422 unprocessable을 반환하며 대상이 ctx.user_id로 고정됨이 단위 테스트로 확인된다
  - _Requirements: 4.1, 4.2, 4.4, 4.5, 5.4_
  - _Boundary: AuthService_
  - _Depends: 1.2_

- [ ] 3. Integration: 라우터·앱 조립
- [x] 3.1 인증 라우터 구현
  - `app/auth/router.py`에 `POST /auth/login`(공개, `request.session` 전달), `POST /auth/logout`(204), `GET /auth/me`, `POST /auth/password`(204) 구현. logout·me·password는 s01 `Depends(get_current_user)`로 인증 강제
  - 경로·메서드·요구 인증은 s01 카탈로그 1~4번과 동일. self sign-up·자가 재설정 엔드포인트는 만들지 않음
  - 관찰 가능 완료: 4개 엔드포인트가 등록되고, 미인증 상태로 logout/me/password 호출 시 401(s01), login 성공 시 200 `AuthUserRead`가 반환됨이 라우터 단위/통합 테스트로 확인된다
  - _Requirements: 1.2, 2.2, 2.3, 3.2, 3.3, 4.6, 5.2_
  - _Boundary: AuthRouter_
  - _Depends: 2.1, 2.2, 2.3_
- [ ] 3.2 create_app 조립 지점에 인증 라우터 등록
  - s01 `app/main.py` `create_app`의 feature 라우터 조립 지점에 `app.include_router(auth.router)` 추가. `app/common/*`은 수정하지 않음
  - 관찰 가능 완료: `uv run uvicorn app.main:app` 기동 후 OpenAPI/라우트 목록에 `/auth/login`·`/auth/logout`·`/auth/me`·`/auth/password`가 노출되고 common 모듈 diff가 없음이 확인된다
  - _Requirements: 5.1, 5.3_
  - _Depends: 3.1_

- [ ] 4. Validation: 통합·계약 정합 검증
- [ ] 4.1 로그인·계정 상태 게이트 통합 테스트
  - 마이그레이션된 DB(s01)와 부팅 앱에서: 올바른 자격 → 200 + 세션 쿠키 발급, 잘못된 자격 → 401, `is_active=false`/`is_deleted=true` 사용자 → 401(동일 응답)을 mock 없이 검증. `AuthUserRead`에 `password_hash` 부재 확인
  - 관찰 가능 완료: 로그인 성공/실패/비활동/삭제 4개 시나리오 통합 테스트가 통과하고 응답 본문에 민감 필드가 없다
  - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.6, 1.7_
  - _Depends: 3.2_
- [ ] 4.2 로그아웃·me·미인증 접근 통합 테스트
  - 로그인 → `GET /auth/me` 200(세션 키 정합) → `POST /auth/logout` 204 → 동일 쿠키 재요청 401 왕복 검증. 세션 없이 logout/me/password 호출 → 401 검증
  - 관찰 가능 완료: login→me→logout→재요청 왕복과 미인증 보호 접근 401이 통합 테스트로 통과한다
  - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3_
  - _Depends: 3.2_
- [ ] 4.3 비밀번호 변경 e2e 및 계약 경계 검증
  - 로그인 → 비밀번호 변경 204 → 이전 비밀번호 로그인 401 → 새 비밀번호 로그인 200 e2e 검증. 현재 비밀번호 불일치 422, 새 비밀번호 정책 위반 422(field_errors), 미인증 변경 401 검증. 라우터 경로가 s01 카탈로그 1~4와 일치하고 계정 생성·삭제·admin 재설정 엔드포인트가 없으며 모든 오류가 s01 `ErrorResponse` 형태임을 확인
  - 관찰 가능 완료: 비밀번호 변경 e2e와 예외 케이스(422/401)가 통합 테스트로 통과하고, 카탈로그 경로 일치·계정 생명주기 엔드포인트 부재·공통 에러 형태가 검증된다
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4_
  - _Depends: 3.2_

## Implementation Notes
- 세션 키 상수: s01 `app/common/auth.py:64`는 `session.get("user_id")` **리터럴**을 쓰며 내보낸 상수가 없다. `app/common/*` 수정 금지이므로 s02는 `app/auth/service.py`에 `SESSION_USER_KEY = "user_id"`를 정의해 미러링한다(값이 s01과 반드시 일치해야 s01 `get_current_user`가 세션을 읽는다). 세션 write/clear(2.1·2.2) 및 통합 테스트(4.x)는 이 상수를 재사용한다.
