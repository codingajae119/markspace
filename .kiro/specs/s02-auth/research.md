# Research Log — s02-auth

## Discovery Scope

- **Feature type**: Extension(기존 s01 계약·인프라 위에 인증 동작을 얹는 통합 중심 feature). Full greenfield 아님 → **light discovery**.
- **대조 기준**: `s01-contract-foundation`의 `design.md`/`requirements.md`(단일 계약 소스). 새 계약 요소를 만들지 않고 재사용.
- **상위 근거**: `docs/projects.md` §3 REQ-1(1.1~1.5, 1.7), roadmap(L1 계층, s02는 s01에만 의존).

## Key Findings (s01 계약에서 재사용할 요소)

| 재사용 요소 | s01 위치 | s02에서의 사용 |
|-------------|----------|----------------|
| user 모델(login_id·password_hash·is_active·is_deleted·is_admin·name·email) | `app/models/user.py` | 로그인 조회, 상태 게이트, 비밀번호 갱신 |
| 세션 미들웨어(Starlette SessionMiddleware, 서명 쿠키, payload=user_id) | `app/main.py create_app` | 로그인 시 `session["user_id"]` write, 로그아웃 시 clear |
| `AuthContext`/`get_current_user` | `app/common/auth.py` | 보호 엔드포인트(logout·me·password) 현재 사용자 확정, 미인증/비활동/삭제 401 |
| `hash_password`/`verify_password`(Argon2id) | `app/common/security.py` | 로그인 자격 검증, 현재 비밀번호 확인, 새 비밀번호 해싱 |
| `DomainError`/`ErrorCode`/`ErrorResponse` | `app/common/errors.py` | 401(unauthenticated)·422(unprocessable/validation) 반환 |
| `get_db`·`SessionLocal` | `app/common/db.py` | 요청 스코프 DB 세션 |
| `ORMReadModel`/`TimestampedRead` | `app/schemas/base.py` | `AuthUserRead` 파생 |
| 엔드포인트 카탈로그 1~4번 | s01 design §API Catalog | `/auth/login`·`/auth/logout`·`/auth/me`·`/auth/password` 계약 |
| feature 라우터 조립 지점 | `app/main.py create_app` | auth 라우터 include |

## 설계 결정 (Decisions)

- **D1 — 로그인은 `get_current_user`를 사용하지 않는다.** 로그인은 세션이 아직 없는 상태에서 자격 증명으로 세션을
  **생성**하는 경로이므로, s01 세션 의존성(세션 존재 전제)과 분리한다. 로그인 서비스가 자체적으로 조회→검증→상태
  게이트→세션 write를 수행한다. logout·me·password는 세션이 이미 있으므로 `get_current_user`를 재사용한다.
- **D2 — 계정 상태 게이트를 로그인 경로에 명시 적용.** `get_current_user`는 이미 비활동/삭제를 401로 막지만, 로그인은
  세션 write 이전 경로라 별도 게이트가 필요하다. 순서: 사용자 조회 → 비밀번호 검증 → `is_active`/`is_deleted` 게이트 →
  세션 write. 실패는 모두 401 UNAUTHENTICATED **동일 메시지**로 반환(계정 열거 방지, REQ-1.3).
- **D3 — 현재 비밀번호 불일치는 422 unprocessable.** 사용자는 이미 인증된 상태이므로 401이 아니라 도메인 규칙 위반으로
  취급(s01 에러 카탈로그: 422 unprocessable = 도메인 규칙 위반). 새 비밀번호 정책 위반은 요청 검증 실패 → 422
  validation_error + field_errors(pydantic 검증 → s01 전역 핸들러).
- **D4 — auth 사용자 접근을 얇은 저장소로 캡슐화하되 범위를 인증으로 한정.** `find_by_login_id`(상태 무관 조회, 게이트는
  서비스가 판단), `get_by_id`, `update_password_hash`만 소유. 계정 생성·플래그 전환은 s03가 소유(경계 분리). 두 spec이
  `password_hash`를 각기 다른 흐름(본인 변경 vs admin 재설정)으로 쓰지만 동일 s01 해싱 헬퍼를 경유하므로 공유 소유 아님.
- **D5 — feature 패키지 배치.** steering `structure.md`의 레이어드+spec 정렬(auth/workspace/...)에 따라 `app/auth/`
  패키지(router/service/repository/schemas)로 응집. 라우터는 s01 `create_app` 조립 지점에 등록.
- **D6 — 로그아웃/비밀번호 변경 성공 응답은 본문 없음(204).** 카탈로그의 Response가 `—`인 항목과 정합.

## Synthesis 결과

- **일반화**: 인증에 필요한 모든 횡단 관심사(세션·해싱·에러·권한 판정)는 s01 common에 이미 단일 구현으로 존재 →
  s02는 **동작 조립(orchestration)**만 추가하고 새 공용 유틸을 만들지 않는다.
- **Build vs Adopt**: 전부 Adopt(s01 재사용). 신규는 auth 도메인 서비스·라우터·요청/응답 스키마뿐.
- **단순화**: 권한 resolver(`require_ws_role`)는 auth 경로에 워크스페이스 개념이 없어 사용하지 않는다. me/logout/password는
  "인증됨"만 요구하므로 `get_current_user`로 충분.

## Risks / Open Points

- **R1 — 세션 payload 키 정합**: s02가 write하는 세션 키(`user_id`)가 s01 `get_current_user`가 읽는 키와 반드시 일치해야
  한다. 구현 시 s01 `auth.py`의 세션 키 상수를 참조/재사용(하드코딩 중복 금지). 통합 테스트로 로그인→me 왕복 검증.
- **R2 — 계정 열거**: 로그인 실패 응답·타이밍을 통일. 최소한 응답 메시지·코드는 동일하게(401 UNAUTHENTICATED).
- **R3 — 세션 고정(session fixation)**: 서명 쿠키 세션 특성상 로그인 시 payload 교체로 충분하나, 필요 시 로그인 전
  기존 세션 clear 후 write. 본 spec 범위에서는 로그인 시 `user_id` 재설정으로 처리.

## References

- `s01-contract-foundation/design.md` §Common/Auth, §Common/Security, §Common/Errors, §API Endpoint Catalog(1~4), §Bootstrap.
- `docs/projects.md` §3 REQ-1(1.1~1.5, 1.7), §6(범위 밖: self sign-up).
- steering: `product.md`(폐쇄형·self sign-up 없음), `tech.md`(uv·pydantic·단일 Settings), `structure.md`(레이어드·spec 정렬·공통 권한/설정 단일화).
