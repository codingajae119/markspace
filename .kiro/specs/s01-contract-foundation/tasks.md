# Implementation Plan — s01-contract-foundation

> 계약 + 공용 런타임 인프라 spec. 모든 명령은 `backend/`에서 `uv run` 기준. 산출물 언어 한국어, 코드 식별자는 영어.
> 계약 문서(엔드포인트 카탈로그·불변식 카탈로그·`{Resource}Create/Read/Update` 규약)의 단일 소스는 `design.md`이며,
> 아래 태스크는 그 계약을 실행/검증 가능한 공용 인프라로 구현하고 계약 완전성을 테스트로 고정한다.

- [ ] 1. Foundation: 실행 환경·단일 설정·DB 접속 뼈대
- [x] 1.1 uv 의존성 추가 및 앱 패키지 스캐폴드
  - `uv add`로 fastapi, uvicorn[standard], sqlalchemy(<2.1), pymysql, alembic, pydantic-settings, pyyaml, itsdangerous, pwdlib[argon2] 추가
  - `app/`, `app/common/`, `app/models/`, `app/schemas/`, `app/routers/`, `migrations/` 패키지 골격 생성
  - 관찰 가능 완료: `uv run python -c "import fastapi, sqlalchemy, alembic, pydantic_settings, pymysql, itsdangerous, pwdlib"`가 오류 없이 종료하고 `pyproject.toml`/`uv.lock`에 의존성이 기록된다
  - _Requirements: 8.1_
- [x] 1.2 단일 Settings 로더 구현 (config.yml + .env)
  - `config.py`에 `Settings`(pydantic-settings)와 `settings_customise_sources`로 YAML 소스 포함, `get_settings()` 캐시 접근자, `sqlalchemy_url` 프로퍼티 구현
  - `config.yml`(비밀 아닌 값: db_host/port/name/user, default_trash_retention_days, file_storage_root, session_cookie_name/max_age)와 `.env.example`(db_password, session_secret) 작성
  - 관찰 가능 완료: config.yml+.env 로드 시 `Settings` 인스턴스가 생성되고, 필수 secret(session_secret/db_password) 누락 시 부팅이 ValidationError로 실패한다(단위 테스트로 확인)
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  - _Boundary: Settings_
- [x] 1.3 DB engine·세션 팩토리·Base·get_db 의존성 구현
  - `common/db.py`에 `Base(DeclarativeBase)`, `engine`(Settings의 URL, pool_pre_ping), `SessionLocal`, 요청 스코프 `get_db()` 구현
  - 관찰 가능 완료: `get_db()`가 세션을 yield하고 종료 시 close하며, `SELECT 1`이 성공한다(로컬 MySQL 8 또는 통합 테스트 컨테이너 기준)
  - _Requirements: 1.9, 8.3_
  - _Boundary: Db_
  - _Depends: 1.2_

- [ ] 2. 데이터 스키마 마이그레이션 (전체 DB 계약)
- [x] 2.1 (P) SQLAlchemy 모델 7테이블 + is_admin 정의
  - `models/`에 user(+is_admin), workspace, workspace_member, document, document_version, attachment, share_link을 `design.md` 물리 모델(컬럼·타입·ENUM·nullable)대로 정의하고 `models/__init__.py`가 `Base.metadata`를 노출
  - 제약: login_id UNIQUE, (workspace_id,user_id) UNIQUE, token UNIQUE, ENUM(role/status/kind), 자기참조 document.parent_id, soft-delete 컬럼(is_deleted/status/is_archived)
  - 관찰 가능 완료: `Base.metadata.tables`가 7개 테이블과 지정 컬럼·유일제약을 포함한다(단위 테스트로 확인)
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_
  - _Boundary: Models_
  - _Depends: 1.3_
- [x] 2.2 Alembic 초기 마이그레이션 0001 작성 (upgrade/downgrade)
  - `alembic.ini`·`migrations/env.py`(Settings에서 URL 주입, `target_metadata = Base.metadata`) 구성
  - `0001_initial_schema.py`에 7테이블+is_admin 생성(upgrade)과 완전 역전(downgrade), 인덱스(soft-delete 필터용 포함)·외래키·유일제약 포함
  - 관찰 가능 완료: `uv run alembic upgrade head`가 7테이블을 생성하고 `information_schema`에서 컬럼/인덱스/유일제약이 확인된다
  - _Requirements: 1.1, 1.9, 1.10, 1.11_
  - _Boundary: Migration_
  - _Depends: 2.1_
- [x] 2.3 마이그레이션 적용·왕복 통합 테스트
  - `upgrade head` 후 7테이블·is_admin·인덱스·UNIQUE(login_id, token, (workspace_id,user_id))·ENUM 존재를 검증하고, `downgrade base`로 스키마가 원복됨을 검증
  - 관찰 가능 완료: upgrade→검증→downgrade→재검증 통합 테스트가 통과한다
  - _Requirements: 1.1, 1.10, 1.11_
  - _Depends: 2.2_

- [ ] 3. 공용 런타임 인프라 (common)
- [x] 3.1 (P) 공통 에러 모델·코드 카탈로그·전역 예외 핸들러
  - `common/errors.py`에 `FieldError`, `ErrorResponse`, `ErrorCode`(401/403/404/409/422/500), `DomainError` 기반 예외, `register_error_handlers(app)` 구현
  - RequestValidationError→422+field_errors, HTTPException·DomainError→코드·상태 매핑, 미처리 예외→500(내부 세부정보 미노출) 변환
  - 관찰 가능 완료: 각 예외 유형이 `ErrorResponse` 형태(code/message/field_errors)로 직렬화됨을 단위 테스트로 확인
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_
  - _Boundary: Errors_
  - _Depends: 1.1_
- [x] 3.2 (P) 비밀번호 해싱 공용 헬퍼
  - `common/security.py`에 pwdlib(Argon2id) 기반 `hash_password`/`verify_password` 구현
  - 관찰 가능 완료: hash→verify 왕복이 True, 잘못된 비밀번호는 False를 반환하는 단위 테스트가 통과한다
  - _Requirements: 4.3_
  - _Boundary: Security_
  - _Depends: 1.1_
- [x] 3.3 (P) 공용 Read 스키마 규약(Base Schemas)
  - `schemas/base.py`에 `ORMReadModel`(from_attributes), `TimestampedRead`, `Page[T]` 정의 및 `{Resource}Create/Read/Update` 명명 규약 문서 주석
  - 관찰 가능 완료: ORM 객체로부터 `TimestampedRead`가 직렬화되고 `Page[T]`가 items/total을 담는 단위 테스트가 통과한다
  - _Requirements: 6.2, 6.5_
  - _Boundary: BaseSchemas_
  - _Depends: 1.1_
- [x] 3.4 세션 인증 의존성 구현
  - `common/auth.py`에 `AuthContext(user_id, is_admin)`와 `get_current_user(request, db)` 구현: 세션 payload user_id로 사용자 로드, `is_active`·`is_deleted` 검사, is_admin 노출
  - 세션 없음/무효/비활동/삭제 → `DomainError(UNAUTHENTICATED, 401)`
  - 관찰 가능 완료: 미설정 세션→401, 비활동/삭제 사용자→401, 정상 사용자→AuthContext(is_admin 반영)을 단위 테스트로 확인
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
  - _Boundary: SessionAuth_
  - _Depends: 1.3, 2.1, 3.1_
- [ ] 3.5 워크스페이스 권한 resolver + admin 게이트 구현
  - `common/permissions.py`에 `Role(IntEnum)`, `WorkspaceRoleResolver`(workspace_member 조회, owner≥editor≥viewer), `require_ws_role(min)` 의존성 팩토리 구현: admin이면 무조건 통과(INV-3), 미충족 시 403
  - 동일 `common/permissions.py`에 admin 전용 `require_admin(ctx=Depends(get_current_user)) -> AuthContext` 의존성 단일 정의: `not ctx.is_admin`이면 표준 403 `DomainError(FORBIDDEN)` raise, admin이면 통과. admin 전용 엔드포인트(카탈로그 row 5–9)가 이 단일 정의를 소비하며 feature spec은 재정의하지 않는다(권한 검사 단일화)
  - 관찰 가능 완료: role 충족→통과, 미충족→403, admin→bypass 통과, viewer의 editor 요구 작업 거부, `require_admin`이 비-admin→403·admin→통과를 단위 테스트로 확인
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_
  - _Boundary: PermissionResolver_
  - _Depends: 2.1, 3.4_

- [ ] 4. 애플리케이션 부트스트랩·health (integration)
- [ ] 4.1 create_app 조립 지점 구현
  - `app/main.py`에 `create_app()`: Settings 로드, `SessionMiddleware`(session_secret/cookie/max_age) 등록, `register_error_handlers`, health 라우터 include, feature 라우터 조립 지점(초기 비어있음) 마련. 기존 `backend/main.py`는 실행 래퍼로 정리
  - 관찰 가능 완료: `uv run uvicorn app.main:app`이 오류 없이 기동되고, 미처리 예외가 500 `ErrorResponse`로 변환된다
  - _Requirements: 8.1, 8.4, 8.5, 8.6_
  - _Depends: 1.2, 3.1, 3.4_
- [ ] 4.2 health 라우터(+DB 연결 점검)
  - `app/routers/`에 `GET /health` 구현: `HealthRead{status, db}` 반환, 경량 `SELECT 1`로 DB 연결 여부 반영
  - 관찰 가능 완료: `GET /health` → 200 `{status:"ok", db:"ok"}`, DB 중단 시 `db:"down"`
  - _Requirements: 8.2, 8.3_
  - _Depends: 1.3, 4.1_

- [ ] 5. 계약 완전성 확정 및 통합 검증 (validation)
- [ ] 5.1 API 엔드포인트 카탈로그·스키마 규약 일관성 검증
  - `design.md` 엔드포인트 카탈로그가 8개 도메인(REQ-1~8)을 빠짐없이 열거하고 각 항목이 요구 role·요청/응답 스키마·소유 spec(s02~s14)을 표기하는지 점검하는 체크 테스트/검증 스크립트 작성, `{Resource}Create/Read/Update` 규약 준수 확인
  - 관찰 가능 완료: 카탈로그의 모든 엔드포인트가 소유 spec과 스키마 이름을 가지며 명명 규약을 위반하지 않음이 검증 테스트로 통과한다
  - _Requirements: 6.1, 6.3, 6.4, 6.6_
  - _Depends: 3.3_
- [ ] 5.2 도메인 불변식 카탈로그(INV-1~12) 매핑 검증
  - `design.md` 불변식 카탈로그가 INV-1~12 전부를 계약 요소(스키마/권한 resolver/상태 컬럼/공유 계약)와 소유 spec에 매핑하는지 점검하는 체크 테스트/검증 작성(권한 INV-1·2·3↔resolver/auth, INV-4↔soft-delete, INV-8↔share_link, INV-10·11·12↔status/trashed_at)
  - 관찰 가능 완료: 12개 불변식이 각각 계약 요소·소유 spec에 매핑되어 있음이 검증 테스트로 통과한다
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_
  - _Depends: 2.1, 3.4, 3.5_
- [ ] 5.3 부팅·health·인증·권한 결선 통합 검증
  - 마이그레이션된 DB 위에서 앱 부팅→`GET /health`(db:ok)→보호 스텁 라우트에 `Depends(require_ws_role(EDITOR))` 부착 시 미인증 401·비멤버 403·admin bypass 통과를 확인하는 통합 테스트 작성
  - 관찰 가능 완료: 부팅·health·세션 의존성·권한 resolver가 실제 앱 컨텍스트에서 함께 동작함이 통합 테스트로 통과한다
  - _Requirements: 4.1, 4.2, 5.3, 5.5, 8.1, 8.2, 8.3_
  - _Depends: 2.2, 3.4, 3.5, 4.2_

## Implementation Notes

- **환경**: dev MySQL 8 @ 127.0.0.1:3306 (root/1234), DB `notion_lite`(앱)·`notion_lite_test`(테스트) 생성됨. `backend/.env`(gitignored)에 dev secret, `.env.example`은 placeholder만.
- **2.1→2.2**: 모델은 Python-side `default=`만 사용(모델 boundary). DDL-level `DEFAULT`(is_admin/is_active/is_deleted/is_shareable/is_enabled BOOLEAN, trash_retention_days=30, status=active)는 마이그레이션(2.2)이 `server_default`로 명시해야 함.
- **2.1 순환 FK**: document.current_version_id ↔ document_version.id 는 nullable + `use_alter=True`(name="fk_document_current_version")로 해소. 마이그레이션도 이 FK를 `create_table` 이후 `create_foreign_key`(ALTER)로 분리 생성해야 함.
- **Windows 인코딩**: `alembic.ini`는 configparser가 시스템 로캘(cp949)로 읽어 한글 주석이 UnicodeDecodeError를 유발. alembic.ini는 ASCII-only로 유지할 것. `alembic check`("No new upgrade operations detected")로 모델↔마이그레이션 드리프트 없음을 기계적으로 확인 가능.
- **DB 상태**: 2.2 완료 후 DB는 `base`(빈 상태, alembic_version 테이블만 존재). 마이그레이션 검증 태스크는 자체 fixture로 upgrade/downgrade 제어.
- **DB 테스트 격리 패턴(재사용)**: DB 접근 테스트는 `notion_lite_test`에 대해 `DB_NAME=notion_lite_test`+`get_settings.cache_clear()` 후 `get_settings().sqlalchemy_url`로 **fresh engine**를 새로 만든다(모듈 레벨 `app.common.db.engine`는 import 시점에 dev DB로 바인딩되어 재사용 불가). teardown에서 테이블 drop+DB_NAME 복원+cache_clear. `tests/test_migration_roundtrip.py`·`tests/test_auth.py` 참고.
