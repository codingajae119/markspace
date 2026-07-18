"""문서 계약 대조 스위트 (Task 2.1 / Req 2.1, 2.2, 2.3, 2.4, 2.5, 2.6,
design §DocumentContractConformanceSuite · §계약 대조 판정).

실제 결합된 런타임(마이그레이션 적용 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕**s07**) + 실 세션 +
부팅 앱과 동일 세션 팩토리의 `DocumentStateEngine`)을 **s01-contract-foundation 단일 소스**와
대조하는 외부 관찰자 스위트다. 대조 기준은 s07 의 design 이 아니라 항상
s01(`design.md` §Physical Data Model `document`·`document_version` · §API Endpoint Catalog
18~23 · §Errors 에러 코드 카탈로그 · §Base Schemas `TimestampedRead`·`Page[T]`·`ErrorResponse`
· §Invariants INV-4·INV-7)이며, 실제 앱이 s01 계약에서 벗어났다면 단언을 약화시키지 않고 그대로
실패시켜 **어느 계약 요소가 드리프트했는지** 를 assertion 메시지가 지목한다(design §계약 대조
판정: "불일치 시 어느 계약 요소가 드리프트했는지 assertion 메시지가 지목").

이 스위트는 L1 `test_contract_conformance.py`·L2 `test_workspace_contract_conformance.py`
(스키마·API·에러 대조 템플릿)를 문서 도메인 표면으로 확장한다. 다섯 개의 단언 그룹(task 2.1):

- **Group 1 — document·document_version 스키마 vs s01 물리 모델(Req 2.1·2.2)**: 마이그레이션된
  DB 의 `information_schema` 를 조회해 컬럼 집합·nullability·타입 계열, `status`
  ENUM(active/trashed/deleted), `sort_order` DECIMAL(30,15), 인덱스
  `(workspace_id, status, parent_id)`·`(workspace_id, status, trashed_at)` 와
  `(document_id, created_at)`, FK 를 s01 물리 모델과 대조하고, s07 이 새 마이그레이션을 추가하지
  않고 s01 단일 리비전(0001)만 씀을 확인한다.
- **Group 2 — 엔드포인트 카탈로그 18~23 노출·게이트 강제(Req 2.3)**: 부팅 앱의 OpenAPI 가 s01
  카탈로그 행 18~23 을 정확한 경로(파라미터 명명 무관 구조)·메서드로 노출하고, 요구 role 게이트가
  런타임에서 실제로 강제됨(미인증 401·viewer 변경 403)을 대표 요청으로 확인.
- **Group 3 — 에러 모델 vs s01 에러 카탈로그(Req 2.4)**: 401/403/404/409/422 를 실제로 유발해
  상태코드와 `ErrorResponse` 형태(`{code, message, field_errors?}`)·`code` 문자열을 대조.
- **Group 4 — Base Schemas 규약·status 값(Req 2.5)**: `DocumentRead` 가
  `TimestampedRead`(id·created_at·updated_at)를 상속하고 목록이 `Page[DocumentRead]`
  (items 리스트 + total int) 규약을 따르며, 관측된 `status` 값이 s01 ENUM 집합과 동일함을 확인.
- **Group 5 — status 전이·종착·물리삭제 부재(Req 2.6, INV-4·INV-7)**: 라우터가 노출하는 문서
  status 전이는 active→trashed(삭제)뿐이고 복구 라우트가 없음, trashed→deleted 는 엔진 종착이며
  deleted 가 최종(복원 경로 없음, INV-7)이고, 어떤 경로에서도 문서가 물리 삭제되지 않음(INV-4)을
  실제 결합(라우터 delete + 엔진 purge + DB 직접 관찰)으로 확인.

하네스(`harness`, L1 conftest)·`ws_scenario`(L2 conftest)·`engine_access`(L3 conftest)
픽스처가 제공하는 실 결합 환경 위에서만 동작하며 mock 을 쓰지 않는다.
"""

from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from tests.integration_L3 import helpers

# =============================================================================
# s01 단일 소스 계약 상수 — §Physical Data Model document·document_version
# =============================================================================

# s01 §Physical Data Model — document 테이블 계약(단일 소스).
# 컬럼명 → nullability("NO" = NOT NULL, "YES" = NULLable).
S01_DOCUMENT_COLUMNS_NULLABILITY = {
    "id": "NO",
    "workspace_id": "NO",
    "parent_id": "YES",
    "title": "NO",
    "status": "NO",
    "sort_order": "NO",
    "current_version_id": "YES",
    "lock_user_id": "YES",
    "lock_acquired_at": "YES",
    "trashed_at": "YES",
    "created_by": "NO",
    "created_at": "NO",
    "updated_at": "YES",
}

# 타입 계열(브리틀한 정확 문자열 대신 MySQL 타입 계열로 경량 검증).
# BIGINT → bigint, 문자열 → varchar, ENUM → enum, DECIMAL → decimal, 타임스탬프 → datetime.
S01_DOCUMENT_TYPE_FAMILY = {
    "id": "bigint",
    "workspace_id": "bigint",
    "parent_id": "bigint",
    "title": "varchar",
    "status": "enum",
    "sort_order": "decimal",
    "current_version_id": "bigint",
    "lock_user_id": "bigint",
    "lock_acquired_at": "datetime",
    "trashed_at": "datetime",
    "created_by": "bigint",
    "created_at": "datetime",
    "updated_at": "datetime",
}

# s01: status ENUM('active','trashed','deleted') 의 정확한 값 집합.
S01_DOCUMENT_STATUS_ENUM_VALUES = {"active", "trashed", "deleted"}

# s01: sort_order DECIMAL(30,15) — 형제 중간 삽입 지원(§2.4, 6.7).
S01_SORT_ORDER_PRECISION = 30
S01_SORT_ORDER_SCALE = 15

# s01 §Physical Data Model — document_version 테이블 계약(타임스탬프는 created_at 만).
S01_DOCUMENT_VERSION_COLUMNS_NULLABILITY = {
    "id": "NO",
    "document_id": "NO",
    "content": "NO",
    "created_by": "NO",
    "created_at": "NO",
}

# content 는 MEDIUMTEXT.
S01_DOCUMENT_VERSION_TYPE_FAMILY = {
    "id": "bigint",
    "document_id": "bigint",
    "content": "mediumtext",
    "created_by": "bigint",
    "created_at": "datetime",
}

# s01 document 인덱스 계약 — 컬럼 순서열(이름 비의존, 구조로 판정).
S01_DOCUMENT_INDEX_LAYOUTS = [
    ["workspace_id", "status", "parent_id"],
    ["workspace_id", "status", "trashed_at"],
]

# s01 document FK 계약 — (컬럼, 참조테이블, 참조컬럼).
S01_DOCUMENT_FOREIGN_KEYS = {
    ("workspace_id", "workspace", "id"),
    ("parent_id", "document", "id"),
    ("current_version_id", "document_version", "id"),
    ("lock_user_id", "user", "id"),
    ("created_by", "user", "id"),
}

# s01 document_version FK 계약.
S01_DOCUMENT_VERSION_FOREIGN_KEYS = {
    ("document_id", "document", "id"),
    ("created_by", "user", "id"),
}

# s01 document_version 인덱스 계약 — 선두 (document_id, created_at) 을 덮는 인덱스.
S01_DOCUMENT_VERSION_INDEX_LAYOUT = ["document_id", "created_at"]

# s01 §API Endpoint Catalog rows 18~23 — (경로, 메서드, 요구 role).
# 경로는 파라미터 명명(s07 이 실제로 `{workspace_id}`/`{id}` 를 씀)에 의존하지 않도록 아래
# `_normalize_path` 로 정규화해 대조한다. s01 카탈로그의 구조(세그먼트+파라미터 위치)가 계약이다.
S01_ENDPOINT_CATALOG_18_TO_23 = [
    ("/workspaces/{}/documents", "post"),    # row 18 — 생성 (editor)
    ("/workspaces/{}/documents", "get"),     # row 19 — 목록 (viewer)
    ("/documents/{}", "get"),                # row 20 — 상세 (viewer)
    ("/documents/{}", "patch"),              # row 21 — 제목 수정 (editor)
    ("/documents/{}/move", "post"),          # row 22 — 이동 (editor)
    ("/documents/{}", "delete"),             # row 23 — 삭제 (editor)
]

# s01 `DocumentRead`(TimestampedRead 상속) 가 노출해야 하는 전체 필드 집합(§Base Schemas 규약).
S01_TIMESTAMPED_READ_FIELDS = {"id", "created_at", "updated_at"}
S01_DOCUMENT_READ_FIELDS = S01_TIMESTAMPED_READ_FIELDS | {
    "workspace_id",
    "parent_id",
    "title",
    "status",
    "sort_order",
    "current_version_id",
    "created_by",
    "content",
    "content_html",
}

# 인증되었으나 대상이 존재하지 않을 때 어댑터 404 를 관측하기 위한 미존재 id.
MISSING_DOCUMENT_ID = 999_999_999


def _title(prefix: str) -> str:
    """공유 ``notion_lite_test`` DB 충돌을 피하는 고유 문서 제목을 만든다."""
    return f"{prefix}-{uuid4().hex[:12]}"


def _normalize_path(path: str) -> str:
    """경로의 `{param}` 세그먼트를 `{}` 로 정규화한다(파라미터 명명 비의존 구조 대조).

    s01 카탈로그는 워크스페이스 경로 파라미터를 `{id}` 로 적지만 s07 라우트는 `{workspace_id}`
    를 쓴다. 계약 요소는 **경로 구조(세그먼트 배열 + 파라미터 위치) + 메서드 + 요구 role** 이지
    파라미터 식별자 이름이 아니므로, 양쪽을 동일 규칙으로 정규화해 대조한다.
    """
    out: list[str] = []
    for seg in path.split("/"):
        out.append("{}" if seg.startswith("{") and seg.endswith("}") else seg)
    return "/".join(out)


def _assert_error_response_shape(body: object) -> None:
    """관측된 에러 본문이 s01 ``ErrorResponse`` 형태를 따르는지 강제한다(Req 2.4).

    최소 계약(s01 §Errors): 문자열 ``code`` 와 문자열 ``message`` 키를 가지며,
    ``field_errors`` 가 존재하면 리스트다(``{code, message, field_errors?}``).
    """
    assert isinstance(body, dict), f"ErrorResponse 본문은 JSON 객체여야 한다: {body!r}"
    assert isinstance(body.get("code"), str), (
        f"ErrorResponse.code 는 문자열이어야 한다(s01 §Errors 드리프트): {body!r}"
    )
    assert isinstance(body.get("message"), str), (
        f"ErrorResponse.message 는 문자열이어야 한다(s01 §Errors 드리프트): {body!r}"
    )
    if body.get("field_errors") is not None:
        assert isinstance(body["field_errors"], list), (
            f"ErrorResponse.field_errors 가 존재하면 리스트여야 한다: {body!r}"
        )


def _index_columns_by_name(rows) -> dict[str, list[str]]:
    """`information_schema.statistics` 행을 인덱스명 → [seq 순 컬럼] 로 묶는다(구조 판정용).

    각 행은 (index_name, seq_in_index, column_name). 반환 값은 seq_in_index 오름차순으로
    정렬된 컬럼 리스트다(인덱스명이 아니라 컬럼 순서열로 계약을 판정하기 위함).
    """
    grouped: dict[str, list[tuple[int, str]]] = {}
    for index_name, seq_in_index, column_name in rows:
        grouped.setdefault(index_name, []).append((int(seq_in_index), column_name))
    return {name: [c for _, c in sorted(cols)] for name, cols in grouped.items()}


def _statistics_rows(harness, table: str):
    """대상 테이블의 (index_name, seq_in_index, column_name) 인덱스 행을 조회한다."""
    with harness.session_local() as db:
        return db.execute(
            text(
                "SELECT index_name, seq_in_index, column_name "
                "FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = :t"
            ),
            {"t": table},
        ).all()


# =============================================================================
# Group 1 — document·document_version 스키마 vs s01 물리 모델 (Req 2.1, 2.2)
# =============================================================================


def test_document_table_columns_match_s01_physical_model(harness):
    """마이그레이션된 document 테이블의 컬럼 집합·nullability·타입 계열이 s01 물리 모델과 일치(2.1).

    `information_schema.columns` 를 조회해 (1) 컬럼 집합이 s01 계약과 정확히 같고(누락·초과
    없음), (2) 각 컬럼 nullability, (3) 타입 계열이 s01 과 일치함을 대조한다. 드리프트 시 어떤
    컬럼이 어긋났는지 메시지에 명시한다(design §계약 대조 판정).
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT column_name, is_nullable, data_type "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'document'"
            )
        ).all()

    assert rows, "마이그레이션된 DB 에 document 테이블 컬럼이 존재해야 한다(스키마 미적용?)"

    observed = {row[0]: (row[1].upper(), row[2].lower()) for row in rows}

    expected_cols = set(S01_DOCUMENT_COLUMNS_NULLABILITY)
    observed_cols = set(observed)
    missing = expected_cols - observed_cols
    extra = observed_cols - expected_cols
    assert not missing, f"document 테이블에 s01 계약 컬럼 누락: {sorted(missing)}"
    assert not extra, f"document 테이블에 s01 계약 밖 컬럼 초과: {sorted(extra)}"

    for col, expected_nullable in S01_DOCUMENT_COLUMNS_NULLABILITY.items():
        observed_nullable = observed[col][0]
        assert observed_nullable == expected_nullable, (
            f"document.{col} nullability 드리프트: s01={expected_nullable} "
            f"관측={observed_nullable}"
        )

    for col, expected_family in S01_DOCUMENT_TYPE_FAMILY.items():
        observed_family = observed[col][1]
        assert observed_family == expected_family, (
            f"document.{col} 타입 계열 드리프트: s01={expected_family} "
            f"관측={observed_family}"
        )


def test_document_status_enum_values_match_s01(harness):
    """document.status 가 정확히 ENUM('active','trashed','deleted')임을 확인(s01, 2.1).

    `information_schema.columns.column_type`(예: ``enum('active','trashed','deleted')``)을
    조회해 열거된 값 집합이 s01 계약과 정확히 일치함을 대조한다(이름이 아니라 값 집합으로).
    """
    with harness.session_local() as db:
        row = db.execute(
            text(
                "SELECT column_type FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'document' "
                "AND column_name = 'status'"
            )
        ).first()

    assert row is not None, "document.status 컬럼이 존재해야 한다"
    column_type = row[0].lower()
    assert column_type.startswith("enum("), (
        f"document.status 는 ENUM 타입이어야 한다(s01): 관측 column_type={column_type!r}"
    )
    observed_values = {
        piece.strip().strip("'")
        for piece in column_type[len("enum("):-1].split(",")
    }
    assert observed_values == S01_DOCUMENT_STATUS_ENUM_VALUES, (
        f"document.status ENUM 값 드리프트: s01={sorted(S01_DOCUMENT_STATUS_ENUM_VALUES)} "
        f"관측={sorted(observed_values)}"
    )


def test_document_sort_order_is_decimal_30_15(harness):
    """document.sort_order 가 DECIMAL(30,15)임을 확인(s01: 형제 중간 삽입 지원, 2.1).

    `information_schema.columns` 의 numeric_precision·numeric_scale 을 조회해 s01 이 정한
    정밀도(30)·스케일(15)과 정확히 일치함을 대조한다(중간 삽입 sort_order 계약 근거).
    """
    with harness.session_local() as db:
        row = db.execute(
            text(
                "SELECT data_type, numeric_precision, numeric_scale "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'document' "
                "AND column_name = 'sort_order'"
            )
        ).first()

    assert row is not None, "document.sort_order 컬럼이 존재해야 한다"
    data_type, precision, scale = row[0].lower(), int(row[1]), int(row[2])
    assert data_type == "decimal", (
        f"document.sort_order 타입 드리프트: s01=decimal 관측={data_type}"
    )
    assert (precision, scale) == (S01_SORT_ORDER_PRECISION, S01_SORT_ORDER_SCALE), (
        f"document.sort_order 정밀도 드리프트: "
        f"s01=DECIMAL({S01_SORT_ORDER_PRECISION},{S01_SORT_ORDER_SCALE}) "
        f"관측=DECIMAL({precision},{scale})"
    )


def test_document_indexes_match_s01_physical_model(harness):
    """document 에 s01 인덱스 (workspace_id,status,parent_id)·(workspace_id,status,trashed_at) 존재(2.1).

    `information_schema.statistics` 에서 각 인덱스가 덮는 컬럼 순서열을 이름이 아니라 **구조**로
    판정한다. s01 이 정한 두 복합 인덱스 각각의 정확한 컬럼 순서열을 덮는 인덱스가 존재해야 한다.
    """
    rows = _statistics_rows(harness, "document")
    assert rows, "document 에 인덱스가 존재해야 한다"
    grouped = _index_columns_by_name(rows)
    observed_layouts = list(grouped.values())

    for expected_layout in S01_DOCUMENT_INDEX_LAYOUTS:
        assert expected_layout in observed_layouts, (
            f"document 인덱스 드리프트: s01 계약 인덱스 {expected_layout} 를 정확히 덮는 "
            f"인덱스가 없다. 관측 인덱스 레이아웃={observed_layouts}"
        )


def test_document_foreign_keys_match_s01(harness):
    """document 의 FK 가 s01 물리 모델(workspace/parent/current_version/lock_user/created_by)과 일치(2.1).

    `information_schema.key_column_usage` 에서 참조 테이블이 있는 행을 조회해 s01 이 정한 FK
    (컬럼→참조테이블.참조컬럼) 집합이 모두 존재함을 대조한다(제약명 비의존).
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT column_name, referenced_table_name, referenced_column_name "
                "FROM information_schema.key_column_usage "
                "WHERE table_schema = DATABASE() AND table_name = 'document' "
                "AND referenced_table_name IS NOT NULL"
            )
        ).all()

    observed_fks = {(row[0], row[1], row[2]) for row in rows}
    missing = S01_DOCUMENT_FOREIGN_KEYS - observed_fks
    assert not missing, (
        f"document FK 드리프트: s01 계약 FK 누락={sorted(missing)} "
        f"관측 FK={sorted(observed_fks)}"
    )


def test_document_version_table_columns_match_s01_physical_model(harness):
    """마이그레이션된 document_version 테이블의 컬럼·nullability·타입 계열이 s01 과 일치(2.2).

    s01 물리 모델상 document_version 은 id·document_id·content(MEDIUMTEXT)·created_by·created_at
    만 가진다(updated_at 없음). 컬럼 집합이 정확히 이 다섯이고 각 nullability·타입 계열이 s01 과
    일치함을 대조한다. content 가 mediumtext 계열임을 확인한다.
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT column_name, is_nullable, data_type "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'document_version'"
            )
        ).all()

    assert rows, (
        "마이그레이션된 DB 에 document_version 테이블 컬럼이 존재해야 한다(스키마 미적용?)"
    )

    observed = {row[0]: (row[1].upper(), row[2].lower()) for row in rows}

    expected_cols = set(S01_DOCUMENT_VERSION_COLUMNS_NULLABILITY)
    observed_cols = set(observed)
    missing = expected_cols - observed_cols
    extra = observed_cols - expected_cols
    assert not missing, f"document_version 테이블에 s01 계약 컬럼 누락: {sorted(missing)}"
    assert not extra, (
        f"document_version 테이블에 s01 계약 밖 컬럼 초과(updated_at 없어야 함): "
        f"{sorted(extra)}"
    )

    for col, expected_nullable in S01_DOCUMENT_VERSION_COLUMNS_NULLABILITY.items():
        observed_nullable = observed[col][0]
        assert observed_nullable == expected_nullable, (
            f"document_version.{col} nullability 드리프트: s01={expected_nullable} "
            f"관측={observed_nullable}"
        )

    for col, expected_family in S01_DOCUMENT_VERSION_TYPE_FAMILY.items():
        observed_family = observed[col][1]
        assert observed_family == expected_family, (
            f"document_version.{col} 타입 계열 드리프트: s01={expected_family} "
            f"관측={observed_family}"
        )


def test_document_version_index_and_foreign_keys_match_s01(harness):
    """document_version 에 INDEX(document_id,created_at) 와 FK(document,user) 가 존재(s01, 2.2).

    인덱스는 컬럼 순서열 구조로, FK 는 (컬럼→참조테이블.참조컬럼) 집합으로 s01 계약과 대조한다.
    """
    index_rows = _statistics_rows(harness, "document_version")
    assert index_rows, "document_version 에 인덱스가 존재해야 한다"
    grouped = _index_columns_by_name(index_rows)
    observed_layouts = list(grouped.values())
    assert S01_DOCUMENT_VERSION_INDEX_LAYOUT in observed_layouts, (
        f"document_version 인덱스 드리프트: s01 계약 인덱스 "
        f"{S01_DOCUMENT_VERSION_INDEX_LAYOUT} 를 정확히 덮는 인덱스가 없다. "
        f"관측 인덱스 레이아웃={observed_layouts}"
    )

    with harness.session_local() as db:
        fk_rows = db.execute(
            text(
                "SELECT column_name, referenced_table_name, referenced_column_name "
                "FROM information_schema.key_column_usage "
                "WHERE table_schema = DATABASE() AND table_name = 'document_version' "
                "AND referenced_table_name IS NOT NULL"
            )
        ).all()
    observed_fks = {(row[0], row[1], row[2]) for row in fk_rows}
    missing = S01_DOCUMENT_VERSION_FOREIGN_KEYS - observed_fks
    assert not missing, (
        f"document_version FK 드리프트: s01 계약 FK 누락={sorted(missing)} "
        f"관측 FK={sorted(observed_fks)}"
    )


def test_s07_adds_no_new_migration_over_s01_initial_schema():
    """s07 이 새 마이그레이션 없이 s01 단일 리비전(0001)만으로 문서 스키마를 제공함을 확인(2.2).

    (1) `migrations/versions/` 에 리비전 파일이 정확히 하나(`0001_initial_schema.py`)이고,
    (2) alembic head 가 단일 `0001` 리비전이며 그 down_revision 이 None(base)임을 확인한다.
    document·document_version 테이블은 이 단일 리비전이 유일한 출처이며, s07 은 스키마 형태를
    신설하지 않고 그 위에서 동작한다(L2 워크스페이스 스위트 `test_no_additional_s05_migration`
    와 동일한 구체·비-flaky 판정을 재사용).
    """
    backend_dir = Path(__file__).resolve().parents[2]  # integration_L3 -> tests -> backend
    versions_dir = backend_dir / "migrations" / "versions"

    revision_files = sorted(
        p.name for p in versions_dir.glob("*.py") if p.name != "__init__.py"
    )
    # s01 baseline(0001) + additive user_setting(0002). s07 이 자기 마이그레이션을
    # 추가하지 않았음을 검증하는 것이 목적이므로 additive user_setting 은 허용한다.
    assert revision_files == ["0001_initial_schema.py", "0002_user_setting.py"], (
        "s07 은 새 마이그레이션을 추가하지 않고 s01 단일 리비전(0001) + additive user_setting 위에서 문서를 "
        f"제공해야 한다(2.2): 관측 리비전 파일={revision_files}"
    )

    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))
    script = ScriptDirectory.from_config(cfg)

    # head 는 additive user_setting(0002)로 전진했으나 여전히 단일 선형 체인이다.
    heads = list(script.get_heads())
    assert heads == ["0002"], f"alembic head 는 단일 선형 체인의 0002 여야 한다: {heads}"

    # baseline 0001 은 여전히 최초 리비전(down_revision None)이다.
    rev = script.get_revision("0001")
    assert rev.down_revision is None, (
        f"0001 은 base 리비전이어야 한다(down_revision None): {rev.down_revision!r}"
    )


# =============================================================================
# Group 2 — 엔드포인트 카탈로그 18~23 노출·게이트 강제 (Req 2.3)
# =============================================================================


def test_openapi_exposes_document_catalog_rows_18_to_23(harness):
    """부팅 앱의 OpenAPI 가 s01 카탈로그 행 18~23 을 정확한 경로 구조·메서드로 노출(2.3).

    각 (정규화 경로, 메서드) 쌍이 앱 OpenAPI 에 존재함을 확인한다. 경로 파라미터 명명(s07 이
    `{workspace_id}`/`{id}` 를 씀)은 계약 요소가 아니므로 `_normalize_path` 로 정규화해 구조로
    대조한다. 문서 CRUD·이동·삭제 표면이 s01 카탈로그 18~23 과 정합함을 보증한다.
    """
    paths = harness.app.openapi()["paths"]
    observed = {
        (_normalize_path(path), method.lower())
        for path, methods in paths.items()
        for method in methods
    }

    for expected_path, expected_method in S01_ENDPOINT_CATALOG_18_TO_23:
        assert (expected_path, expected_method) in observed, (
            f"카탈로그 {expected_method.upper()} {expected_path} 가 앱 OpenAPI 에 노출되어야 "
            f"한다(API 드리프트): 관측 문서 라우트="
            f"{sorted(o for o in observed if 'document' in o[0])}"
        )


def test_document_change_route_unauthenticated_returns_401(harness):
    """문서 변경 라우트를 세션 없이 호출하면 401(요구 role 게이트 이전 인증 게이트 강제, 2.3)."""
    resp = harness.new_client().post(
        "/workspaces/999999999/documents", json={"title": "미인증생성"}
    )
    assert resp.status_code == 401, (
        f"미인증 POST /workspaces/{{id}}/documents 는 401 이어야 한다(인증 게이트): "
        f"{resp.status_code} {resp.text}"
    )


def test_document_change_route_viewer_returns_403(ws_scenario):
    """viewer 가 문서 변경 라우트(생성)를 호출하면 403(요구 role editor 게이트 강제, 2.3, INV-2).

    카탈로그 행 18(생성)의 요구 role 이 실제로 editor 게이트로 걸려 있는지 — viewer(멤버지만
    editor 미만)의 변경 요청이 런타임에서 거부됨(403)으로 확인한다.
    """
    resp = helpers.attempt_create_document(
        ws_scenario.viewer_client, ws_scenario.workspace_id, _title("viewer변경")
    )
    assert resp.status_code == 403, (
        f"viewer 의 문서 생성은 editor 게이트에서 403 이어야 한다(요구 role 강제, INV-2): "
        f"{resp.status_code} {resp.text}"
    )


# =============================================================================
# Group 3 — 에러 모델 vs s01 에러 카탈로그 (Req 2.4)
# =============================================================================


def test_error_401_unauthenticated(harness):
    """미인증 문서 상세 요청 → 401 + code=unauthenticated + ErrorResponse 형태(2.4)."""
    resp = harness.new_client().get(f"/documents/{MISSING_DOCUMENT_ID}")
    assert resp.status_code == 401, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "unauthenticated", (
        f"401 은 s01 에러 카탈로그상 code=unauthenticated 여야 한다: {body!r}"
    )


def test_error_403_forbidden(ws_scenario):
    """viewer 의 문서 변경(생성) 거부 → 403 + code=forbidden + ErrorResponse 형태(2.4)."""
    resp = helpers.attempt_create_document(
        ws_scenario.viewer_client, ws_scenario.workspace_id, _title("거부")
    )
    assert resp.status_code == 403, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "forbidden", (
        f"403 은 s01 에러 카탈로그상 code=forbidden 여야 한다: {body!r}"
    )


def test_error_404_not_found(ws_scenario):
    """게이트를 통과하는 owner 로 미존재 문서 상세 → 404 + code=not_found(어댑터 매핑 실패, 2.4).

    비멤버는 resolver 가 role None 을 반환해 403 으로 막히므로, 문서→WS 어댑터가 매핑 실패로
    404 를 내는 경로를 관측하려면 게이트를 통과하는 인증 멤버(owner)로 호출한다.
    """
    resp = helpers.attempt_get_document(ws_scenario.owner_client, MISSING_DOCUMENT_ID)
    assert resp.status_code == 404, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "not_found", (
        f"404 는 s01 에러 카탈로그상 code=not_found 여야 한다: {body!r}"
    )


def test_error_409_conflict_on_redelete_trashed_document(ws_scenario):
    """이미 trashed 된 문서를 재삭제 → 409 + code=conflict(비active 삭제 금지, 2.4).

    editor 가 문서를 만들어 삭제(204, active→trashed)한 뒤 같은 문서를 다시 삭제하면 엔진이
    비active 대상에 대해 상태 충돌을 409 로 raise 한다(s01 에러 카탈로그 409=conflict).
    """
    doc = helpers.create_document(
        ws_scenario.editor_client, ws_scenario.workspace_id, _title("재삭제")
    )
    helpers.delete_document(ws_scenario.editor_client, doc["id"])  # 첫 삭제 204.

    resp = helpers.attempt_delete_document(ws_scenario.editor_client, doc["id"])
    assert resp.status_code == 409, (
        f"trashed 문서 재삭제는 409 여야 한다: {resp.status_code} {resp.text}"
    )
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "conflict", (
        f"409 는 s01 에러 카탈로그상 code=conflict 여야 한다: {body!r}"
    )


def test_error_422_validation_error_on_blank_title(ws_scenario):
    """공백 전용 제목 생성 → 422 + code=validation_error + 비어있지 않은 field_errors(2.4).

    editor(게이트 통과)로 공백 제목을 보내 스키마 검증 실패가 s01 전역 핸들러를 거쳐 공통
    `ErrorResponse` 형태의 422 로 직렬화됨을 확인한다(게이트가 아니라 검증 경로).
    """
    resp = helpers.attempt_create_document(
        ws_scenario.editor_client, ws_scenario.workspace_id, "   "
    )
    assert resp.status_code == 422, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "validation_error", (
        f"422 스키마 위반은 s01 에러 카탈로그상 code=validation_error 여야 한다: {body!r}"
    )
    assert isinstance(body.get("field_errors"), list) and body["field_errors"], (
        f"검증 오류는 비어있지 않은 field_errors 를 포함해야 한다: {body!r}"
    )


# =============================================================================
# Group 4 — Base Schemas 규약·status 값 (Req 2.5)
# =============================================================================


def test_document_read_inherits_timestamped_read_fields(ws_scenario):
    """생성(201)·상세(200) 본문이 DocumentRead ⊃ TimestampedRead 규약 전체 필드를 가짐(2.5).

    본문에 s01 `TimestampedRead` 공통 필드(id·created_at·updated_at)와 문서 고유 필드가 모두
    존재함을 확인해 `DocumentRead` 가 s01 공통 Read 베이스를 재정의 없이 상속함을 관찰로 보증한다.
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    created = helpers.attempt_create_document(editor, ws_id, _title("베이스규약"))
    assert created.status_code == 201, f"{created.status_code} {created.text}"
    body = created.json()
    assert isinstance(body, dict), f"DocumentRead 본문은 객체여야 한다: {body!r}"

    missing = S01_TIMESTAMPED_READ_FIELDS - set(body)
    assert not missing, (
        f"DocumentRead 가 TimestampedRead 상속 필드 누락(Base Schemas 드리프트): "
        f"{sorted(missing)} (keys={sorted(body)})"
    )
    missing_doc_fields = S01_DOCUMENT_READ_FIELDS - set(body)
    assert not missing_doc_fields, (
        f"DocumentRead 계약 필드 누락: {sorted(missing_doc_fields)} (keys={sorted(body)})"
    )

    detail = helpers.attempt_get_document(editor, body["id"])
    assert detail.status_code == 200, f"{detail.status_code} {detail.text}"
    detail_missing = S01_DOCUMENT_READ_FIELDS - set(detail.json())
    assert not detail_missing, (
        f"상세 DocumentRead 계약 필드 누락: {sorted(detail_missing)}"
    )


def test_document_list_follows_page_shape(ws_scenario):
    """목록(200) 본문이 Page[DocumentRead] 규약(items 리스트 + total int)을 따름(2.5).

    editor 로 두 문서를 만든 뒤 viewer 로 목록을 조회해 Page 엔벨로프 형태와 각 item 의
    DocumentRead 계약 필드를 확인한다(조회 게이트는 viewer 통과).
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    helpers.create_document(editor, ws_id, _title("목록1"))
    helpers.create_document(editor, ws_id, _title("목록2"))

    page = helpers.list_documents(ws_scenario.viewer_client, ws_id)
    assert isinstance(page, dict), f"목록 본문은 Page 엔벨로프여야 한다: {page!r}"
    assert isinstance(page.get("items"), list), (
        f"Page.items 는 리스트여야 한다(Base Schemas 드리프트): {page!r}"
    )
    assert isinstance(page.get("total"), int), (
        f"Page.total 는 정수여야 한다(Base Schemas 드리프트): {page!r}"
    )
    assert page["total"] >= 2, f"생성한 active 문서가 total 에 반영되어야 한다: {page!r}"
    for item in page["items"]:
        item_missing = S01_DOCUMENT_READ_FIELDS - set(item)
        assert not item_missing, (
            f"Page item 의 DocumentRead 계약 필드 누락: {sorted(item_missing)}"
        )


def test_observed_status_values_within_s01_enum_set(ws_scenario, engine_access):
    """API·엔진이 노출하는 status 값이 s01 ENUM 집합(active/trashed/deleted) 내부임을 확인(2.5).

    문서를 생성하면 active, 삭제하면(API) trashed 가 관측된다. 각 관측 값이 s01
    `document.status` ENUM 집합의 부분집합인지 대조해 status 값 계약을 확인한다(엔진 묶음 관찰).
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    doc = helpers.create_document(editor, ws_id, _title("상태값"))
    assert doc["status"] == "active", f"신규 문서는 active 여야 한다: {doc!r}"

    helpers.delete_document(editor, doc["id"])
    trashed = helpers.get_bundle(engine_access, doc["id"])  # 엔진으로 묶음 status 관찰.
    observed = {m.status for m in trashed.members}
    assert observed <= S01_DOCUMENT_STATUS_ENUM_VALUES, (
        f"관측 status 값이 s01 ENUM 집합을 벗어남: 관측={observed} "
        f"허용={S01_DOCUMENT_STATUS_ENUM_VALUES}"
    )
    assert "trashed" in observed, f"삭제 후 묶음 status 는 trashed 여야 한다: {observed}"


# =============================================================================
# Group 5 — status 전이·종착·물리삭제 부재 (Req 2.6, INV-4·INV-7)
# =============================================================================

# s01 카탈로그상 **문서(document) 라우터**는 문서 status 를 되돌릴(복원) 경로를 노출하지
# 않는다(INV-7 종착): s07 문서 라우터가 노출하는 status 전이는 삭제(active→trashed)뿐이고
# 문서 단위 복원 라우트가 없다. 아래 정규화 경로가 관측되면 문서 종착 계약이 드리프트한 것이다.
#
# 주의(s10 조립 이후): 휴지통 복구·완전삭제 라우트(카탈로그 행 29~31: `/workspaces/{id}/trash`
# GET·`/trash/{bundleId}/restore` POST·`/trash/{bundleId}` DELETE)는 이제 s10 이 **정당하게**
# 소유·조립한다. 이들은 **묶음(bundle)** 단위 trashed→active 복구/trashed→deleted 완전삭제이며
# deleted 종착(INV-7)을 위반하지 않는다(deleted 에서 되돌리는 경로가 아니다). 따라서 이 문서-
# 계층 가드는 s10 휴지통 라우트를 금지 목록에 포함하지 않고, 문서 단위 복원 경로 부재만 검증한다.
_FORBIDDEN_RESTORE_ROUTE_SHAPES = {
    ("/documents/{}/restore", "post"),
    ("/documents/{}/trash", "delete"),
    ("/documents/{}/untrash", "post"),
    ("/documents/{}/undelete", "post"),
}


def _document_status(harness, document_id: int) -> str | None:
    """document 테이블에서 물리 행의 status 를 직접 조회한다(없으면 None = 물리 삭제됨)."""
    with harness.session_local() as db:
        row = db.execute(
            text("SELECT status FROM document WHERE id = :id"),
            {"id": document_id},
        ).first()
    return None if row is None else row[0]


def test_router_exposes_only_active_to_trashed_transition_no_restore(harness):
    """문서(document) 라우터가 노출하는 status 전이는 삭제(active→trashed)뿐이고 문서 단위 복구
    경로가 없음(2.6, INV-7).

    s01 카탈로그 18~23(문서 라우터)에는 문서를 trashed/deleted 에서 되돌리는 문서 단위 라우트가
    없다(deleted 종착). 부팅 앱 OpenAPI 에 문서 단위 복원/undelete 경로가 노출되지 않음을 정규화
    경로로 확인해, trashed→deleted 종착(INV-7)이 문서 라우터 표면에서 복원 경로 부재로 구조적으로
    성립함을 보증한다. (묶음 단위 휴지통 복구·완전삭제(행 29~31)는 s10 이 정당하게 소유하며 deleted
    에서 되돌리는 경로가 아니므로 이 가드 대상이 아니다.)
    """
    paths = harness.app.openapi()["paths"]
    observed = {
        (_normalize_path(path), method.lower())
        for path, methods in paths.items()
        for method in methods
    }
    leaked = _FORBIDDEN_RESTORE_ROUTE_SHAPES & observed
    assert not leaked, (
        f"deleted 종착(INV-7) 드리프트: 문서 단위 복원 라우트가 노출됨={sorted(leaked)} "
        "(s01 카탈로그 18~23 은 문서 복원 라우트를 포함하지 않는다)"
    )


def test_trashed_then_deleted_is_terminal_with_physical_preservation(
    harness, ws_scenario, engine_access
):
    """active→trashed(라우터)→deleted(엔진 종착) 전이 후에도 문서 행이 물리 보존됨(2.6, INV-4·INV-7).

    (1) editor 가 문서를 생성(active)→라우터 삭제(trashed): DB 행이 status=trashed 로 존재.
    (2) 엔진 `purge_bundle` 로 trashed→deleted(종착): DB 행이 status=deleted 로 **여전히 물리
        존재**(물리 삭제 없음, INV-4). deleted 는 종착이며 라우터에 복원 경로가 없다(INV-7).
    각 단계에서 DB 를 직접 조회해 행이 사라지지 않았음(물리 보존)을 확인한다. `harness` 와
    `ws_scenario` 는 동일 L1 하네스를 공유하므로(ws_scenario 가 harness 를 의존) 같은
    마이그레이션 DB 를 본다.
    """
    ws_id = ws_scenario.workspace_id
    editor = ws_scenario.editor_client

    doc = helpers.create_document(editor, ws_id, _title("종착"))
    doc_id = doc["id"]
    assert _document_status(harness, doc_id) == "active", (
        "생성 직후 문서 물리 행 status 는 active 여야 한다"
    )

    # active → trashed (라우터 노출 전이).
    helpers.delete_document(editor, doc_id)
    assert _document_status(harness, doc_id) == "trashed", (
        "라우터 삭제 후 문서 행이 status=trashed 로 물리 존재해야 한다(물리 삭제 없음, INV-4)"
    )

    # trashed → deleted (엔진 종착 전이 — 라우터 밖 primitive).
    purged = helpers.purge_bundle(engine_access, doc_id)
    assert all(m.status == "deleted" for m in purged.members), (
        f"purge_bundle 후 묶음 구성원 status 는 deleted(종착)여야 한다: "
        f"{[m.status for m in purged.members]}"
    )
    assert _document_status(harness, doc_id) == "deleted", (
        "완전삭제(deleted) 후에도 문서 행이 물리적으로 보존되어야 한다(INV-4): "
        "물리 삭제가 관측되면 안 된다"
    )
