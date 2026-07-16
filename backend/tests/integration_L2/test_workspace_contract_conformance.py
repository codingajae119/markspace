"""워크스페이스 계약 대조 스위트 (Task 2.1 / Req 2.1, 2.2, 2.3, 2.4, 2.5, 2.6).

실제 결합된 런타임(마이그레이션 적용 DB + 부팅 앱(s01⊕s02⊕s03⊕s05) + 실 세션)을
**s01-contract-foundation 단일 소스**와 대조하는 외부 관찰자 스위트다. 대조 기준은 s05 의
design 이 아니라 항상 s01(`design.md` §Physical Data Model · §API Endpoint Catalog · §Errors ·
§Base Schemas)이며, 실제 앱이 s01 계약에서 벗어났다면 단언을 약화시키지 않고 그대로
실패시켜 드리프트를 표면화한다(design.md §계약 대조 판정 · §Error Categories "계약 드리프트").

이 스위트는 L1 `test_contract_conformance.py`(user 테이블 템플릿)를 워크스페이스·멤버십
표면으로 그대로 확장한다. 네 개의 단언 그룹:

- **Group 1 — workspace·workspace_member 스키마 vs s01 물리 모델(Req 2.1, 2.2)**:
  마이그레이션된 DB 의 `information_schema` 를 조회해 컬럼 집합·nullability·타입 계열, role
  ENUM(owner/editor/viewer), UNIQUE(workspace_id, user_id), INDEX(user_id), FK(workspace_id→
  workspace.id · user_id→user.id) 를 s01 물리 모델과 대조한다.
- **Group 2 — 엔드포인트 카탈로그 9~17 노출(Req 2.3, 2.4)**: 부팅 앱의 OpenAPI 가 s01 카탈로그
  행 10~17(워크스페이스·멤버십)과 행 9(admin 소유권 변경)을 정확한 경로·메서드로 노출하고,
  요구 role 게이트(미인증 401·비멤버 403·비-admin 403)가 런타임에서 실제로 강제됨을 확인.
- **Group 3 — 에러 모델 vs s01 에러 카탈로그(Req 2.5)**: 401/403/404/409/422 를 실제로 유발해
  상태코드와 `ErrorResponse` 형태(`{code, message, field_errors?}`)·`code` 문자열을 대조.
- **Group 4 — Base Schemas 규약·마이그레이션 무추가(Req 2.6)**: `WorkspaceRead` 가
  `TimestampedRead`(id·created_at·updated_at)를 상속하고 목록이 `Page[WorkspaceRead]` 규약을
  따르며, s05 가 새 마이그레이션 없이 s01 단일 리비전만 쓰는지 확인.

하네스(:func:`~tests.integration_L1.conftest.harness`, L2 conftest 경유)와 `ws_scenario`
픽스처가 제공하는 실 결합 환경 위에서만 동작하며 mock 을 쓰지 않는다.
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from tests.integration_L1 import helpers

# s01 §Physical Data Model — workspace 테이블 계약(단일 소스).
# 컬럼명 → nullability("NO" = NOT NULL, "YES" = NULLable).
S01_WORKSPACE_COLUMNS_NULLABILITY = {
    "id": "NO",
    "name": "NO",
    "is_shareable": "NO",
    "trash_retention_days": "NO",
    "created_at": "NO",
    "updated_at": "YES",
}

# 타입 계열(브리틀한 정확 문자열 대신 MySQL 타입 계열로 경량 검증).
# BIGINT → bigint, 문자열 → varchar, BOOLEAN → tinyint, INTEGER → int, 타임스탬프 → datetime.
S01_WORKSPACE_TYPE_FAMILY = {
    "id": "bigint",
    "name": "varchar",
    "is_shareable": "tinyint",
    "trash_retention_days": "int",
    "created_at": "datetime",
    "updated_at": "datetime",
}

# s01 §Physical Data Model — workspace_member 테이블 계약(타임스탬프 없음).
S01_WORKSPACE_MEMBER_COLUMNS_NULLABILITY = {
    "id": "NO",
    "workspace_id": "NO",
    "user_id": "NO",
    "role": "NO",
}

S01_WORKSPACE_MEMBER_TYPE_FAMILY = {
    "id": "bigint",
    "workspace_id": "bigint",
    "user_id": "bigint",
    "role": "enum",
}

# s01 workspace_member.role ENUM 의 정확한 값 집합.
S01_MEMBER_ROLE_ENUM_VALUES = {"owner", "editor", "viewer"}

# s01 §API Endpoint Catalog rows 9~17 — (경로, 메서드) 계약.
# 실제 라우트가 쓰는 경로 파라미터 명명은 `{id}` / `{uid}` (s01 카탈로그 반영).
S01_ENDPOINT_CATALOG_9_TO_17 = [
    ("/admin/workspaces/{id}/owner", "post"),      # row 9  — admin 소유권 변경 (admin)
    ("/workspaces", "post"),                        # row 10 — 생성 (auth)
    ("/workspaces", "get"),                         # row 11 — 목록 (auth)
    ("/workspaces/{id}", "get"),                    # row 12 — 상세 (VIEWER)
    ("/workspaces/{id}", "patch"),                  # row 13 — 수정 (OWNER)
    ("/workspaces/{id}", "delete"),                 # row 14 — 삭제 (OWNER)
    ("/workspaces/{id}/members", "post"),           # row 15 — 멤버 추가 (OWNER)
    ("/workspaces/{id}/members/{uid}", "patch"),    # row 16 — role 변경 (OWNER)
    ("/workspaces/{id}/members/{uid}", "delete"),   # row 17 — 멤버 제거 (OWNER)
]


def _assert_error_response_shape(body: object) -> None:
    """관측된 에러 본문이 s01 ``ErrorResponse`` 형태를 따르는지 강제한다(Req 2.5).

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


def _index_columns_by_name(rows) -> dict[str, list[tuple[int, str]]]:
    """`information_schema.statistics` 행들을 인덱스명 → [(seq_in_index, column)] 로 묶는다.

    각 인덱스가 어떤 컬럼을 어떤 순서로 덮는지 이름이 아니라 **구조**로 판정하기 위한
    보조 함수. 반환 리스트는 seq_in_index 오름차순으로 정렬된다.
    """
    grouped: dict[str, list[tuple[int, str]]] = {}
    for index_name, non_unique, seq_in_index, column_name in rows:
        grouped.setdefault(index_name, []).append((int(seq_in_index), column_name))
    for name in grouped:
        grouped[name].sort()
    return grouped


# --- Group 1 — workspace·workspace_member 스키마 vs s01 물리 모델 (Req 2.1, 2.2) ------


def test_workspace_table_columns_match_s01_physical_model(harness):
    """마이그레이션된 workspace 테이블의 컬럼 집합·nullability·타입 계열이 s01 물리 모델과 일치.

    `information_schema.columns` 를 조회해 (1) 컬럼 집합이 s01 계약과 정확히 같고(누락·초과
    없음), (2) 각 컬럼 nullability, (3) 문자열/불리언/정수/타임스탬프 타입 계열이 s01 과
    일치함을 대조한다. 드리프트 시 어떤 컬럼이 어긋났는지 메시지에 명시한다.
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT column_name, is_nullable, data_type "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'workspace'"
            )
        ).all()

    assert rows, "마이그레이션된 DB 에 workspace 테이블 컬럼이 존재해야 한다(스키마 미적용?)"

    observed = {row[0]: (row[1].upper(), row[2].lower()) for row in rows}

    expected_cols = set(S01_WORKSPACE_COLUMNS_NULLABILITY)
    observed_cols = set(observed)
    missing = expected_cols - observed_cols
    extra = observed_cols - expected_cols
    assert not missing, f"workspace 테이블에 s01 계약 컬럼 누락: {sorted(missing)}"
    assert not extra, f"workspace 테이블에 s01 계약 밖 컬럼 초과: {sorted(extra)}"

    for col, expected_nullable in S01_WORKSPACE_COLUMNS_NULLABILITY.items():
        observed_nullable = observed[col][0]
        assert observed_nullable == expected_nullable, (
            f"workspace.{col} nullability 드리프트: s01={expected_nullable} "
            f"관측={observed_nullable}"
        )

    for col, expected_family in S01_WORKSPACE_TYPE_FAMILY.items():
        observed_family = observed[col][1]
        assert observed_family == expected_family, (
            f"workspace.{col} 타입 계열 드리프트: s01={expected_family} "
            f"관측={observed_family}"
        )


def test_workspace_member_table_columns_match_s01_physical_model(harness):
    """마이그레이션된 workspace_member 테이블의 컬럼 집합·nullability·타입 계열이 s01 과 일치.

    s01 물리 모델상 workspace_member 는 id·workspace_id·user_id·role 만 가지며 타임스탬프가
    **없다**. 컬럼 집합이 정확히 이 넷이고(누락·초과 없음), 각 nullability·타입 계열이
    s01 과 일치함을 대조한다. created_at/updated_at 이 관측되면 초과 컬럼으로 실패한다.
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT column_name, is_nullable, data_type "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'workspace_member'"
            )
        ).all()

    assert rows, (
        "마이그레이션된 DB 에 workspace_member 테이블 컬럼이 존재해야 한다(스키마 미적용?)"
    )

    observed = {row[0]: (row[1].upper(), row[2].lower()) for row in rows}

    expected_cols = set(S01_WORKSPACE_MEMBER_COLUMNS_NULLABILITY)
    observed_cols = set(observed)
    missing = expected_cols - observed_cols
    extra = observed_cols - expected_cols
    assert not missing, f"workspace_member 테이블에 s01 계약 컬럼 누락: {sorted(missing)}"
    assert not extra, (
        f"workspace_member 테이블에 s01 계약 밖 컬럼 초과(타임스탬프 없어야 함): "
        f"{sorted(extra)}"
    )

    for col, expected_nullable in S01_WORKSPACE_MEMBER_COLUMNS_NULLABILITY.items():
        observed_nullable = observed[col][0]
        assert observed_nullable == expected_nullable, (
            f"workspace_member.{col} nullability 드리프트: s01={expected_nullable} "
            f"관측={observed_nullable}"
        )

    for col, expected_family in S01_WORKSPACE_MEMBER_TYPE_FAMILY.items():
        observed_family = observed[col][1]
        assert observed_family == expected_family, (
            f"workspace_member.{col} 타입 계열 드리프트: s01={expected_family} "
            f"관측={observed_family}"
        )


def test_workspace_member_role_enum_values_match_s01(harness):
    """workspace_member.role 이 정확히 ENUM('owner','editor','viewer')임을 확인(s01).

    `information_schema.columns.column_type`(예: ``enum('owner','editor','viewer')``)을
    조회해 열거된 값 집합이 s01 계약과 정확히 일치함을 대조한다(이름이 아니라 값 집합으로).
    """
    with harness.session_local() as db:
        row = db.execute(
            text(
                "SELECT column_type FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'workspace_member' "
                "AND column_name = 'role'"
            )
        ).first()

    assert row is not None, "workspace_member.role 컬럼이 존재해야 한다"
    column_type = row[0].lower()
    assert column_type.startswith("enum("), (
        f"workspace_member.role 은 ENUM 타입이어야 한다: 관측 column_type={column_type!r}"
    )
    # enum('owner','editor','viewer') → 따옴표 안 값만 추출.
    observed_values = {piece.strip().strip("'") for piece in
                       column_type[len("enum("):-1].split(",")}
    assert observed_values == S01_MEMBER_ROLE_ENUM_VALUES, (
        f"workspace_member.role ENUM 값 드리프트: s01={sorted(S01_MEMBER_ROLE_ENUM_VALUES)} "
        f"관측={sorted(observed_values)}"
    )


def test_workspace_member_unique_over_workspace_id_user_id(harness):
    """workspace_member 에 (workspace_id, user_id) UNIQUE 제약이 존재함을 확인(s01).

    `information_schema.statistics` 에서 non_unique=0 인 인덱스 중 정확히 (workspace_id,
    user_id) 두 컬럼만 순서대로 덮는 것이 있음을 **구조로** 단언한다(제약명 관례는
    `uq_workspace_member_ws_user` 이나 이름에 의존하지 않는다).
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT index_name, non_unique, seq_in_index, column_name "
                "FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = 'workspace_member'"
            )
        ).all()

    assert rows, "workspace_member 에 인덱스가 존재해야 한다"
    grouped = _index_columns_by_name(rows)

    # non_unique 는 인덱스 단위 속성 — 인덱스명별로 판별한다.
    unique_index_names = {
        row[0] for row in rows if int(row[1]) == 0
    }
    matching = [
        name
        for name in unique_index_names
        if [col for _, col in grouped[name]] == ["workspace_id", "user_id"]
    ]
    observed_layout = {name: [col for _, col in cols] for name, cols in grouped.items()}
    assert matching, (
        "workspace_member 에 (workspace_id, user_id) 순서를 정확히 덮는 UNIQUE 인덱스가 "
        f"없다: 관측 인덱스 레이아웃={observed_layout}, UNIQUE 인덱스={sorted(unique_index_names)}"
    )


def test_workspace_member_index_on_user_id(harness):
    """workspace_member.user_id 를 선두 컬럼으로 하는 인덱스가 존재함을 확인(s01 INDEX(user_id)).

    `information_schema.statistics` 에서 첫 컬럼(seq_in_index=1)이 user_id 인 인덱스가
    하나라도 있음을 단언한다(인덱스명 `ix_workspace_member_user_id` 에 의존하지 않는다).
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT index_name, non_unique, seq_in_index, column_name "
                "FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = 'workspace_member'"
            )
        ).all()

    assert rows, "workspace_member 에 인덱스가 존재해야 한다"
    grouped = _index_columns_by_name(rows)

    leading_user_id = [
        name for name, cols in grouped.items() if cols and cols[0][1] == "user_id"
    ]
    leading_columns = {name: cols[0][1] for name, cols in grouped.items() if cols}
    assert leading_user_id, (
        "workspace_member.user_id 를 선두로 하는 인덱스가 없다(s01 INDEX(user_id) 계약): "
        f"관측 인덱스 선두 컬럼={leading_columns}"
    )


def test_workspace_member_foreign_keys_reference_workspace_and_user(harness):
    """workspace_member 의 FK 가 workspace(id)·user(id) 를 참조함을 확인(s01).

    `information_schema.key_column_usage` 에서 참조 테이블이 있는(FK) 행을 조회해
    (workspace_id → workspace.id) 와 (user_id → user.id) 두 참조가 모두 존재함을
    컬럼·참조테이블·참조컬럼 기준으로 단언한다(제약명 비의존).
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT column_name, referenced_table_name, referenced_column_name "
                "FROM information_schema.key_column_usage "
                "WHERE table_schema = DATABASE() AND table_name = 'workspace_member' "
                "AND referenced_table_name IS NOT NULL"
            )
        ).all()

    observed_fks = {
        (row[0], row[1], row[2]) for row in rows
    }
    assert ("workspace_id", "workspace", "id") in observed_fks, (
        f"workspace_member.workspace_id → workspace.id FK 가 없다: 관측={sorted(observed_fks)}"
    )
    assert ("user_id", "user", "id") in observed_fks, (
        f"workspace_member.user_id → user.id FK 가 없다: 관측={sorted(observed_fks)}"
    )


# --- Group 2 — API 엔드포인트 카탈로그 9~17 노출 (Req 2.3, 2.4) ----------------------


def test_openapi_exposes_workspace_catalog_rows_9_to_17(harness):
    """부팅 앱의 OpenAPI 가 s01 카탈로그 행 9~17 을 정확한 경로·메서드로 노출.

    각 (경로, 메서드) 쌍이 `app.openapi()["paths"]` 에 존재함을 확인한다(경로 파라미터는
    s01 이 정한 `{id}`/`{uid}` 명명). 이는 워크스페이스·멤버십·admin 소유권 변경 API 표면이
    s01 카탈로그와 정합함을 보증한다.
    """
    paths = harness.app.openapi()["paths"]

    for path, method in S01_ENDPOINT_CATALOG_9_TO_17:
        assert path in paths, (
            f"카탈로그 경로 {path!r} 가 앱 OpenAPI 에 노출되어야 한다: "
            f"관측 경로={sorted(paths)}"
        )
        methods = {m.lower() for m in paths[path]}
        assert method in methods, (
            f"카탈로그 {method.upper()} {path} 가 노출되어야 한다: "
            f"관측 메서드={sorted(methods)}"
        )


def test_workspace_detail_without_session_returns_401(harness):
    """워크스페이스 상세를 세션 없이 호출하면 401(인증 게이트 런타임 강제, Req 2.3)."""
    resp = harness.new_client().get("/workspaces/999999999")
    assert resp.status_code == 401, (
        f"미인증 GET /workspaces/{{id}} 는 401 이어야 한다: {resp.status_code} {resp.text}"
    )


def test_nonmember_workspace_detail_returns_403(ws_scenario):
    """비멤버가 워크스페이스 상세를 호출하면 403(role 게이트 실제 강제, Req 2.3, INV-1).

    resolver 가 멤버십이 없는 요청자의 role 을 None 으로 판정해 서비스 실행 전에 거부한다.
    """
    resp = ws_scenario.nonmember_client.get(
        f"/workspaces/{ws_scenario.workspace_id}"
    )
    assert resp.status_code == 403, (
        f"비멤버 GET /workspaces/{{id}} 는 403 이어야 한다: {resp.status_code} {resp.text}"
    )


def test_nonadmin_owner_change_returns_403(ws_scenario):
    """비-admin 이 소유권 변경을 호출하면 403(admin 게이트 실제 강제, Req 2.4)."""
    resp = ws_scenario.nonmember_client.post(
        f"/admin/workspaces/{ws_scenario.workspace_id}/owner",
        json={"new_owner_user_id": ws_scenario.nonmember_user_id},
    )
    assert resp.status_code == 403, (
        f"비-admin POST /admin/workspaces/{{id}}/owner 는 403 이어야 한다: "
        f"{resp.status_code} {resp.text}"
    )


# --- Group 3 — 에러 모델 vs s01 에러 카탈로그 (Req 2.5) -----------------------------


def test_error_401_unauthenticated(harness):
    """미인증 보호 요청 → 401 + code=unauthenticated + ErrorResponse 형태."""
    resp = harness.new_client().get("/workspaces/999999999")
    assert resp.status_code == 401, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "unauthenticated", (
        f"401 은 s01 카탈로그상 code=unauthenticated 여야 한다: {body!r}"
    )


def test_error_403_forbidden(ws_scenario):
    """비멤버의 워크스페이스 상세 요청 → 403 + code=forbidden + ErrorResponse 형태."""
    resp = ws_scenario.nonmember_client.get(
        f"/workspaces/{ws_scenario.workspace_id}"
    )
    assert resp.status_code == 403, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "forbidden", (
        f"403 은 s01 카탈로그상 code=forbidden 여야 한다: {body!r}"
    )


def test_error_404_not_found(ws_scenario):
    """admin(게이트 bypass) PATCH /workspaces/{존재하지 않는 id} → 404 + code=not_found.

    비멤버는 resolver 가 role None 을 반환해 403(404 아님)으로 막힌다. 404 를 관측하려면
    게이트를 **통과하는** 클라이언트가 필요하므로 admin bypass 를 쓴다: admin 은 owner
    게이트를 통과하고 서비스가 미존재 워크스페이스에 대해 not_found 를 올린다.
    """
    resp = ws_scenario.admin_client.patch(
        "/workspaces/999999999", json={"name": "없는 워크스페이스"}
    )
    assert resp.status_code == 404, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "not_found", (
        f"404 는 s01 카탈로그상 code=not_found 여야 한다: {body!r}"
    )


def test_error_409_conflict(ws_scenario):
    """owner 가 이미 멤버인 사용자를 다시 추가 → 409 + code=conflict.

    `ws_scenario` 에서 editor 는 이미 멤버다. owner 가 같은 user_id 를 다시 추가하면
    UNIQUE(workspace_id, user_id) 계약상 중복 멤버 충돌이 발생한다.
    """
    resp = ws_scenario.owner_client.post(
        f"/workspaces/{ws_scenario.workspace_id}/members",
        json={"user_id": ws_scenario.editor_user_id, "role": "viewer"},
    )
    assert resp.status_code == 409, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "conflict", (
        f"409 는 s01 카탈로그상 code=conflict 여야 한다: {body!r}"
    )


def test_error_422_validation_error_has_field_errors(ws_scenario):
    """owner 가 trash_retention_days=0 으로 설정 → 422 + code=validation_error + field_errors.

    보관일은 양의 정수(>0)여야 하므로 0 은 검증 실패다. s01 전역 핸들러를 통해 422
    `validation_error` 와 비어있지 않은 `field_errors` 로 응답함을 대조한다.
    """
    resp = ws_scenario.owner_client.patch(
        f"/workspaces/{ws_scenario.workspace_id}",
        json={"trash_retention_days": 0},
    )
    assert resp.status_code == 422, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "validation_error", (
        f"422 검증 위반은 s01 카탈로그상 code=validation_error 여야 한다: {body!r}"
    )
    assert isinstance(body.get("field_errors"), list) and len(body["field_errors"]) > 0, (
        f"검증 오류는 비어있지 않은 field_errors 를 포함해야 한다: {body!r}"
    )


# --- Group 4 — Base Schemas 규약·마이그레이션 무추가 (Req 2.6) ----------------------


def test_workspace_create_body_follows_timestamped_read(harness):
    """POST /workspaces(201) 본문이 WorkspaceRead ⊃ TimestampedRead 규약을 따름.

    본문에 s01 `TimestampedRead` 공통 필드(id·created_at·updated_at)와 워크스페이스 고유
    필드(name·is_shareable·trash_retention_days)가 모두 존재함을 확인한다. 이는
    `WorkspaceRead` 가 s01 공통 Read 베이스를 재정의 없이 상속함을 관찰로 보증한다.
    """
    admin = harness.login_admin()
    login_id = helpers.unique_login_id("wsowner")
    helpers.create_user(admin, login_id, helpers.DEFAULT_PASSWORD, name="베이스규약 오너")
    owner = harness.login(login_id, helpers.DEFAULT_PASSWORD)

    resp = owner.post("/workspaces", json={"name": "베이스 규약 워크스페이스"})
    assert resp.status_code == 201, f"{resp.status_code} {resp.text}"
    body = resp.json()
    assert isinstance(body, dict), f"WorkspaceRead 본문은 객체여야 한다: {body!r}"

    for field in ("id", "created_at", "updated_at"):
        assert field in body, (
            f"WorkspaceRead 는 TimestampedRead 필드 {field!r} 를 포함해야 한다: "
            f"keys={sorted(body.keys())}"
        )
    for field in ("name", "is_shareable", "trash_retention_days"):
        assert field in body, (
            f"WorkspaceRead 는 워크스페이스 고유 필드 {field!r} 를 포함해야 한다: "
            f"keys={sorted(body.keys())}"
        )


def test_workspace_list_is_page_shape(ws_scenario):
    """GET /workspaces(200) 본문이 Page[WorkspaceRead] 규약(items 리스트 + total int)을 따름."""
    resp = ws_scenario.owner_client.get("/workspaces")
    assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
    page = resp.json()
    assert isinstance(page, dict), f"목록 본문은 Page 엔벨로프 객체여야 한다: {page!r}"
    assert "items" in page and isinstance(page["items"], list), (
        f"GET /workspaces 는 items 리스트를 가진 Page 형태여야 한다: {page!r}"
    )
    assert "total" in page and isinstance(page["total"], int), (
        f"GET /workspaces 는 total 정수를 가진 Page 형태여야 한다: {page!r}"
    )
    # owner 는 자신이 만든 워크스페이스가 목록에 있어야 한다(각 item 도 WorkspaceRead 형태).
    assert page["items"], "owner 가 만든 워크스페이스가 목록에 있어야 한다"
    for item in page["items"]:
        for field in ("id", "created_at", "name", "is_shareable", "trash_retention_days"):
            assert field in item, (
                f"목록 item 은 WorkspaceRead 필드 {field!r} 를 포함해야 한다: "
                f"keys={sorted(item.keys())}"
            )


def test_no_additional_s05_migration():
    """s05 가 새 마이그레이션을 추가하지 않고 s01 단일 리비전(0001)만 사용함을 확인(Req 2.6).

    (1) `migrations/versions/` 에 리비전 파일이 정확히 하나(`0001_initial_schema.py`)이고,
    (2) alembic head 가 단일 `0001` 리비전이며 그 down_revision 이 None(base)임을 확인한다.
    이 리비전이 workspace/workspace_member 테이블의 유일한 출처다.
    """
    backend_dir = Path(__file__).resolve().parents[2]  # integration_L2 -> tests -> backend
    versions_dir = backend_dir / "migrations" / "versions"

    revision_files = sorted(
        p.name for p in versions_dir.glob("*.py") if p.name != "__init__.py"
    )
    assert revision_files == ["0001_initial_schema.py"], (
        "s05 는 새 마이그레이션을 추가하지 않고 s01 단일 리비전만 사용해야 한다: "
        f"관측 리비전 파일={revision_files}"
    )

    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))
    script = ScriptDirectory.from_config(cfg)

    heads = list(script.get_heads())
    assert heads == ["0001"], f"alembic head 는 단일 0001 리비전이어야 한다: {heads}"

    rev = script.get_revision("0001")
    assert rev.down_revision is None, (
        f"0001 은 base 리비전이어야 한다(down_revision None): {rev.down_revision!r}"
    )
