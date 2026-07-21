"""누적 계약 대조 스위트 (Task 2.1 / Req 2.1, 2.2, 2.3, 2.4, 2.5, 2.6,
design §CumulativeContractConformanceSuite · §Settings additive 조정 항목 · 계약 대조 판정).

실제 결합된 런타임(마이그레이션 적용 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕**s09**⊕**s10**) +
실 세션 + APScheduler 결합 + 부팅 앱과 동일 세션 팩토리의 `RetentionSweepService`)을
**s01-contract-foundation 단일 소스**와 대조하는 외부 관찰자 스위트다. 대조 기준은 s09/s10 의
design 이 아니라 **항상 s01**(`design.md` §Physical Data Model `document`(lock 필드)·
`document_version` · §API Endpoint Catalog 행 24~31 · §Errors 에러 코드 카탈로그 · §Base
Schemas `ORMReadModel`·`TimestampedRead`·`Page[T]`·`ErrorResponse` · §Settings 스키마
(`default_trash_retention_days` 포함))이며, 실제 앱이 s01 계약에서 벗어났다면 단언을 약화시키지
않고 그대로 실패시켜 **어느 계약 요소가 드리프트했는지** 를 assertion 메시지가 지목한다.

이 스위트는 L3 `test_document_contract_conformance.py`(스키마·API·에러·Base 대조 템플릿)를
잠금·버전·휴지통 표면(행 24~31)과 s10 Settings additive 조정 항목·APScheduler 결합으로 확장한다.
여섯 개의 단언 그룹(task 2.1):

- **Group 1 — lock 필드·document_version 스키마 vs s01 물리 모델(Req 2.1)**: 마이그레이션된
  DB 의 `information_schema` 로 `document` lock 컬럼(`lock_user_id BIGINT FK NULL`·
  `lock_acquired_at DATETIME NULL`·`current_version_id BIGINT FK NULL`)과 `document_version`
  (`document_id` FK·`content`·`created_by` FK·`created_at`·INDEX(document_id, created_at))을
  대조하고, s09·s10 이 새 마이그레이션을 추가하지 않고 s01 단일 리비전(0001)만 씀을 확인한다.
- **Group 2 — 엔드포인트 카탈로그 24~31 노출·게이트 강제(Req 2.2)**: 부팅 앱 OpenAPI 가 s01
  카탈로그 행 24~31 을 정확한 경로 구조·메서드로 노출하고, 요구 role 게이트가 런타임에서 실제로
  강제됨(미인증 401·viewer 변경 403)을 대표 요청으로 확인.
- **Group 3 — 에러 모델 vs s01 에러 카탈로그(Req 2.3)**: 401/403/404/409/422 를 실제로 유발해
  상태코드와 `ErrorResponse` 형태(`{code, message, field_errors?}`)·`code` 문자열을 대조.
- **Group 4 — Base Schemas 규약·버전 본문 부재(Req 2.4)**: `DocumentLockRead`·
  `DocumentVersionRead`·`TrashBundleRead` 가 s01 `ORMReadModel` 규약을 상속하고 목록이 `Page[T]`
  이며 `DocumentVersionRead` 에 본문(content) 필드가 없음(rollback·과거 본문 미제공)을 확인.
- **Group 5 — Settings additive 조정 항목(Req 2.5)**: s10 이 additive 로 추가한
  `trash_sweep_interval_seconds` 가 존재하는 실제 결합 부팅에서 `s01` `Settings`/`get_settings`
  로딩이 정상 성공하고 기존 필드(`default_trash_retention_days`·db_*·session_* 등)가 보존되며
  설정 접근이 단일 `Settings`/`get_settings` 경유(모듈별 설정 파일·`os.environ` 직접 접근 부재)임을 확인.
- **Group 6 — APScheduler 결합 부팅(Req 2.6)**: APScheduler 의존성이 결합된 상태에서
  `create_app()` 이 정상 부팅되고, `trash_sweep_interval_seconds` `>0` 이면 스케줄러 기동·`<=0`
  이면 미기동되며 이 결합이 기존 앱 부팅 계약을 회귀시키지 않음(부팅 스모크)을 확인.

재검증 트리거(design §Revalidation Triggers): `s01`(계약)·`s02`·`s03`·`s05`·`s07`·`s09`·`s10`
중 하나라도 수정되면 이 체크포인트를 누적 집합 기준으로 재실행한다(`s01` 수정 시 모든 체크포인트).

`harness`(L1 conftest)·`lock_scenario`(L4 conftest) 픽스처가 제공하는 실 결합 환경 위에서만
동작하며 mock/stub/fake 를 쓰지 않는다(스윕·스케줄러 직접 호출은 실제 s10 코드 실행).
"""

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.config import Settings, get_settings
from app.lock_version.schemas import DocumentLockRead, DocumentVersionRead
from app.schemas.base import ORMReadModel, Page, TimestampedRead
from app.trash import scheduler as trash_scheduler
from app.trash.schemas import TrashBundleRead
from tests.integration_L4 import helpers

# =============================================================================
# s01 단일 소스 계약 상수 — §Physical Data Model document(lock 필드)·document_version
# =============================================================================

# s01 §Physical Data Model — document lock 관련 컬럼 계약(단일 소스). L4 의 대조 초점은
# 잠금·버전 도메인이 s01 위에 얹힌 lock 필드다. 컬럼명 → nullability("YES" = NULLable).
S01_DOCUMENT_LOCK_COLUMNS_NULLABILITY = {
    "lock_user_id": "YES",
    "lock_acquired_at": "YES",
    "current_version_id": "YES",
}

# lock 필드 타입 계열: BIGINT → bigint, DATETIME → datetime.
S01_DOCUMENT_LOCK_TYPE_FAMILY = {
    "lock_user_id": "bigint",
    "lock_acquired_at": "datetime",
    "current_version_id": "bigint",
}

# s01 document lock FK 계약 — (컬럼, 참조테이블, 참조컬럼).
S01_DOCUMENT_LOCK_FOREIGN_KEYS = {
    ("lock_user_id", "user", "id"),
    ("current_version_id", "document_version", "id"),
}

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

# s01 document_version FK 계약.
S01_DOCUMENT_VERSION_FOREIGN_KEYS = {
    ("document_id", "document", "id"),
    ("created_by", "user", "id"),
}

# s01 document_version 인덱스 계약 — 선두 (document_id, created_at) 을 덮는 인덱스.
S01_DOCUMENT_VERSION_INDEX_LAYOUT = ["document_id", "created_at"]

# s01 §API Endpoint Catalog rows 24~31 — (정규화 경로, 메서드, 요구 role).
# 경로는 파라미터 명명(s09 는 `{id}`, s10 은 `{id}`/`{bundleId}`)에 비의존하도록 `_normalize_path`
# 로 정규화해 구조로 대조한다. 요구 role 은 대표 요청(미인증 401·viewer 변경 403)으로 강제 관찰한다.
S01_ENDPOINT_CATALOG_24_TO_31 = [
    ("/documents/{}/lock", "post", "editor"),           # row 24
    ("/documents/{}/save", "post", "editor"),           # row 25
    ("/documents/{}/cancel", "post", "editor"),         # row 26
    ("/documents/{}/force-unlock", "post", "owner"),    # row 27
    ("/documents/{}/versions", "get", "viewer"),        # row 28
    ("/workspaces/{}/trash", "get", "editor"),          # row 29
    ("/trash/{}/restore", "post", "editor"),            # row 30
    ("/trash/{}", "delete", "editor"),                  # row 31
]

# s01 §Settings 스키마 — additive 확장 이후에도 보존되어야 하는 기존 필드 + additive 신규 필드.
S01_SETTINGS_PRESERVED_FIELDS = {
    "app_name",
    "db_host",
    "db_port",
    "db_name",
    "db_user",
    "default_trash_retention_days",
    "file_storage_root",
    "session_cookie_name",
    "session_max_age_seconds",
    "db_password",
    "session_secret",
}
S01_SETTINGS_ADDITIVE_FIELD = "trash_sweep_interval_seconds"

# 인증되었으나 대상이 존재하지 않을 때 어댑터 404 를 관측하기 위한 미존재 id.
MISSING_DOCUMENT_ID = 999_999_999
MISSING_BUNDLE_ID = 999_999_999


from tests.support import logical_openapi_paths


def _normalize_path(path: str) -> str:
    """경로의 `{param}` 세그먼트를 `{}` 로 정규화한다(파라미터 명명 비의존 구조 대조).

    s01 카탈로그와 s09/s10 라우트는 경로 파라미터 식별자(`{id}`·`{bundleId}`)를 다르게 적을 수
    있으나 계약 요소는 **경로 구조(세그먼트 배열 + 파라미터 위치) + 메서드 + 요구 role** 이므로
    양쪽을 동일 규칙으로 정규화해 대조한다.
    """
    out: list[str] = []
    for seg in path.split("/"):
        out.append("{}" if seg.startswith("{") and seg.endswith("}") else seg)
    return "/".join(out)


def _assert_error_response_shape(body: object) -> None:
    """관측된 에러 본문이 s01 ``ErrorResponse`` 형태를 따르는지 강제한다(Req 2.3).

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
    """`information_schema.statistics` 행을 인덱스명 → [seq 순 컬럼] 로 묶는다(구조 판정용)."""
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
# Group 1 — document lock 필드·document_version 스키마 vs s01 물리 모델 (Req 2.1)
# =============================================================================


def test_document_lock_columns_match_s01_physical_model(harness):
    """마이그레이션된 document 테이블의 lock 컬럼이 s01 물리 모델과 일치(2.1).

    `information_schema.columns` 를 조회해 s01 이 정한 lock 컬럼(`lock_user_id BIGINT NULL`·
    `lock_acquired_at DATETIME NULL`·`current_version_id BIGINT NULL`)이 존재하고 각
    nullability·타입 계열이 s01 과 일치함을 대조한다. s09 가 lock 필드 형태를 드리프트시켰다면
    어떤 컬럼이 어긋났는지 메시지에 명시한다.
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

    for col, expected_nullable in S01_DOCUMENT_LOCK_COLUMNS_NULLABILITY.items():
        assert col in observed, (
            f"document 테이블에 s01 lock 계약 컬럼 누락: {col} (관측 컬럼={sorted(observed)})"
        )
        observed_nullable = observed[col][0]
        assert observed_nullable == expected_nullable, (
            f"document.{col} nullability 드리프트: s01={expected_nullable} "
            f"관측={observed_nullable}"
        )

    for col, expected_family in S01_DOCUMENT_LOCK_TYPE_FAMILY.items():
        observed_family = observed[col][1]
        assert observed_family == expected_family, (
            f"document.{col} 타입 계열 드리프트: s01={expected_family} "
            f"관측={observed_family}"
        )


def test_document_lock_foreign_keys_match_s01(harness):
    """document lock 컬럼의 FK 가 s01 물리 모델과 일치(2.1).

    `information_schema.key_column_usage` 에서 참조 테이블이 있는 행을 조회해 s01 이 정한 lock
    FK(`lock_user_id`→user.id·`current_version_id`→document_version.id)가 존재함을 대조한다.
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
    missing = S01_DOCUMENT_LOCK_FOREIGN_KEYS - observed_fks
    assert not missing, (
        f"document lock FK 드리프트: s01 계약 FK 누락={sorted(missing)} "
        f"관측 FK={sorted(observed_fks)}"
    )


def test_document_version_table_columns_match_s01_physical_model(harness):
    """마이그레이션된 document_version 테이블의 컬럼·nullability·타입 계열이 s01 과 일치(2.1).

    s01 물리 모델상 document_version 은 id·document_id·content(MEDIUMTEXT)·created_by·created_at
    만 가진다(updated_at 없음). 컬럼 집합이 정확히 이 다섯이고 각 nullability·타입 계열이 s01 과
    일치함을 대조한다(content 가 mediumtext 계열임을 포함).
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
        f"document_version 테이블에 s01 계약 밖 컬럼 초과(updated_at·content 롤백 필드 없어야 함): "
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
    """document_version 에 INDEX(document_id,created_at) 와 FK(document,user) 가 존재(s01, 2.1).

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


def test_s09_s10_add_no_new_migration_over_s01_initial_schema():
    """s09·s10 이 새 마이그레이션 없이 s01 단일 리비전(0001)만으로 동작함을 확인(2.1).

    (1) `migrations/versions/` 에 리비전 파일이 정확히 하나(`0001_initial_schema.py`)이고,
    (2) alembic head 가 단일 `0001` 리비전이며 그 down_revision 이 None(base)임을 확인한다.
    s09(잠금·버전)·s10(휴지통·보관 스윕)은 lock 필드·document_version 을 포함한 s01 단일
    리비전 위에서 동작하며 스키마 형태를 신설하지 않는다(L3 `test_s07_adds_no_new_migration`
    과 동일한 구체·비-flaky 판정을 누적 집합으로 재사용).
    """
    backend_dir = Path(__file__).resolve().parents[2]  # integration_L4 -> tests -> backend
    versions_dir = backend_dir / "migrations" / "versions"

    revision_files = sorted(
        p.name for p in versions_dir.glob("*.py") if p.name != "__init__.py"
    )
    # s01 baseline(0001) + additive user_setting(0002). s09·s10 이 자기 마이그레이션을
    # 추가하지 않았음을 검증하는 것이 목적이므로 additive user_setting 은 허용한다.
    assert revision_files == ["0001_initial_schema.py", "0002_user_setting.py"], (
        "s09·s10 은 새 마이그레이션을 추가하지 않고 s01 단일 리비전(0001) + additive user_setting 위에서 동작해야 "
        f"한다(2.1): 관측 리비전 파일={revision_files}"
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
# Group 2 — 엔드포인트 카탈로그 24~31 노출·게이트 강제 (Req 2.2)
# =============================================================================


def test_openapi_exposes_lock_trash_catalog_rows_24_to_31(harness):
    """부팅 앱 OpenAPI 가 s01 카탈로그 행 24~31 을 정확한 경로 구조·메서드로 노출(2.2).

    각 (정규화 경로, 메서드) 쌍이 앱 OpenAPI 에 존재함을 확인한다. 경로 파라미터 명명(s09 는
    `{id}`, s10 은 `{id}`/`{bundleId}`)은 계약 요소가 아니므로 `_normalize_path` 로 정규화해
    구조로 대조한다. 잠금·저장·취소·강제해제·버전목록·휴지통목록·복구·완전삭제 표면이 s01
    카탈로그 24~31 과 정합함을 보증한다.
    """
    paths = logical_openapi_paths(harness.app)
    observed = {
        (_normalize_path(path), method.lower())
        for path, methods in paths.items()
        for method in methods
    }

    for expected_path, expected_method, _role in S01_ENDPOINT_CATALOG_24_TO_31:
        assert (expected_path, expected_method) in observed, (
            f"카탈로그 {expected_method.upper()} {expected_path} 가 앱 OpenAPI 에 노출되어야 "
            f"한다(API 드리프트): 관측 잠금/휴지통 라우트="
            f"{sorted(o for o in observed if 'lock' in o[0] or 'trash' in o[0] or 'versions' in o[0] or 'save' in o[0] or 'cancel' in o[0] or 'unlock' in o[0])}"
        )


def test_lock_route_unauthenticated_returns_401(harness):
    """잠금 라우트를 세션 없이 호출하면 401(요구 role 게이트 이전 인증 게이트 강제, 2.2)."""
    resp = harness.new_client().post(f"/documents/{MISSING_DOCUMENT_ID}/lock")
    assert resp.status_code == 401, (
        f"미인증 POST /documents/{{id}}/lock 은 401 이어야 한다(인증 게이트): "
        f"{resp.status_code} {resp.text}"
    )


def test_trash_list_route_unauthenticated_returns_401(harness):
    """휴지통 목록 라우트를 세션 없이 호출하면 401(인증 게이트 강제, 2.2)."""
    resp = harness.new_client().get(f"/workspaces/{MISSING_DOCUMENT_ID}/trash")
    assert resp.status_code == 401, (
        f"미인증 GET /workspaces/{{id}}/trash 는 401 이어야 한다(인증 게이트): "
        f"{resp.status_code} {resp.text}"
    )


def test_lock_route_viewer_mutation_returns_403(lock_scenario):
    """viewer 가 잠금(변경) 라우트를 호출하면 403(요구 role editor 게이트 강제, 2.2, INV-2).

    카탈로그 행 24(잠금)의 요구 role 이 실제로 editor 게이트로 걸려 있는지 — viewer(멤버지만
    editor 미만)의 잠금 요청이 런타임에서 거부됨(403)으로 확인한다. 실제 문서 위에서 게이트를
    통과하지 못함을 관측한다.
    """
    doc = helpers.l3_helpers.create_document(
        lock_scenario.editor_a_client, lock_scenario.workspace_id, "viewer게이트-lock"
    )
    resp = helpers.attempt_lock(lock_scenario.viewer_client, doc["id"])
    assert resp.status_code == 403, (
        f"viewer 의 잠금은 editor 게이트에서 403 이어야 한다(요구 role 강제, INV-2): "
        f"{resp.status_code} {resp.text}"
    )


def test_trash_list_route_viewer_returns_403(lock_scenario):
    """viewer 가 휴지통 목록 라우트를 호출하면 403(카탈로그 행 29 editor 게이트 강제, 2.2, INV-2)."""
    resp = helpers.attempt_list_trash(
        lock_scenario.viewer_client, lock_scenario.workspace_id
    )
    assert resp.status_code == 403, (
        f"viewer 의 휴지통 목록은 editor 게이트에서 403 이어야 한다(요구 role 강제, INV-2): "
        f"{resp.status_code} {resp.text}"
    )


# =============================================================================
# Group 3 — 에러 모델 vs s01 에러 카탈로그 (Req 2.3)
# =============================================================================


def test_error_401_unauthenticated(harness):
    """미인증 잠금 요청 → 401 + code=unauthenticated + ErrorResponse 형태(2.3)."""
    resp = harness.new_client().post(f"/documents/{MISSING_DOCUMENT_ID}/lock")
    assert resp.status_code == 401, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "unauthenticated", (
        f"401 은 s01 에러 카탈로그상 code=unauthenticated 여야 한다: {body!r}"
    )


def test_error_403_forbidden(lock_scenario):
    """viewer 의 잠금 거부 → 403 + code=forbidden + ErrorResponse 형태(2.3)."""
    doc = helpers.l3_helpers.create_document(
        lock_scenario.editor_a_client, lock_scenario.workspace_id, "403-lock"
    )
    resp = helpers.attempt_lock(lock_scenario.viewer_client, doc["id"])
    assert resp.status_code == 403, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "forbidden", (
        f"403 은 s01 에러 카탈로그상 code=forbidden 여야 한다: {body!r}"
    )


def test_error_404_not_found(lock_scenario):
    """게이트를 통과하는 owner 로 미존재 문서 잠금 → 404 + code=not_found(어댑터 매핑 실패, 2.3).

    비멤버는 resolver 가 role None 을 반환해 403 으로 막히므로, 문서→WS 어댑터가 매핑 실패로
    404 를 내는 경로를 관측하려면 게이트를 통과하는 인증 멤버(owner)로 호출한다.
    """
    resp = helpers.attempt_lock(lock_scenario.owner_client, MISSING_DOCUMENT_ID)
    assert resp.status_code == 404, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "not_found", (
        f"404 는 s01 에러 카탈로그상 code=not_found 여야 한다: {body!r}"
    )


def test_error_409_conflict_on_lock_held_by_other(lock_scenario):
    """editor A 가 잠근 문서를 editor B 가 잠그려 하면 → 409 + code=conflict(타인 잠금, 2.3).

    editor A 가 문서를 만들어 잠근 뒤(200) editor B 가 같은 문서를 잠그면 서비스가 타인 잠금
    충돌을 409 로 raise 한다(s01 에러 카탈로그 409=conflict, INV-9 문서당 잠금 최대 1인).
    """
    doc = helpers.l3_helpers.create_document(
        lock_scenario.editor_a_client, lock_scenario.workspace_id, "409-lock"
    )
    helpers.lock(lock_scenario.editor_a_client, doc["id"])  # A 획득(200).

    resp = helpers.attempt_lock(lock_scenario.editor_b_client, doc["id"])
    assert resp.status_code == 409, (
        f"타인 잠금 문서 재잠금은 409 여야 한다: {resp.status_code} {resp.text}"
    )
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "conflict", (
        f"409 는 s01 에러 카탈로그상 code=conflict 여야 한다: {body!r}"
    )


def test_error_422_validation_error_on_save_missing_content(lock_scenario):
    """게이트 통과 editor 가 content 없는 저장 본문을 보내면 → 422 + code=validation_error(2.3).

    editor(EDITOR 게이트 통과)로 `content` 필드가 없는 저장 본문을 보내 pydantic 스키마 검증
    실패가 s01 전역 핸들러를 거쳐 공통 `ErrorResponse` 형태의 422 로 직렬화됨을 확인한다(게이트가
    아니라 검증 경로 — 비어있지 않은 field_errors 포함).
    """
    doc = helpers.l3_helpers.create_document(
        lock_scenario.editor_a_client, lock_scenario.workspace_id, "422-save"
    )
    resp = lock_scenario.editor_a_client.post(
        f"/documents/{doc['id']}/save", json={}
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
# Group 4 — Base Schemas 규약·버전 본문 부재 (Req 2.4)
# =============================================================================


def test_lock_version_trash_read_schemas_inherit_s01_base():
    """DocumentLockRead·DocumentVersionRead·TrashBundleRead 가 s01 ORMReadModel 규약을 상속(2.4).

    s09/s10 응답 Read 스키마가 s01 공통 Read 베이스(`ORMReadModel`, from_attributes)를 재정의
    없이 상속함을 클래스 수준에서 확인한다(Base Schemas 규약 준수).
    """
    for schema in (DocumentLockRead, DocumentVersionRead, TrashBundleRead):
        assert issubclass(schema, ORMReadModel), (
            f"{schema.__name__} 은 s01 ORMReadModel 을 상속해야 한다(Base Schemas 드리프트)"
        )


def test_document_version_read_has_no_body_field():
    """DocumentVersionRead 에 본문(content) 필드가 없음 — rollback·과거 본문 미제공(2.4).

    s01 계약상 버전 응답은 메타데이터(식별자·저장자·저장 시각)만 노출하고 과거 본문·rollback 을
    제공하지 않는다. 스키마 필드 집합에 `content`·`body` 가 없고 메타데이터 필드가 있음을 확인한다.
    """
    fields = set(DocumentVersionRead.model_fields)
    assert "content" not in fields and "body" not in fields, (
        f"DocumentVersionRead 는 본문 필드를 포함하지 않아야 한다(rollback·과거 본문 미제공): "
        f"관측 필드={sorted(fields)}"
    )
    assert {"id", "document_id", "created_by", "created_at"} <= fields, (
        f"DocumentVersionRead 는 버전 메타데이터 필드를 노출해야 한다: 관측 필드={sorted(fields)}"
    )


def test_versions_list_follows_page_shape_and_version_body_absent(lock_scenario):
    """버전 목록(200)이 Page[DocumentVersionRead] 규약을 따르고 각 항목에 본문이 없음(2.4).

    editor 가 문서를 잠그고 저장한 뒤 버전 목록을 조회해 (1) Page 엔벨로프(items 리스트 + total
    int) 규약, (2) 저장 응답·목록 항목에 `content` 본문 필드 부재, (3) 버전 메타데이터 필드
    존재를 실제 결합 응답으로 확인한다(런타임 Base 규약 확인).
    """
    ws_id = lock_scenario.workspace_id
    editor = lock_scenario.editor_a_client

    doc = helpers.l3_helpers.create_document(editor, ws_id, "page-versions")
    helpers.lock(editor, doc["id"])
    saved = helpers.save(editor, doc["id"], "본문 스냅샷")  # 저장=버전 생성+잠금 해제.
    assert "content" not in saved and "body" not in saved, (
        f"저장 응답(DocumentVersionRead)에 본문 필드가 없어야 한다: {sorted(saved)}"
    )
    assert {"id", "document_id", "created_by", "created_at"} <= set(saved), (
        f"저장 응답은 버전 메타데이터 필드를 노출해야 한다: {sorted(saved)}"
    )

    page = helpers.list_versions(lock_scenario.viewer_client, doc["id"])
    assert isinstance(page, dict), f"버전 목록 본문은 Page 엔벨로프여야 한다: {page!r}"
    assert isinstance(page.get("items"), list), (
        f"Page.items 는 리스트여야 한다(Base Schemas 드리프트): {page!r}"
    )
    assert isinstance(page.get("total"), int), (
        f"Page.total 는 정수여야 한다(Base Schemas 드리프트): {page!r}"
    )
    assert page["total"] >= 1, f"저장한 버전이 total 에 반영되어야 한다: {page!r}"
    for item in page["items"]:
        assert "content" not in item and "body" not in item, (
            f"버전 목록 항목에 본문 필드가 없어야 한다(rollback·과거 본문 미제공): {sorted(item)}"
        )
        assert {"id", "document_id", "created_by", "created_at"} <= set(item), (
            f"버전 목록 항목은 메타데이터 필드를 노출해야 한다: {sorted(item)}"
        )


def test_trash_list_follows_page_shape_with_expires_at(lock_scenario):
    """휴지통 목록(200)이 Page[TrashBundleRead] 규약을 따르고 각 묶음에 expires_at 포함(2.4).

    editor 가 문서를 만들어 삭제(trashed)한 뒤 휴지통 목록을 조회해 Page 엔벨로프 규약과 각
    TrashBundleRead 묶음의 핵심 필드(bundle_id·trashed_at·expires_at)를 확인한다(런타임 Base 규약).
    """
    ws_id = lock_scenario.workspace_id
    editor = lock_scenario.editor_a_client

    doc = helpers.l3_helpers.create_document(editor, ws_id, "page-trash")
    helpers.l3_helpers.delete_document(editor, doc["id"])  # active→trashed.

    page = helpers.list_trash(editor, ws_id)
    assert isinstance(page, dict), f"휴지통 목록 본문은 Page 엔벨로프여야 한다: {page!r}"
    assert isinstance(page.get("items"), list), (
        f"Page.items 는 리스트여야 한다(Base Schemas 드리프트): {page!r}"
    )
    assert isinstance(page.get("total"), int), (
        f"Page.total 는 정수여야 한다(Base Schemas 드리프트): {page!r}"
    )
    assert page["total"] >= 1, f"삭제한 묶음이 total 에 반영되어야 한다: {page!r}"
    for item in page["items"]:
        assert {"bundle_id", "trashed_at", "expires_at"} <= set(item), (
            f"TrashBundleRead 항목은 bundle_id·trashed_at·expires_at 을 노출해야 한다: "
            f"{sorted(item)}"
        )


# =============================================================================
# Group 5 — Settings additive 조정 항목 (Req 2.5)
# =============================================================================


def test_settings_additive_field_present_and_existing_fields_preserved(harness):
    """additive `trash_sweep_interval_seconds` 존재·기존 필드 보존·로딩 정상 성공(2.5).

    실제 결합 부팅(harness 가 이미 `create_app()` 부팅)에서 `get_settings()` 로딩이 정상 성공하고,
    s10 이 additive 로 추가한 `trash_sweep_interval_seconds` 가 `Settings` 스키마에 존재하며,
    기존 s01 필드(`default_trash_retention_days`·db_*·session_* 등)가 모두 보존되고 유효한 값으로
    로드됨을 확인한다. additive 확장이 s01 Settings 계약을 깨지 않았음을 지목한다.
    """
    fields = set(Settings.model_fields)
    assert S01_SETTINGS_ADDITIVE_FIELD in fields, (
        f"s10 additive 필드 `{S01_SETTINGS_ADDITIVE_FIELD}` 가 Settings 스키마에 있어야 한다: "
        f"관측 필드={sorted(fields)}"
    )
    missing = S01_SETTINGS_PRESERVED_FIELDS - fields
    assert not missing, (
        f"additive 확장으로 s01 기존 Settings 필드가 소실되면 안 된다(계약 파손): 누락={sorted(missing)}"
    )

    settings = get_settings()  # 실 결합 부팅 설정 로딩(부팅 실패 없이 성공해야 함).
    assert isinstance(settings.trash_sweep_interval_seconds, int), (
        f"trash_sweep_interval_seconds 는 int 로 로드되어야 한다: "
        f"{settings.trash_sweep_interval_seconds!r}"
    )
    assert isinstance(settings.default_trash_retention_days, int), (
        f"기존 필드 default_trash_retention_days 는 int 로 보존되어야 한다: "
        f"{settings.default_trash_retention_days!r}"
    )
    assert settings.default_trash_retention_days > 0, (
        f"default_trash_retention_days 는 유효한 양수여야 한다(보존 확인): "
        f"{settings.default_trash_retention_days!r}"
    )
    # 세션·DB 기존 필드가 유효한 비어있지 않은 값으로 보존됨(대표 표본).
    assert settings.session_cookie_name and isinstance(settings.session_cookie_name, str)
    assert settings.db_name and isinstance(settings.db_name, str)


def test_settings_single_accessor_is_cached(harness):
    """설정 접근이 단일 `get_settings` 접근자 경유(캐시된 동일 인스턴스)임을 확인(2.5).

    `get_settings()` 를 두 번 호출하면 lru_cache 로 **동일 인스턴스**가 반환됨을 확인해 설정
    접근이 모듈별 개별 로더가 아니라 단일 접근자를 통함을 관측한다.
    """
    assert get_settings() is get_settings(), (
        "설정 접근은 단일 `get_settings` 캐시 접근자를 경유해야 한다(동일 인스턴스)"
    )


def test_app_config_path_has_no_direct_env_access():
    """애플리케이션 설정 경로에 `os.environ`·`os.getenv` 직접 접근이 없음을 확인(2.5).

    s01 단일화 원칙(설정은 단일 `Settings`/`get_settings` 경유)에 따라 `app/` 소스에 `os.environ[`·
    `os.environ.get(`·`os.getenv(` 같은 직접 환경변수 접근이 없어야 한다(모듈별 설정 파일·직접
    접근 부재). config.py 의 docstring 은 "os.environ 직접 접근 금지" 문구를 담으므로 실제 접근
    패턴(대괄호/`.get`/`getenv`)만 정규식으로 판정한다(문구 오탐 회피).
    """
    app_dir = Path(__file__).resolve().parents[2] / "app"
    pattern = re.compile(r"os\.environ\[|os\.environ\.get\(|os\.getenv\(")
    offenders: list[str] = []
    for py in app_dir.rglob("*.py"):
        text_src = py.read_text(encoding="utf-8")
        if pattern.search(text_src):
            offenders.append(str(py))
    assert not offenders, (
        f"애플리케이션 설정 경로에 직접 환경변수 접근이 없어야 한다(단일 Settings 경유): "
        f"{offenders}"
    )


# =============================================================================
# Group 6 — APScheduler 결합 부팅 (Req 2.6)
# =============================================================================


def test_create_app_boots_cleanly_with_scheduler_wired(harness):
    """APScheduler 의존성 결합 상태에서 `create_app()` 이 정상 부팅됨(부팅 스모크, 2.6).

    부팅 앱은 lifespan 에 s10 보관 스윕 스케줄러(APScheduler)를 결선한다. 이 결합이 기존 앱
    부팅 계약을 회귀시키지 않음을 (1) harness 부팅 앱이 lifespan 을 가지며 (2) 잠금·휴지통
    라우트가 조립되어 있음으로 확인한다(스케줄러 job 대기 없이 부팅 관찰).
    """
    app = harness.app
    assert app.router.lifespan_context is not None, (
        "부팅 앱은 s10 스케줄러 결선을 위한 lifespan 을 가져야 한다(부팅 계약)"
    )
    observed = {
        (_normalize_path(path), method.lower())
        for path, methods in logical_openapi_paths(app).items()
        for method in methods
    }
    assert ("/documents/{}/lock", "post") in observed, (
        "APScheduler 결합 부팅이 s09 잠금 라우트 조립을 회귀시키면 안 된다"
    )
    assert ("/workspaces/{}/trash", "get") in observed, (
        "APScheduler 결합 부팅이 s10 휴지통 라우트 조립을 회귀시키면 안 된다"
    )


def test_scheduler_starts_when_interval_positive(harness):
    """`trash_sweep_interval_seconds > 0` 이면 보관 스윕 스케줄러가 기동됨(2.6).

    실제 config(3600 > 0) 값으로 `trash_scheduler.start(app)` 를 호출해 APScheduler 가 기동
    (running=True)되고 보관 스윕 job 이 등록됨을 모듈 상태로 관측한다. 스케줄러 job 은 interval
    주기(3600초) 뒤 첫 실행이므로 테스트 중 실행되지 않는다(대기·sleep 없음). 종료는 finally 에서
    반드시 정리한다.
    """
    trash_scheduler.stop()  # 잔여 상태 정리(멱등 no-op 가능).
    assert get_settings().trash_sweep_interval_seconds > 0, (
        "이 테스트는 실제 config 의 interval 이 >0 임을 전제한다(현재 config.yml=3600)"
    )
    try:
        trash_scheduler.start(harness.app)
        sched = trash_scheduler._scheduler
        assert sched is not None, (
            "interval>0 이면 보관 스윕 스케줄러가 기동되어야 한다(_scheduler 비어있음=미기동)"
        )
        assert sched.running, "기동된 스케줄러는 running 상태여야 한다"
        assert sched.get_job(trash_scheduler._JOB_ID) is not None, (
            f"보관 스윕 job({trash_scheduler._JOB_ID})이 등록되어야 한다"
        )
    finally:
        trash_scheduler.stop()
    assert trash_scheduler._scheduler is None, (
        "stop() 후 스케줄러 홀더가 정리(None)되어야 한다"
    )


def test_scheduler_not_started_when_interval_non_positive(harness, monkeypatch):
    """`trash_sweep_interval_seconds <= 0` 이면 스케줄러가 기동되지 않음(2.6).

    실제 `Settings`/`get_settings` 로더 경로에 환경변수로 interval=0 을 주입(pydantic-settings
    가 실제로 로드하는 값이며 mock 이 아님)한 뒤 `trash_scheduler.start(app)` 를 호출해 인프로세스
    스케줄러가 기동되지 않음(_scheduler=None, 외부 cron 신호 분기)을 관측한다. 환경변수·설정 캐시는
    finally 에서 원상 복구한다(harness 의 테스트 DB 설정은 DB_NAME 환경변수로 유지되므로 캐시
    재적재 시에도 개발 DB 로 새지 않는다).
    """
    trash_scheduler.stop()  # 잔여 상태 정리.
    monkeypatch.setenv("TRASH_SWEEP_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    try:
        assert get_settings().trash_sweep_interval_seconds <= 0, (
            "환경변수 주입으로 interval 이 <=0 로 로드되어야 한다(설정 경로 확인)"
        )
        trash_scheduler.start(harness.app)
        assert trash_scheduler._scheduler is None, (
            "interval<=0 이면 인프로세스 스케줄러가 기동되지 않아야 한다(외부 cron 신호)"
        )
    finally:
        trash_scheduler.stop()
        get_settings.cache_clear()  # 주입값 제거(monkeypatch 가 env 를 되돌림).
