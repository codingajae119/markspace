# Implementation Plan — s03-admin-account

> admin 계정 생명주기 feature spec. 모든 명령은 `backend/`에서 `uv run` 기준. 산출물 언어 한국어, 코드 식별자는 영어.
> `s01-contract-foundation`의 계약(user 모델·세션 인증·에러 모델·해싱 헬퍼·Base Schemas·권한 게이트
> `require_admin`·라우터 조립 지점)을 재사용하며 재정의하지 않는다. 모든 삭제·비활동은 flag 전환만 수행한다(INV-4).

- [ ] 1. Foundation: feature 모듈·스키마·admin 게이트
- [x] 1.1 admin_account 모듈 스캐폴드 및 User 스키마 정의
  - `app/admin_account/` 패키지(`__init__.py`, `router.py`, `service.py`, `repository.py`, `schemas.py`)
    골격 생성 (feature-local `dependencies.py`는 생성하지 않음 — `require_admin`은 s01 common 재사용)
  - `schemas.py`에 `s01` Base Schemas를 상속한 `UserCreate`(login_id/password/name/email), `UserRead`
    (`TimestampedRead` 상속, is_admin/is_active/is_deleted 포함, password 미노출), `UserUpdate`(name/email/
    is_active/is_deleted 부분 갱신, is_admin 미포함), `AdminPasswordResetRequest`(new_password) 정의
  - 관찰 가능 완료: `UserCreate`가 필수 항목 누락 시 검증 오류를 내고, ORM user 객체로부터 `UserRead`가
    `password_hash` 없이 직렬화되며, `UserUpdate`에 `is_admin` 필드가 존재하지 않음을 단위 테스트로 확인
  - _Requirements: 2.1, 2.5, 2.6, 3.2, 7.5, 8.1_
  - _Boundary: UserSchemas_
- [x] 1.2 (P) s01 require_admin 게이트 소비 (feature-local 정의 없음)
  - s03는 자체 게이트를 정의하지 않는다. `s01` common 권한 모듈의 `require_admin`(`AuthContext.is_admin` 기반,
    비-admin→403)을 그대로 import하여 계정관리 라우트에 부착할 수 있도록 소비한다. `require_admin`의 정의·동작은
    s01이 소유하며 s03는 재정의하지 않는다(권한 단일 구현 규칙)
  - 관찰 가능 완료: s01 `require_admin`을 부착한 라우트가 admin `AuthContext`→통과, 비-admin→403, 비인증은
    `get_current_user`에서 401로 산출됨을 라우터 테스트로 확인 (게이트 정의 자체의 단위 테스트는 s01 소유)
  - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - _Boundary: s01 require_admin 소비 (게이트 재정의 없음)_
  - _Depends: 1.1_

- [ ] 2. Core: 리포지토리·서비스
- [x] 2.1 (P) UserRepository 구현 (조회·생성·flag 전환)
  - `repository.py`에 `s01` user 모델·`get_db` 세션 기반 `get_by_id`, `get_by_login_id`,
    `list_paginated`(limit/offset, 삭제·비활동 포함, total 반환), `create`(is_admin=False·is_active=True·
    is_deleted=False 기본값), `apply_updates`(flag/필드 전환), `set_password_hash` 구현
  - 제약: 어떤 경로에서도 물리 DELETE를 발행하지 않는다(INV-4)
  - 관찰 가능 완료: `create`가 기본 상태 계정 행을 만들고, `apply_updates`가 `is_deleted`/`is_active`를
    독립적으로 전환하며 레코드가 삭제되지 않고, `list_paginated`가 삭제 계정을 포함해 items·total을 반환함을
    단위 테스트로 확인
  - _Requirements: 2.2, 3.1, 3.3, 3.4, 4.1, 5.1, 6.1, 7.1, 8.3_
  - _Boundary: UserRepository_
  - _Depends: 1.1_
- [x] 2.2 AdminAccountService 구현 (계정 생명주기 로직)
  - `service.py`에 `create_user`(login_id 중복→409, `s01` `hash_password`로 해싱, 기본 상태 생성),
    `list_users`(`Page[UserRead]` 반환), `update_user`(대상 미존재→404, admin 대상의 is_active=false 또는
    is_deleted=true 전환→409 단일 admin 잠금 방지, is_active·is_deleted 독립 갱신, 재활성화=is_deleted=false),
    `reset_password`(미존재→404, 새 비밀번호 해싱 저장) 구현. 도메인 오류는 `s01` `DomainError`로 raise
  - 관찰 가능 완료: 정상 생성 계정이 활동·비삭제·비관리자이고 비밀번호가 해시로 저장되며, 중복 login_id→409,
    미존재 대상→404, admin 계정 비활동/삭제 시도→409, 재활성화가 `is_active`를 바꾸지 않음을 단위 테스트로 확인
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3, 7.4, 8.2, 8.4_
  - _Boundary: AdminAccountService_
  - _Depends: 2.1_

- [ ] 3. Integration: 라우터·부트스트랩 연결
- [x] 3.1 AdminUserRouter 4개 엔드포인트 구현
  - `router.py`에 `POST /admin/users`(UserCreate→UserRead), `GET /admin/users`(limit/offset→Page[UserRead]),
    `PATCH /admin/users/{id}`(UserUpdate→UserRead), `POST /admin/users/{id}/password`
    (AdminPasswordResetRequest→본문 없음) 구현. 전 라우트에 `Depends(require_admin)`(s01 common 재사용) 부착, 서비스에 위임
  - 관찰 가능 완료: 각 라우트가 admin 세션→정상 응답, 비-admin→403, 비인증→401을 반환하고 스키마 검증 실패는
    422 `ErrorResponse`로 직렬화됨을 단위/라우터 테스트로 확인
  - _Requirements: 1.1, 1.2, 1.3, 2.2, 3.1, 4.1, 5.1, 6.1, 7.1, 7.5, 8.1, 8.2_
  - _Boundary: AdminUserRouter_
  - _Depends: 1.2, 2.2_
- [ ] 3.2 s01 라우터 조립 지점에 admin 라우터 연결
  - `s01` `create_app()`의 feature 라우터 조립 지점(`app/main.py` 또는 `app/routers/__init__.py`)에
    `include_router(admin_account.router)` 추가
  - 관찰 가능 완료: `uv run uvicorn app.main:app` 부팅 후 `/admin/users` 경로가 앱 라우트 목록에 노출됨을 확인
  - _Requirements: 8.5_
  - _Depends: 3.1_

- [ ] 4. Validation: 계약·생명주기 통합 검증
- [ ] 4.1 계정 생명주기·계약·soft-delete 통합 테스트
  - 마이그레이션된 DB + 부팅 앱에서: (1) admin 세션 `POST /admin/users`→201, 비-admin→403, 비인증→401,
    (2) 생성→`GET /admin/users` 목록 노출→`PATCH` 삭제(is_deleted=true)→목록에 삭제 상태로 계속 노출→재활성화
    (is_deleted=false) 왕복, (3) `POST /admin/users/{id}/password` 후 저장 비밀번호가 새 해시로 갱신(평문 아님),
    (4) 삭제·비활동 경로에서 레코드가 물리적으로 제거되지 않음(INV-4) 검증하는 통합 테스트 작성
  - 관찰 가능 완료: 위 4개 시나리오 통합 테스트가 실제 앱 컨텍스트에서 모두 통과한다
  - _Requirements: 1.2, 1.3, 2.2, 3.1, 3.3, 4.1, 6.1, 7.1, 7.2, 8.3, 8.5_
  - _Depends: 3.2_
