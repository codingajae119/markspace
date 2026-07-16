"""계약 대조 스위트 (Task 2.1 / Req 2.1, 2.2, 2.3, 2.4, 2.5, 7.2).

실제 결합된 런타임(마이그레이션 적용 DB + 부팅 앱 + 실 세션)을 **s01-contract-foundation
단일 소스**와 대조하는 외부 관찰자 스위트다. 대조 기준은 s02/s03 의 design 이 아니라 항상
s01(`design.md` §Physical Data Model · §API Endpoint Catalog · §Errors)이며, 실제 앱이 s01
계약에서 벗어났다면 단언을 약화시키지 않고 그대로 실패시켜 드리프트를 표면화한다
(design.md §계약 대조 판정 · §Error Categories "계약 드리프트").

네 개의 단언 그룹:

- **Group 1 — user 테이블 스키마 vs s01 물리 모델(Req 2.1)**: 마이그레이션된 DB 의
  `information_schema` 를 조회해 컬럼 집합·nullability·`login_id` UNIQUE 를 s01 user 물리
  모델과 대조한다.
- **Group 2 — 엔드포인트 카탈로그 1~8 노출(Req 2.2, 2.3)**: 부팅 앱의 OpenAPI 가 s01 카탈로그
  1~8 을 정확한 경로·메서드로 노출하고, auth/admin 게이트가 런타임에서 실제로 강제됨을 확인.
- **Group 3 — 에러 모델 vs s01 에러 카탈로그(Req 2.4)**: 401/403/404/409/422 를 실제로 유발해
  상태코드와 `ErrorResponse` 형태(`{code, message, field_errors?}`)·`code` 문자열을 대조.
- **Group 4 — 민감 필드 부재(Req 2.5, 7.2)**: 인증·계정 응답 본문에 `password_hash`/`password`
  가 존재하지 않음을 확인.

하네스(:func:`~tests.integration_L1.conftest.harness`)가 제공하는 실 결합 환경 위에서만
동작하며 mock 을 쓰지 않는다.
"""

from sqlalchemy import text

from tests.integration_L1 import helpers

# s01 §Physical Data Model — user 테이블 계약(단일 소스).
# 컬럼명 → nullability("NO" = NOT NULL, "YES" = NULLable).
S01_USER_COLUMNS_NULLABILITY = {
    "id": "NO",
    "login_id": "NO",
    "password_hash": "NO",
    "name": "NO",
    "email": "YES",
    "is_admin": "NO",
    "is_active": "NO",
    "is_deleted": "NO",
    "created_at": "NO",
    "updated_at": "YES",
}

# 타입 계열(브리틀한 정확 문자열 대신 MySQL 타입 계열로 경량 검증).
# BOOLEAN → tinyint, BIGINT → bigint, 문자열 → varchar, 타임스탬프 → datetime.
S01_USER_TYPE_FAMILY = {
    "id": "bigint",
    "login_id": "varchar",
    "password_hash": "varchar",
    "name": "varchar",
    "email": "varchar",
    "is_admin": "tinyint",
    "is_active": "tinyint",
    "is_deleted": "tinyint",
    "created_at": "datetime",
    "updated_at": "datetime",
}

# s01 §API Endpoint Catalog rows 1~8 — (경로, 메서드) 계약. 경로 파라미터는 `user_id`.
S01_ENDPOINT_CATALOG_1_TO_8 = [
    ("/auth/login", "post"),
    ("/auth/logout", "post"),
    ("/auth/me", "get"),
    ("/auth/password", "post"),
    ("/admin/users", "post"),
    ("/admin/users", "get"),
    ("/admin/users/{user_id}", "patch"),
    ("/admin/users/{user_id}/password", "post"),
]

# 민감 필드(어떤 응답 본문에도 노출 금지) — s01 UserRead/AuthUserRead 계약.
SENSITIVE_FIELDS = ("password_hash", "password")


def _assert_error_response_shape(body: object) -> None:
    """관측된 에러 본문이 s01 ``ErrorResponse`` 형태를 따르는지 강제한다(Req 2.4).

    최소 계약(s01 §Errors): 문자열 ``code`` 와 문자열 ``message`` 키를 가지며,
    ``field_errors`` 가 존재하면 리스트다(``{code, message, field_errors?}``).
    """
    assert isinstance(body, dict), f"에러 본문은 JSON 객체여야 한다: {body!r}"
    assert isinstance(body.get("code"), str), f"code 는 문자열이어야 한다: {body!r}"
    assert isinstance(body.get("message"), str), f"message 는 문자열이어야 한다: {body!r}"
    if "field_errors" in body and body["field_errors"] is not None:
        assert isinstance(body["field_errors"], list), (
            f"field_errors 가 존재하면 리스트여야 한다: {body!r}"
        )


def _assert_no_sensitive_fields(user_obj: object, where: str) -> None:
    """사용자 객체(응답 본문)에 민감 필드가 하나도 없음을 강제한다(Req 2.5)."""
    assert isinstance(user_obj, dict), f"{where}: 사용자 객체는 dict 여야 한다: {user_obj!r}"
    for field in SENSITIVE_FIELDS:
        assert field not in user_obj, (
            f"{where}: 민감 필드 {field!r} 가 응답 본문에 노출되어서는 안 된다: "
            f"keys={sorted(user_obj.keys())}"
        )


# --- Group 1 — user 테이블 스키마 vs s01 물리 데이터 모델 (Req 2.1) ------------------


def test_user_table_columns_match_s01_physical_model(harness):
    """마이그레이션된 user 테이블의 컬럼 집합·nullability 가 s01 물리 모델과 정확히 일치.

    `information_schema.columns` 를 조회해 (1) 컬럼 집합이 s01 계약과 정확히 같고,
    (2) 각 컬럼 nullability(NOT NULL / NULLable)가 s01 과 일치하며, (3) 문자열/불리언/정수/
    타임스탬프 타입 계열이 일치함을 대조한다. 드리프트 시 어떤 컬럼이 어긋났는지 메시지에
    명시한다(design.md §계약 대조 판정).
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT column_name, is_nullable, data_type "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'user'"
            )
        ).all()

    assert rows, "마이그레이션된 DB 에 user 테이블 컬럼이 존재해야 한다(스키마 미적용?)"

    observed = {row[0]: (row[1].upper(), row[2].lower()) for row in rows}

    # (1) 컬럼 집합이 s01 계약과 정확히 일치(누락·초과 없음).
    expected_cols = set(S01_USER_COLUMNS_NULLABILITY)
    observed_cols = set(observed)
    missing = expected_cols - observed_cols
    extra = observed_cols - expected_cols
    assert not missing, f"user 테이블에 s01 계약 컬럼 누락: {sorted(missing)}"
    assert not extra, f"user 테이블에 s01 계약 밖 컬럼 초과: {sorted(extra)}"

    # (2) 각 컬럼 nullability 가 s01 과 일치.
    for col, expected_nullable in S01_USER_COLUMNS_NULLABILITY.items():
        observed_nullable = observed[col][0]
        assert observed_nullable == expected_nullable, (
            f"user.{col} nullability 드리프트: s01={expected_nullable} "
            f"관측={observed_nullable}"
        )

    # (3) 타입 계열이 s01 과 일치(브리틀한 정확 문자열 대신 계열 대조).
    for col, expected_family in S01_USER_TYPE_FAMILY.items():
        observed_family = observed[col][1]
        assert observed_family == expected_family, (
            f"user.{col} 타입 계열 드리프트: s01={expected_family} "
            f"관측={observed_family}"
        )


def test_user_login_id_has_unique_constraint(harness):
    """user.login_id 에 UNIQUE 제약이 존재함을 확인(s01: login_id VARCHAR(255) NOT NULL UNIQUE).

    `information_schema.statistics` 에서 login_id 컬럼에 대한 non_unique=0 인덱스를 찾아
    유일성 제약을 확인한다(제약/인덱스명은 관례상 `uq_user_login_id` 이나 이름에 의존하지
    않고 컬럼 유일성 자체를 단언한다).
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT index_name, non_unique "
                "FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = 'user' "
                "AND column_name = 'login_id'"
            )
        ).all()

    assert rows, "user.login_id 에 대한 인덱스가 존재해야 한다(UNIQUE 계약)"
    unique_indexes = [row[0] for row in rows if int(row[1]) == 0]
    assert unique_indexes, (
        f"user.login_id 에 UNIQUE 인덱스(non_unique=0)가 없다: 관측 인덱스={rows!r}"
    )


# --- Group 2 — API 엔드포인트 카탈로그 1~8 노출 (Req 2.2, 2.3) ----------------------


def test_openapi_exposes_catalog_endpoints_1_to_8(harness):
    """부팅 앱의 OpenAPI 가 s01 카탈로그 1~8 을 정확한 경로·메서드로 노출.

    각 (경로, 메서드) 쌍이 `app.openapi()["paths"]` 에 존재함을 확인한다(경로 파라미터는
    s01 이 정한 `user_id` 명명). 이는 인증·계정 API 표면이 s01 카탈로그와 정합함을 보증한다.
    """
    paths = harness.app.openapi()["paths"]

    for path, method in S01_ENDPOINT_CATALOG_1_TO_8:
        assert path in paths, (
            f"카탈로그 경로 {path!r} 가 앱 OpenAPI 에 노출되어야 한다: "
            f"관측 경로={sorted(paths)}"
        )
        methods = {m.lower() for m in paths[path]}
        assert method in methods, (
            f"카탈로그 {method.upper()} {path} 가 노출되어야 한다: "
            f"관측 메서드={sorted(methods)}"
        )


def test_auth_required_endpoint_without_session_returns_401(harness):
    """인증 요구 엔드포인트를 세션 없이 호출하면 401(게이트 런타임 강제, Req 2.2)."""
    client = harness.new_client()
    resp = client.get("/auth/me")
    assert resp.status_code == 401, (
        f"미인증 GET /auth/me 는 401 이어야 한다: {resp.status_code} {resp.text}"
    )


def test_admin_endpoint_as_non_admin_returns_403(harness):
    """인증된 비-admin 이 admin 엔드포인트를 호출하면 403(admin 게이트 강제, Req 2.3)."""
    admin = harness.login_admin()
    login_id = helpers.unique_login_id()
    password = "non-admin-pw-123"
    helpers.create_user(admin, login_id, password, name="비관리자")

    non_admin = harness.login(login_id, password)
    resp = non_admin.post(
        "/admin/users",
        json={
            "login_id": helpers.unique_login_id(),
            "password": "another-pw-123",
            "name": "생성 시도",
        },
    )
    assert resp.status_code == 403, (
        f"비-admin 의 POST /admin/users 는 403 이어야 한다: "
        f"{resp.status_code} {resp.text}"
    )


def test_admin_endpoint_unauthenticated_returns_401(harness):
    """admin 엔드포인트를 미인증으로 호출하면 401(인증 게이트 우선, Req 2.3)."""
    client = harness.new_client()
    resp = client.get("/admin/users")
    assert resp.status_code == 401, (
        f"미인증 GET /admin/users 는 401 이어야 한다: {resp.status_code} {resp.text}"
    )


# --- Group 3 — 에러 모델 vs s01 에러 카탈로그 (Req 2.4) -----------------------------


def test_error_401_unauthenticated(harness):
    """미인증 보호 요청 → 401 + code=unauthenticated + ErrorResponse 형태."""
    resp = harness.new_client().get("/auth/me")
    assert resp.status_code == 401, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "unauthenticated", (
        f"401 은 s01 카탈로그상 code=unauthenticated 여야 한다: {body!r}"
    )


def test_error_403_forbidden(harness):
    """인증된 비-admin 의 admin 라우트 → 403 + code=forbidden + ErrorResponse 형태."""
    admin = harness.login_admin()
    login_id = helpers.unique_login_id()
    password = "forbidden-pw-123"
    helpers.create_user(admin, login_id, password, name="비관리자")

    non_admin = harness.login(login_id, password)
    resp = non_admin.get("/admin/users")
    assert resp.status_code == 403, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "forbidden", (
        f"403 은 s01 카탈로그상 code=forbidden 여야 한다: {body!r}"
    )


def test_error_404_not_found(harness):
    """admin PATCH /admin/users/{존재하지 않는 id} → 404 + code=not_found."""
    admin = harness.login_admin()
    resp = admin.patch("/admin/users/999999999", json={"name": "없는 사용자"})
    assert resp.status_code == 404, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "not_found", (
        f"404 는 s01 카탈로그상 code=not_found 여야 한다: {body!r}"
    )


def test_error_409_conflict(harness):
    """admin 이 같은 login_id 로 두 번째 사용자 생성 → 409 + code=conflict."""
    admin = harness.login_admin()
    login_id = helpers.unique_login_id()
    helpers.create_user(admin, login_id, "conflict-pw-123", name="원본 사용자")

    resp = admin.post(
        "/admin/users",
        json={
            "login_id": login_id,  # 동일 login_id 재사용 → 충돌.
            "password": "conflict-pw-456",
            "name": "중복 사용자",
        },
    )
    assert resp.status_code == 409, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "conflict", (
        f"409 는 s01 카탈로그상 code=conflict 여야 한다: {body!r}"
    )


def test_error_422_validation_error_has_field_errors(harness):
    """스키마 위반(필수 필드 누락) → 422 + code=validation_error + 비어있지 않은 field_errors.

    `POST /admin/users` 에서 필수 필드 `name` 을 누락하면 pydantic 이 s01 전역 핸들러를 통해
    422 `validation_error` 와 비어있지 않은 `field_errors` 로 응답한다.
    """
    admin = harness.login_admin()
    resp = admin.post(
        "/admin/users",
        json={
            "login_id": helpers.unique_login_id(),
            "password": "missing-name-pw-123",
            # 필수 필드 `name` 누락 → 스키마 검증 실패.
        },
    )
    assert resp.status_code == 422, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "validation_error", (
        f"422 스키마 위반은 s01 카탈로그상 code=validation_error 여야 한다: {body!r}"
    )
    assert isinstance(body.get("field_errors"), list) and len(body["field_errors"]) > 0, (
        f"스키마 검증 오류는 비어있지 않은 field_errors 를 포함해야 한다: {body!r}"
    )


# --- Group 4 — 민감 필드 부재 (Req 2.5, 7.2) ---------------------------------------


def test_auth_me_body_has_no_sensitive_fields(harness):
    """GET /auth/me(인증) 응답 본문에 password_hash/password 부재."""
    client = harness.login_admin()
    resp = client.get("/auth/me")
    assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
    _assert_no_sensitive_fields(resp.json(), "GET /auth/me")


def test_auth_login_body_has_no_sensitive_fields(harness):
    """POST /auth/login(200) 응답 본문에 password_hash/password 부재."""
    resp = harness.new_client().post(
        "/auth/login",
        json={
            "login_id": harness.admin_login_id,
            "password": harness.admin_password,
        },
    )
    assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
    _assert_no_sensitive_fields(resp.json(), "POST /auth/login")


def test_admin_users_bodies_have_no_sensitive_fields(harness):
    """POST /admin/users(201) 및 GET /admin/users(목록 items)에 민감 필드 부재 (Req 2.5, 7.2)."""
    admin = harness.login_admin()
    login_id = helpers.unique_login_id()

    create = admin.post(
        "/admin/users",
        json={
            "login_id": login_id,
            "password": "sensitive-check-pw-123",
            "name": "민감필드 확인 사용자",
        },
    )
    assert create.status_code == 201, f"{create.status_code} {create.text}"
    _assert_no_sensitive_fields(create.json(), "POST /admin/users")

    listing = admin.get("/admin/users")
    assert listing.status_code == 200, f"{listing.status_code} {listing.text}"
    page = listing.json()
    assert "items" in page and isinstance(page["items"], list), (
        f"GET /admin/users 는 Page[UserRead] 형태(items 리스트)여야 한다: {page!r}"
    )
    assert page["items"], "시드 admin + 방금 생성한 사용자가 목록에 있어야 한다"
    for item in page["items"]:
        _assert_no_sensitive_fields(item, "GET /admin/users item")
