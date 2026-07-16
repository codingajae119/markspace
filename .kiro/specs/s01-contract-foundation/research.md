# Research & Design Decisions — s01-contract-foundation

## Summary
- **Feature**: `s01-contract-foundation`
- **Discovery Scope**: New Feature (greenfield 계약 + 공용 런타임 인프라)
- **Key Findings**:
  - `docs/projects.md` §2는 7개 테이블만 정의하고 **session 테이블·is_admin 컬럼은 없다**. 세션은 서명 쿠키(stateless),
    admin은 user 테이블의 수동 설정 플래그로 확정하는 것이 §2와 REQ-2.1을 동시에 만족하는 유일한 정합 해석이다.
  - 스택은 FastAPI + SQLAlchemy 2.0(sync) + Alembic + MySQL 8(PyMySQL) + pydantic-settings v2로 고정.
    Windows/uv 환경에서 C 빌드 툴체인이 필요 없는 순수 파이썬 드라이버(PyMySQL)와 prebuilt wheel(pwdlib[argon2])을 선택.
  - 서명 쿠키 세션은 Starlette `SessionMiddleware`를 **adopt**(자체 구현 대신)하고, 비밀번호 해싱은 `pwdlib[argon2]`를
    공용 헬퍼로 감싸 s02/s03이 동일 스킴을 재사용하도록 계약화한다.

## Research Log

### 스택 버전·통합 (2026 기준, uv add 대상)
- **Context**: 계약 spec 자체가 마이그레이션·부팅으로 검증되어야 하므로 실제 라이브러리 선택·버전을 확정해야 한다.
- **Sources Consulted**: FastAPI/SQLAlchemy/Alembic/pydantic-settings/pwdlib/PyMySQL PyPI·공식 문서(2026-07 조사).
- **Findings**:
  - `fastapi>=0.139`, `uvicorn[standard]>=0.35`
  - `sqlalchemy>=2.0.51,<2.1` (2.1은 베타), sync 엔진 + PyMySQL이 MySQL 8의 주류 조합
  - `pymysql>=1.1` — 100% 순수 파이썬, Windows에서 컴파일러/헤더 불필요(mysqlclient는 C 확장으로 빌드 툴체인 요구)
  - `alembic>=1.18` — `alembic revision --autogenerate` 후 수동 검토, `alembic upgrade head`/`downgrade`
  - `pydantic-settings>=2.14` + `pyyaml>=6.0` — YAML은 기본 소스 체인에 없으므로 `settings_customise_sources` 재정의 필수
  - `itsdangerous>=2.2` — Starlette `SessionMiddleware`가 서명에 사용
  - `pwdlib[argon2]>=0.3` — passlib 대체(Python 3.13에서 제거된 crypt·bcrypt 4.x 비호환 회피), Argon2id 기본, prebuilt cp313 wheel
- **Implications**: 모든 선택이 Windows/uv 환경에서 빌드 툴체인 없이 설치 가능. URL은 `mysql+pymysql://…?charset=utf8mb4` 사용.

### pydantic-settings 단일 Settings (config.yml + .env 병합)
- **Findings**: `YamlConfigSettingsSource`는 기본 체인에 없어 `settings_customise_sources`를 재정의해 포함해야 하며,
  반환 튜플의 좌측이 우선순위가 높다 → env/.env가 yaml을 override. `model_config`에 `yaml_file`, `env_file` 지정.
- **Implications**: 비밀 아닌 값은 config.yml, secret은 .env로 자연 분리되며 단일 `Settings`로 접근(REQ-2 충족).

### 서명 쿠키 세션 (SessionMiddleware)
- **Findings**: `request.session`은 dict 인터페이스. `request.session["user_id"]=…`(로그인, s02), `request.session.clear()`(로그아웃, s02).
  쿠키는 서명(위변조 방지)일 뿐 암호화가 아니므로 user_id 같은 식별자만 저장. secret은 .env.
- **Implications**: session 테이블 불필요 → §2의 7테이블 스키마와 정합. s01은 미들웨어 등록 + 세션에서 user_id를 읽어 사용자 확정하는
  인증 의존성만 소유. 세션 write(login/logout)는 s02 소유.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 레이어드(선택) | api(router) → service → repository → domain/model, 횡단 common(config/errors/security/deps) | steering structure.md와 정렬, 계층별 의존 방향 강제, 하위 spec이 동일 뼈대 재사용 | 초기 보일러플레이트 | s01은 common + model + 빈 router 조립 지점만 채운다 |
| 서버측 세션 테이블 | session 테이블 추가 | 즉시 무효화 용이 | §2 스키마에 없는 8번째 테이블 추가 → 계약 드리프트 | 기각 |
| admin을 config에 login_id로 지정 | Settings에 admin_login_id | 스키마 무변경 | "DB에 수동 설정"(REQ-2.1) 문언과 불일치, DB 플래그가 더 명시적 | 기각 |

## Design Decisions

### Decision: 세션은 서명 쿠키(Starlette SessionMiddleware) — 서버측 session 테이블 없음
- **Context**: REQ-1.1은 "세션 생성"을 요구하나 §2 데이터 모델에 session 테이블이 없다. s01 스코프의 스키마는 정확히 7개.
- **Alternatives Considered**: 1) 서버측 session 테이블(스키마 확장) 2) 서명 쿠키(stateless)
- **Selected Approach**: Starlette `SessionMiddleware` 서명 쿠키 채택. 세션 payload에 `user_id`만. secret은 `.env`.
- **Rationale**: §2의 7테이블 계약을 깨지 않으면서 세션 요구를 충족. adopt로 자체 서명 코드 불필요.
- **Trade-offs**: 즉시 서버측 무효화 불가(만료·secret 회전으로 대응). 폐쇄형·소규모 서비스에 수용 가능.
- **Follow-up**: s02가 로그인 성공 시 세션 write, 로그아웃 시 clear.

### Decision: admin은 user 테이블의 `is_admin` 플래그(수동 설정)로 확정
- **Context**: REQ-2.1 "admin은 단일 계정이며 DB에 수동 설정". §2 user 논리 모델에는 명시 컬럼이 없으나 §2는 "DDL은 design에서 확정"이라 명시.
- **Alternatives Considered**: 1) `is_admin` boolean 컬럼 2) Settings의 admin_login_id
- **Selected Approach**: user에 `is_admin BOOLEAN NOT NULL DEFAULT FALSE` 추가. 단일 admin 행만 수동으로 true.
- **Rationale**: "DB에 수동 설정" 문언과 정합. INV-3 admin bypass가 인증 컨텍스트의 `is_admin`을 단일 출처로 읽는다.
- **Trade-offs**: 다중 admin이 스키마상 가능해지나 제품 정책(단일 admin)으로 통제(범위 밖 §6).
- **Follow-up**: s03 admin 계정관리가 이 플래그를 신뢰. 애플리케이션에 admin 생성 기능 없음(REQ-2.1).

### Decision: 비밀번호 해싱을 공용 헬퍼(pwdlib[argon2])로 계약화
- **Context**: s02(비번 변경)·s03(비번 재설정)이 동일 해싱 스킴으로 password_hash를 써야 드리프트가 없다.
- **Selected Approach**: `pwdlib.PasswordHash.recommended()`(Argon2id)를 감싼 공용 `security` 헬퍼(hash/verify) 제공.
- **Rationale**: 단일 해싱 계약으로 s02/s03 일관성 보장. passlib의 3.13 비호환 회피.
- **Trade-offs**: s01이 (비록 로그인 로직은 아니지만) 해싱 유틸을 소유 → 공용 인프라 범위로 수용.
- **Follow-up**: 실제 자격증명 검증 흐름은 s02.

### Decision: 권한 resolver는 요구 role을 파라미터로 받는 재사용 의존성
- **Context**: 문서·휴지통·공유 등 다수 라우터가 워크스페이스 role 검사를 반복한다. 중복·드리프트 방지 필요(structure.md).
- **Selected Approach**: `require_ws_role(min_role)` 형태의 의존성 팩토리. owner≥editor≥viewer 위계, admin이면 무조건 통과(INV-3).
- **Rationale**: 라우터는 요구 role만 선언, 판정 로직은 단일 구현.
- **Trade-offs**: 리소스→워크스페이스 매핑(문서 id→workspace_id 등)은 각 feature가 제공해야 함 → 계약으로 명시.
- **Follow-up**: s05가 멤버십을 실제로 채우기 전까지 resolver는 빈 멤버십에 대해 admin만 통과. 각 feature가 자원 매핑 주입.

### Decision: API 계약·불변식은 실행 코드가 아닌 계약 문서(카탈로그)로 소유
- **Context**: 엔드포인트 동작은 각 feature 소유. s01은 시그니처·소유권·불변식 매핑만 고정한다.
- **Selected Approach**: design.md 내에 엔드포인트 카탈로그 표 + `{Resource}Create/Read/Update` 규약 + INV-1~12 매핑 표를 단일 소스로 둔다.
- **Rationale**: 계약과 구현을 분리하되 하위 spec·체크포인트가 참조할 단일 기준을 문서로 고정.
- **Trade-offs**: 문서-코드 동기화 책임은 각 feature impl과 체크포인트가 진다.

## Risks & Mitigations
- **Alembic autogenerate가 MySQL ENUM/타입 일부를 놓침** — 초기 마이그레이션은 수기 검토·보정, downgrade 왕복 테스트로 검증.
- **서명 쿠키 즉시 무효화 불가** — 만료(max_age)와 필요 시 secret 회전으로 대응(폐쇄형·소규모 수용).
- **권한 resolver의 자원→WS 매핑 누출** — 매핑은 각 feature가 주입하도록 계약으로 못 박아 upstream에 downstream 가정 유입 방지.
- **계약 드리프트** — 통합 체크포인트가 이 단일 소스에만 대조. 계약 변경 시 전 체크포인트 재실행(roadmap 재검증 트리거).

## References
- [FastAPI](https://pypi.org/project/fastapi/), [SQLAlchemy 2.0 MySQL dialect](https://docs.sqlalchemy.org/en/20/dialects/mysql.html)
- [Alembic autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
- [pydantic-settings](https://pypi.org/project/pydantic-settings/), [YAML source 패턴 issue #202](https://github.com/pydantic/pydantic-settings/issues/202)
- [Starlette middleware/sessions](https://www.starlette.io/middleware/), [pwdlib](https://pypi.org/project/pwdlib/)
- 상위 계약 근거: `docs/projects.md` §2 데이터 모델 · §3 EARS · §4 상태 전이 · §5 불변식
