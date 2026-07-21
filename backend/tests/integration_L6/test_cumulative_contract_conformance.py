"""누적 전체 계약 대조 스위트 (Task 2.1 / Req 2.1, 2.2, 2.3, 2.4, 2.5, 2.6,
design §CumulativeContractConformanceSuite · §Settings additive 조정 항목 · 계약 대조 판정).

실제 결합된 런타임(마이그레이션 적용 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10⊕s12⊕**s14**) +
실 세션 + 실 파일시스템 저장/보관 루트 + APScheduler 결합 무효화 스케줄러)을
**s01-contract-foundation 단일 소스**와 대조하는 외부 관찰자 스위트다. 대조 기준은 s14 의
design 이 아니라 **항상 s01**(`§Physical Data Model` `share_link` 테이블(`id`·`document_id`·
`token VARCHAR(64) UNIQUE`·`is_enabled BOOLEAN DEFAULT TRUE`·`created_at`) · `§API Endpoint
Catalog` 행 1~37(전체 표면) · `§Errors` 에러 코드 카탈로그·정보 비노출(INV-8) · `§Base Schemas`
`TimestampedRead`·최소 노출 규약 · `§Settings` 스키마)이며, 실제 앱이 s01 계약에서 벗어났다면
단언을 약화시키지 않고 그대로 실패시켜 **어느 계약 요소가 드리프트했는지** 를 assertion 메시지가
지목한다.

이 스위트는 L5 `test_cumulative_contract_conformance.py`(스키마·API·에러·Base·Settings 대조
템플릿)를 공유 표면(행 34~37)·전체 표면(행 1~37)·s14 Settings additive 조정 항목·무효화
스케줄러 APScheduler 결합으로 확장한다. 여섯 개의 단언 그룹(task 2.1):

- **Group 1 — share_link 스키마 vs s01 물리 모델(Req 2.1)**: 마이그레이션된 DB 의
  `information_schema` 로 `share_link` 컬럼(타입 계열·nullability·varchar(64) 길이·`is_enabled`
  DDL 기본값 TRUE)·`token` UNIQUE·`document_id`→document.id FK 를 대조하고, s14 가 새 마이그레이션을
  추가하지 않고 s01 단일 리비전(0001)만 씀을 확인한다.
- **Group 2 — 엔드포인트 카탈로그 전체(행 1~37) 노출·공유 게이트 강제(Req 2.2)**: 부팅 앱 OpenAPI 가
  s01 카탈로그 행 1~37 을 정확한 경로 구조·메서드로 노출(subset)하고, 공유 발급/토글(행 34~35)의
  요구 role 게이트가 런타임에서 실제로 강제됨(미인증 401·viewer 403)·공개 경로(행 36~37)가
  auth-bypass(익명 요청이 401 이 아니라 무효 토큰 404 로 서비스에 도달)임을 대표 요청으로 확인.
- **Group 3 — 에러 모델 vs s01 에러 카탈로그(Req 2.3)**: 401/403/404/409/422 를 실제로 유발해
  상태코드와 `ErrorResponse` 형태(`{code, message, field_errors?}`)·`code` 문자열을 대조하고, 공개
  경로의 모든 무효/부재/범위 밖이 404 로 통일(INV-8 정보 비노출)됨을 확인.
- **Group 4 — Base Schemas 규약·최소 노출·바이너리 응답(Req 2.4)**: `ShareLinkRead` 가 s01
  `TimestampedRead` 를 상속하고 계약 필드를 노출하며, `PublicDocumentNode` 가 내부 필드를 은닉하는
  최소 노출임을, 링크 경유 첨부 응답이 스키마 본문이 아니라 스트리밍(binary)임을 확인.
- **Group 5 — Settings additive 조정 항목(Req 2.5)**: s14 가 additive 로 추가한
  `share_token_bytes`·`share_invalidation_sweep_interval_seconds` 가 존재하는 실제 결합 부팅에서
  `s01` `Settings`/`get_settings` 로딩이 정상 성공하고 기존 필드(s12 첨부 additive 포함)가
  보존되며 설정 접근이 단일 `Settings`/`get_settings` 경유(공유 모듈에 `os.environ` 직접 접근
  부재)임을 확인.
- **Group 6 — 무효화 스케줄러 결합 부팅(design §2.6)**: APScheduler 의존성이 결합된 상태에서
  `create_app()` 이 정상 부팅되고, `share_invalidation_sweep_interval_seconds` `>0` 이면 스케줄러
  기동·`<=0` 이면 미기동되며 이 결합이 기존 앱(공유·첨부·이전) 부팅 계약을 회귀시키지 않음(부팅
  스모크)을 확인한다.

재검증 트리거(design §Revalidation Triggers): `s01`(계약)·`s02`·`s03`·`s05`·`s07`·`s09`·`s10`·
`s12`·`s14` 중 하나라도 수정되면 이 체크포인트를 누적 집합 기준으로 재실행한다(`s01` 수정 시 모든
체크포인트).

`harness`(L1 conftest)·`ws_scenario`(L2 conftest)·`doc_tree_scenario`(L3)·`share_scenario`(L6
conftest)·`tmp_attachment_roots`(L5 conftest) 픽스처가 제공하는 실 결합 환경 위에서만 동작하며
mock/stub/fake 를 쓰지 않는다(스케줄러 직접 기동은 실제 s14 코드 실행). 스케줄러 `<=0` 분기는
환경변수 주입(pydantic-settings 실 로딩)으로 결정적으로 태우며 스택 mock 이 아니다.
"""

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.config import Settings, get_settings
from app.schemas.base import TimestampedRead
from app.sharing import scheduler as share_scheduler
from app.sharing.schemas import (
    PublicDocumentNode,
    PublicDocumentRead,
    ShareLinkRead,
    ShareLinkUpdate,
)
from tests.integration_L6 import helpers

# =============================================================================
# s01 단일 소스 계약 상수 — §Physical Data Model share_link · §API Catalog 1~37 · §Settings
# =============================================================================

# s01 §Physical Data Model — share_link 컬럼 nullability("NO" = NOT NULL). 전 컬럼 NOT NULL.
S01_SHARE_LINK_COLUMNS_NULLABILITY = {
    "id": "NO",
    "document_id": "NO",
    "token": "NO",
    "is_enabled": "NO",
    "created_at": "NO",
}

# s01 share_link 타입 계열: BIGINT→bigint, VARCHAR→varchar, BOOLEAN→tinyint(MySQL),
# DATETIME→datetime.
S01_SHARE_LINK_TYPE_FAMILY = {
    "id": "bigint",
    "document_id": "bigint",
    "token": "varchar",
    "is_enabled": "tinyint",
    "created_at": "datetime",
}

# s01 VARCHAR 길이 계약(token VARCHAR(64)).
S01_SHARE_LINK_VARCHAR_LENGTHS = {
    "token": 64,
}

# s01 share_link FK 계약 — (컬럼, 참조테이블, 참조컬럼).
S01_SHARE_LINK_FOREIGN_KEYS = {
    ("document_id", "document", "id"),
}

# s01 §API Endpoint Catalog 행 1~37 — (정규화 경로, 메서드). 경로는 파라미터 명명(`{id}`)에
# 비의존하도록 `_normalize_path` 로 정규화해 구조로 대조한다(subset — /health 등 부가 라우트 허용).
S01_FULL_API_CATALOG = [
    ("/auth/login", "post"),                          # 1
    ("/auth/logout", "post"),                         # 2
    ("/auth/me", "get"),                              # 3
    ("/auth/password", "post"),                       # 4
    ("/admin/users", "post"),                         # 5
    ("/admin/users", "get"),                          # 6
    ("/admin/users/{}", "patch"),                     # 7
    ("/admin/users/{}/password", "post"),             # 8
    ("/admin/workspaces/{}/owner", "post"),           # 9
    ("/workspaces", "post"),                          # 10
    ("/workspaces", "get"),                           # 11
    ("/workspaces/{}", "get"),                         # 12
    ("/workspaces/{}", "patch"),                       # 13
    ("/workspaces/{}", "delete"),                      # 14
    ("/workspaces/{}/members", "post"),               # 15
    ("/workspaces/{}/members/{}", "patch"),           # 16
    ("/workspaces/{}/members/{}", "delete"),          # 17
    ("/workspaces/{}/documents", "post"),             # 18
    ("/workspaces/{}/documents", "get"),              # 19
    ("/documents/{}", "get"),                          # 20
    ("/documents/{}", "patch"),                        # 21
    ("/documents/{}/move", "post"),                   # 22
    ("/documents/{}", "delete"),                       # 23
    ("/documents/{}/lock", "post"),                   # 24
    ("/documents/{}/save", "post"),                   # 25
    ("/documents/{}/cancel", "post"),                 # 26
    ("/documents/{}/force-unlock", "post"),           # 27
    ("/documents/{}/versions", "get"),                # 28
    ("/workspaces/{}/trash", "get"),                  # 29
    ("/trash/{}/restore", "post"),                    # 30
    ("/trash/{}", "delete"),                           # 31
    ("/documents/{}/attachments", "post"),            # 32
    ("/attachments/{}", "get"),                        # 33
    ("/documents/{}/share", "post"),                  # 34 (editor)
    ("/documents/{}/share", "patch"),                 # 35 (editor)
    ("/public/{}", "get"),                             # 36 (public)
    ("/public/{}/attachments/{}", "get"),             # 37 (public)
]

# s01 §API Catalog 공유 표면(행 34~37) — 게이트 강제·auth-bypass 관측 대상.
S01_SHARE_CATALOG_34_TO_37 = [
    ("/documents/{}/share", "post"),        # 34 editor 게이트
    ("/documents/{}/share", "patch"),       # 35 editor 게이트
    ("/public/{}", "get"),                  # 36 public bypass
    ("/public/{}/attachments/{}", "get"),   # 37 public bypass
]

# s01 §Base Schemas 규약상 ShareLinkRead 가 노출해야 하는 필드(파생 share_url 포함).
# TimestampedRead(id·created_at·updated_at) + document_id·token·is_enabled·share_url.
S01_SHARE_LINK_READ_FIELDS = {
    "id",
    "created_at",
    "updated_at",
    "document_id",
    "token",
    "is_enabled",
    "share_url",
}

# s01 §Base Schemas — PublicDocumentNode 최소 노출 필드(내부 필드 은닉 대조).
S01_PUBLIC_NODE_FIELDS = {"id", "title", "content_html", "children"}

# PublicDocumentNode 가 **노출하지 않아야** 하는 내부 필드(최소 노출 판정).
S01_PUBLIC_NODE_FORBIDDEN_FIELDS = {
    "workspace_id",
    "created_by",
    "status",
    "parent_id",
    "sort_order",
}

# s14 가 additive 로 추가한 Settings 필드(존재해야 함, s01 계약을 비파괴적으로 확장).
S01_SETTINGS_SHARE_ADDITIVE_FIELDS = {
    "share_token_bytes",
    "share_invalidation_sweep_interval_seconds",
}

# s01 §Settings 스키마 — additive 확장 이후에도 보존되어야 하는 기존 필드(L5 집합 + s12 첨부 additive).
S01_SETTINGS_PRESERVED_FIELDS = {
    "app_name",
    "db_host",
    "db_port",
    "db_name",
    "db_user",
    "default_trash_retention_days",
    "trash_sweep_interval_seconds",
    "file_storage_root",
    "session_cookie_name",
    "session_max_age_seconds",
    "db_password",
    "session_secret",
    # s12 첨부 additive(이미 보존 대상)
    "attachment_archive_root",
    "attachment_sweep_interval_seconds",
    "attachment_max_bytes",
}

# 인증되었으나 대상이 존재하지 않을 때 어댑터 404 를 관측하기 위한 미존재 id.
MISSING_DOCUMENT_ID = 999_999_999

# 공개 경로 404 통일(INV-8)을 관측하기 위한 무효 토큰(어떤 링크로도 해석되지 않음).
BOGUS_TOKEN = "bogus-token-does-not-resolve-000000000000"


from tests.support import logical_openapi_paths


def _normalize_path(path: str) -> str:
    """경로의 `{param}` 세그먼트를 `{}` 로 정규화한다(파라미터 명명 비의존 구조 대조).

    s01 카탈로그와 s14 라우트는 경로 파라미터 식별자(`{id}`·`{token}`·`{aid}`)를 다르게 적을 수
    있으나 계약 요소는 **경로 구조(세그먼트 배열 + 파라미터 위치) + 메서드** 이므로 양쪽을 동일
    규칙으로 정규화해 대조한다.
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


def _observed_routes(harness) -> set[tuple[str, str]]:
    """부팅 앱 OpenAPI 의 (정규화 경로, 메서드) 집합을 만든다(구조 대조용)."""
    paths = logical_openapi_paths(harness.app)
    return {
        (_normalize_path(path), method.lower())
        for path, methods in paths.items()
        for method in methods
    }


# =============================================================================
# Group 1 — share_link 스키마 vs s01 물리 모델 (Req 2.1)
# =============================================================================


def test_share_link_columns_match_s01_physical_model(harness):
    """마이그레이션된 share_link 테이블의 컬럼·nullability·타입 계열·varchar 길이가 s01 과 일치(2.1).

    `information_schema.columns` 를 조회해 s01 이 정한 컬럼 집합(id·document_id·token·is_enabled·
    created_at)이 정확히 존재하고, 각 nullability(전 컬럼 NOT NULL)·타입 계열·VARCHAR 길이
    (token 64)가 s01 과 일치함을 대조한다. s14 가 공유 스키마 형태를 드리프트시켰다면 어떤 컬럼이
    어긋났는지 메시지에 명시한다. `share_link` 에는 `updated_at` 컬럼이 없음(s01)도 초과 컬럼 부재로
    확인한다.
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT column_name, is_nullable, data_type, character_maximum_length "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'share_link'"
            )
        ).all()
    assert rows, "마이그레이션된 DB 에 share_link 테이블 컬럼이 존재해야 한다(스키마 미적용?)"

    observed = {row[0]: (row[1].upper(), row[2].lower(), row[3]) for row in rows}

    expected_cols = set(S01_SHARE_LINK_COLUMNS_NULLABILITY)
    observed_cols = set(observed)
    missing = expected_cols - observed_cols
    extra = observed_cols - expected_cols
    assert not missing, f"share_link 테이블에 s01 계약 컬럼 누락: {sorted(missing)}"
    assert not extra, (
        f"share_link 테이블에 s01 계약 밖 컬럼 초과(updated_at 등 없어야 함): {sorted(extra)}"
    )

    for col, expected_nullable in S01_SHARE_LINK_COLUMNS_NULLABILITY.items():
        observed_nullable = observed[col][0]
        assert observed_nullable == expected_nullable, (
            f"share_link.{col} nullability 드리프트: s01={expected_nullable} "
            f"관측={observed_nullable}"
        )

    for col, expected_family in S01_SHARE_LINK_TYPE_FAMILY.items():
        observed_family = observed[col][1]
        assert observed_family == expected_family, (
            f"share_link.{col} 타입 계열 드리프트: s01={expected_family} "
            f"관측={observed_family}"
        )

    for col, expected_len in S01_SHARE_LINK_VARCHAR_LENGTHS.items():
        observed_len = observed[col][2]
        assert observed_len == expected_len, (
            f"share_link.{col} VARCHAR 길이 드리프트: s01={expected_len} "
            f"관측={observed_len}"
        )


def test_share_link_is_enabled_default_true_matches_s01(harness):
    """share_link.is_enabled DDL 기본값 TRUE(=1)가 s01 물리 모델과 일치(2.1).

    `is_enabled BOOLEAN NOT NULL DEFAULT TRUE` 는 MySQL 에서 tinyint(1)+column_default '1' 로
    실체화된다(1 이 TRUE). `information_schema.columns.column_default` 로 대조한다(발급 링크가
    기본 활성 상태로 생성됨의 스키마 근거).
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT column_name, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'share_link' "
                "AND column_name = 'is_enabled'"
            )
        ).all()
    assert rows, "share_link 에 is_enabled 컬럼이 존재해야 한다"
    observed_default = rows[0][1]
    normalized_default = (
        str(observed_default).strip("'\"") if observed_default is not None else None
    )
    assert normalized_default == "1", (
        f"share_link.is_enabled DDL 기본값 드리프트: s01=TRUE(1) "
        f"관측={observed_default!r} (발급 링크 기본 활성)"
    )


def test_share_link_token_is_unique_matches_s01(harness):
    """share_link.token 에 UNIQUE 제약이 존재(s01, 2.1).

    s01 이 정한 `token VARCHAR(64) UNIQUE`(공개 토큰의 전역 유일성)를 `information_schema.
    statistics` 의 non_unique=0 인덱스가 `token` 단일 컬럼을 덮는지로 대조한다(재발급/retire 가
    토큰을 교체해도 유일성이 스키마로 강제됨의 근거).
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT index_name, seq_in_index, column_name, non_unique "
                "FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = 'share_link'"
            )
        ).all()
    assert rows, "share_link 에 인덱스가 존재해야 한다"

    grouped: dict[str, dict] = {}
    for index_name, seq_in_index, column_name, non_unique in rows:
        entry = grouped.setdefault(index_name, {"cols": [], "unique": int(non_unique) == 0})
        entry["cols"].append((int(seq_in_index), column_name))
    unique_layouts = [
        [c for _, c in sorted(e["cols"])] for e in grouped.values() if e["unique"]
    ]
    assert ["token"] in unique_layouts, (
        f"share_link.token 에 UNIQUE 제약(단일 컬럼)이 있어야 한다(s01): "
        f"관측 UNIQUE 인덱스 레이아웃={unique_layouts}"
    )


def test_share_link_foreign_keys_match_s01(harness):
    """share_link 의 FK(document_id→document.id)가 s01 물리 모델과 일치(2.1).

    `information_schema.key_column_usage` 에서 참조 테이블이 있는 행을 조회해 s01 이 정한 FK
    (`document_id`→document.id, 문서 단위 공유의 문서 연결)가 존재함을 대조한다.
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT column_name, referenced_table_name, referenced_column_name "
                "FROM information_schema.key_column_usage "
                "WHERE table_schema = DATABASE() AND table_name = 'share_link' "
                "AND referenced_table_name IS NOT NULL"
            )
        ).all()
    observed_fks = {(row[0], row[1], row[2]) for row in rows}
    missing = S01_SHARE_LINK_FOREIGN_KEYS - observed_fks
    assert not missing, (
        f"share_link FK 드리프트: s01 계약 FK 누락={sorted(missing)} "
        f"관측 FK={sorted(observed_fks)}"
    )


def test_s14_adds_no_new_migration_over_s01_initial_schema():
    """s14 가 새 마이그레이션 없이 s01 단일 리비전(0001)만으로 동작함을 확인(2.1).

    (1) `migrations/versions/` 에 리비전 파일이 정확히 하나(`0001_initial_schema.py`)이고,
    (2) alembic head 가 단일 `0001` 리비전이며 그 down_revision 이 None(base)임을 확인한다.
    s14(문서 단위 공유 링크)는 share_link 테이블을 포함한 s01 단일 리비전 위에서 동작하며 스키마
    형태를 신설하지 않는다(Settings 만 additive 확장, DB 마이그레이션 무추가).
    """
    backend_dir = Path(__file__).resolve().parents[2]  # integration_L6 -> tests -> backend
    versions_dir = backend_dir / "migrations" / "versions"

    revision_files = sorted(
        p.name for p in versions_dir.glob("*.py") if p.name != "__init__.py"
    )
    # s01 baseline(0001) + additive user_setting(0002·0003) + s26 role 2단계화(0004).
    # s14 가 자기 마이그레이션을 추가하지 않았음을 검증하는 것이 목적이므로 이후 spec 의
    # 정당한 마이그레이션(user_setting additive·s26 open-access-roles)은 허용한다.
    assert revision_files == [
        "0001_initial_schema.py",
        "0002_user_setting.py",
        "0003_user_setting_last_selected_workspace.py",
        "0004_open_access_roles.py",
    ], (
        "s14 는 새 마이그레이션을 추가하지 않고 s01 baseline + additive user_setting + s26 role 이관 위에서 동작해야 "
        f"한다(2.1): 관측 리비전 파일={revision_files}"
    )

    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))
    script = ScriptDirectory.from_config(cfg)

    # head 는 s26 role 이관(0004)까지 전진했으나 여전히 단일 선형 체인이다.
    heads = list(script.get_heads())
    assert heads == ["0004"], f"alembic head 는 단일 선형 체인의 0004 여야 한다: {heads}"

    # baseline 0001 은 여전히 최초 리비전(down_revision None)이다.
    rev = script.get_revision("0001")
    assert rev.down_revision is None, (
        f"0001 은 base 리비전이어야 한다(down_revision None): {rev.down_revision!r}"
    )


# =============================================================================
# Group 2 — 엔드포인트 카탈로그 전체(행 1~37) 노출·공유 게이트 강제 (Req 2.2)
# =============================================================================


def test_openapi_exposes_full_catalog_rows_1_to_37(harness):
    """부팅 앱 OpenAPI 가 s01 카탈로그 행 1~37 전체를 정확한 경로 구조·메서드로 노출(subset, 2.2).

    s01 §API Endpoint Catalog 의 37개 (경로, 메서드) 쌍이 모두 부팅 앱 OpenAPI 에 존재함을 확인한다
    (/health 등 부가 라우트는 허용하는 subset 대조). 경로 파라미터 명명은 계약 요소가 아니므로
    `_normalize_path` 로 정규화해 구조로 대조한다. s01⊕...⊕s14 누적 조립이 이전 spec 의 어느
    표면도 회귀시키지 않고 공유 표면(34~37)까지 완비했음을 한 지점에서 보증한다.
    """
    observed = _observed_routes(harness)
    missing = [pair for pair in S01_FULL_API_CATALOG if pair not in observed]
    assert not missing, (
        f"s01 카탈로그 행 1~37 중 앱 OpenAPI 에 미노출된 (경로, 메서드)={missing} "
        f"(누적 조립 표면 드리프트)"
    )


def test_sharing_issue_route_unauthenticated_returns_401(harness):
    """공유 발급 라우트(행 34)를 세션 없이 호출하면 401(요구 role 게이트 이전 인증 게이트 강제, 2.2).

    미인증 요청은 요구 role(editor)·문서 존재(404) 판정 이전에 `get_current_user` 가 401 을
    산출한다(공유 발급은 공개 경로가 아니라 인증 게이트가 앞선다).
    """
    resp = helpers.attempt_issue_share(harness.new_client(), MISSING_DOCUMENT_ID)
    assert resp.status_code == 401, (
        f"미인증 POST /documents/{{id}}/share 은 401 이어야 한다(인증 게이트): "
        f"{resp.status_code} {resp.text}"
    )


def test_sharing_issue_route_viewer_returns_403(share_scenario):
    """viewer 가 공유 발급 라우트(행 34)를 호출하면 403(요구 role editor 게이트 강제, 2.2).

    카탈로그 행 34(발급)의 요구 role 이 실제로 editor 게이트로 걸려 있는지 — viewer(멤버지만 editor
    미만)의 발급 요청이 런타임에서 거부됨(403)으로 확인한다. 게이트 on·실존 active 문서 위에서
    role 게이트가 발급 이전에 걸림을 관측한다.
    """
    resp = helpers.attempt_issue_share(
        share_scenario.viewer_client, share_scenario.document_id
    )
    assert resp.status_code == 403, (
        f"viewer 의 공유 발급은 editor 게이트에서 403 이어야 한다(요구 role 강제): "
        f"{resp.status_code} {resp.text}"
    )


def test_public_render_route_is_auth_bypass_not_401(harness):
    """공개 렌더 라우트(행 36)는 auth-bypass — 익명 요청이 401 이 아니라 404 로 서비스에 도달(2.2).

    행 36 은 인증·권한 게이트가 없다(공개). 익명 클라이언트로 무효 토큰을 렌더 요청하면 인증
    게이트에 막혀 401 이 나는 게 아니라, 게이트 없이 서비스에 도달해 무효 토큰이 404 로 통일됨을
    관측한다(공개 라우트에 auth 게이트가 없다는 증거).
    """
    resp = helpers.attempt_public_render(harness.new_client(), BOGUS_TOKEN)
    assert resp.status_code != 401, (
        f"공개 렌더는 auth-bypass 라 401 이 아니어야 한다(공개 게이트 없음): "
        f"{resp.status_code} {resp.text}"
    )
    assert resp.status_code == 404, (
        f"무효 토큰 공개 렌더는 404 로 통일되어야 한다(서비스 도달): {resp.status_code} {resp.text}"
    )


def test_public_attachment_route_is_auth_bypass_not_401(harness):
    """링크 경유 첨부 라우트(행 37)는 auth-bypass — 익명 요청이 401 이 아니라 404 로 서비스에 도달(2.2)."""
    resp = helpers.attempt_public_attachment(harness.new_client(), BOGUS_TOKEN, 1)
    assert resp.status_code != 401, (
        f"링크 경유 첨부 서빙은 auth-bypass 라 401 이 아니어야 한다(공개 게이트 없음): "
        f"{resp.status_code} {resp.text}"
    )
    assert resp.status_code == 404, (
        f"무효 토큰 링크 경유 첨부는 404 로 통일되어야 한다(서비스 도달): "
        f"{resp.status_code} {resp.text}"
    )


# =============================================================================
# Group 3 — 에러 모델 vs s01 에러 카탈로그 (Req 2.3)
# =============================================================================


def test_error_401_unauthenticated_issue_share(harness):
    """미인증 공유 발급 요청 → 401 + code=unauthenticated + ErrorResponse 형태(2.3)."""
    resp = helpers.attempt_issue_share(harness.new_client(), MISSING_DOCUMENT_ID)
    assert resp.status_code == 401, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "unauthenticated", (
        f"401 은 s01 에러 카탈로그상 code=unauthenticated 여야 한다: {body!r}"
    )


def test_error_403_forbidden_viewer_issue_share(share_scenario):
    """viewer 의 공유 발급 거부 → 403 + code=forbidden + ErrorResponse 형태(2.3)."""
    resp = helpers.attempt_issue_share(
        share_scenario.viewer_client, share_scenario.document_id
    )
    assert resp.status_code == 403, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "forbidden", (
        f"403 은 s01 에러 카탈로그상 code=forbidden 여야 한다: {body!r}"
    )


def test_error_404_missing_document_issue_share(share_scenario):
    """게이트를 통과하는 editor 로 미존재 문서 공유 발급 → 404 + code=not_found(문서→WS 어댑터, 2.3).

    비멤버는 resolver 가 role None 을 반환해 403 으로 막히므로, 문서→WS 어댑터가 매핑 실패로 404 를
    내는 경로를 관측하려면 게이트를 통과하는 인증 멤버(editor)로 호출한다. 문서 부재는 서비스 진입
    이전 어댑터에서 404 로 거부된다.
    """
    resp = helpers.attempt_issue_share(
        share_scenario.editor_client, MISSING_DOCUMENT_ID
    )
    assert resp.status_code == 404, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "not_found", (
        f"404 는 s01 에러 카탈로그상 code=not_found 여야 한다: {body!r}"
    )


def test_error_409_conflict_issue_share_gate_off(doc_tree_scenario):
    """게이트 off 워크스페이스의 active 문서 공유 발급 → 409 + code=conflict(2.3).

    `doc_tree_scenario` 워크스페이스는 `is_shareable` 기본 false(s01 기본)이므로 게이트를 열지
    않고 editor 가 active 루트 문서에 발급을 시도하면 서비스가 게이트 off 관측으로 409(conflict)로
    거부한다(발급 게이트 강제). 게이트가 s05 소유임을 재확인하는 상태 기반 거부 경로다.
    """
    resp = helpers.attempt_issue_share(
        doc_tree_scenario.editor_client, doc_tree_scenario.root_id
    )
    assert resp.status_code == 409, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "conflict", (
        f"게이트 off 발급은 s01 에러 카탈로그상 code=conflict(409)여야 한다: {body!r}"
    )


def test_error_409_conflict_activate_toggle_gate_off(share_scenario):
    """게이트를 닫은 뒤 비활성 링크를 활성화(PATCH is_enabled=true) → 409 + code=conflict(2.3).

    share_scenario(게이트 on·활성 링크)에서 (1) editor 가 링크를 비활성화(항상 허용, 200), (2) owner
    가 게이트를 닫고(set_gate off = s05 설정 라우트), (3) editor 가 재활성화를 시도하면 서비스가
    게이트 off 관측으로 409(conflict)로 거부함을 관측한다(활성화만이 재발급 통일의 상태 기반 예외).
    비활성화는 게이트와 무관하게 항상 허용됨도 함께 확인한다.
    """
    doc_id = share_scenario.document_id
    editor = share_scenario.editor_client

    # (1) 비활성화 — 게이트·status 무관 항상 허용(토큰 유지).
    disabled = helpers.toggle_share(editor, doc_id, is_enabled=False)
    assert disabled["is_enabled"] is False

    # (2) 게이트 닫기 — owner 경로 s05 설정 라우트 재사용.
    helpers.set_gate(
        share_scenario.owner_client, share_scenario.workspace_id, is_shareable=False
    )

    # (3) 재활성화 시도 — 게이트 off → 409 conflict.
    resp = helpers.attempt_toggle_share(editor, doc_id, is_enabled=True)
    assert resp.status_code == 409, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "conflict", (
        f"게이트 off 재활성화는 s01 에러 카탈로그상 code=conflict(409)여야 한다: {body!r}"
    )


def test_error_422_invalid_toggle_body(share_scenario):
    """게이트를 통과하는 editor 로 잘못된 토글 바디(is_enabled 누락) → 422 + code=validation_error(2.3).

    editor 가 실존 문서에 `PATCH /documents/{id}/share` 를 `is_enabled` 누락 바디로 호출하면 요청
    검증 실패(RequestValidationError)로 422 가 나며, s01 §Errors 상 **요청 검증 실패**는
    `code=validation_error`(도메인 규칙 위반 `unprocessable` 과 구분)로 직렬화되고 `field_errors`
    가 채워진다. 게이트 통과 editor·실존 문서 위에서 유발해 바디 검증에 도달함을 보장한다.
    """
    resp = share_scenario.editor_client.patch(
        f"/documents/{share_scenario.document_id}/share", json={}
    )
    assert resp.status_code == 422, (
        f"잘못된 토글 바디는 422 여야 한다: {resp.status_code} {resp.text}"
    )
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "validation_error", (
        f"요청 검증 실패는 s01 에러 카탈로그상 code=validation_error(422)여야 한다: {body!r}"
    )
    assert body.get("field_errors"), (
        f"요청 검증 422 는 field_errors 를 채워야 한다(누락 필드 지목): {body!r}"
    )


def test_public_404_unification_render_and_attachment(harness):
    """공개 경로의 무효/부재/범위 밖은 모두 404 로 통일(INV-8 정보 비노출, 2.3).

    익명 클라이언트로 (1) 무효 토큰 공개 렌더 `GET /public/{bogus}` → 404, (2) 무효 토큰 링크 경유
    첨부 `GET /public/{bogus}/attachments/1` → 404 임을 확인한다. 401/403 유출 없이 모두 404 +
    code=not_found 로 통일되어 링크·문서·첨부의 존재 추정을 차단함을 관측한다(INV-8).
    """
    render_resp = helpers.attempt_public_render(harness.new_client(), BOGUS_TOKEN)
    assert render_resp.status_code == 404, (
        f"무효 토큰 공개 렌더는 404 로 통일되어야 한다(401/403 유출 금지): "
        f"{render_resp.status_code} {render_resp.text}"
    )
    render_body = render_resp.json()
    _assert_error_response_shape(render_body)
    assert render_body["code"] == "not_found", (
        f"공개 렌더 404 통일은 code=not_found 여야 한다(INV-8): {render_body!r}"
    )

    att_resp = helpers.attempt_public_attachment(harness.new_client(), BOGUS_TOKEN, 1)
    assert att_resp.status_code == 404, (
        f"무효 토큰 링크 경유 첨부는 404 로 통일되어야 한다(401/403 유출 금지): "
        f"{att_resp.status_code} {att_resp.text}"
    )
    att_body = att_resp.json()
    _assert_error_response_shape(att_body)
    assert att_body["code"] == "not_found", (
        f"링크 경유 첨부 404 통일은 code=not_found 여야 한다(INV-8): {att_body!r}"
    )


# =============================================================================
# Group 4 — Base Schemas 규약·최소 노출·바이너리 응답 (Req 2.4)
# =============================================================================


def test_share_link_read_inherits_s01_base_and_exposes_contract_fields():
    """ShareLinkRead 가 s01 TimestampedRead 를 상속하고 계약 필드를 노출(2.4).

    s14 발급/토글 응답 Read 스키마가 s01 공통 타임스탬프 Read 베이스(`TimestampedRead`,
    from_attributes)를 상속하고, s01 계약 필드(id·created_at·updated_at + document_id·token·
    is_enabled + 파생 share_url)를 **정확히** 노출함을 클래스 수준에서 확인한다.
    """
    assert issubclass(ShareLinkRead, TimestampedRead), (
        "ShareLinkRead 는 s01 TimestampedRead 를 상속해야 한다(Base Schemas 드리프트)"
    )
    fields = set(ShareLinkRead.model_fields)
    assert fields == S01_SHARE_LINK_READ_FIELDS, (
        f"ShareLinkRead 필드 드리프트: s01 계약 필드={sorted(S01_SHARE_LINK_READ_FIELDS)} "
        f"관측={sorted(fields)} (share_url 파생 필드 포함, updated_at 상속 필드 포함)"
    )


def test_share_link_update_is_toggle_only_contract():
    """ShareLinkUpdate 가 토글 전용 규약(`is_enabled` 만)임을 확인(2.4).

    토글 요청 스키마는 `is_enabled` 상태만 담는다(토큰·기타 필드는 서비스 소관, 요청 바디에 없음).
    재발급 통일 원칙(INV-8)의 유일한 상태 기반 예외 요청이 최소 바디임을 확인한다.
    """
    fields = set(ShareLinkUpdate.model_fields)
    assert fields == {"is_enabled"}, (
        f"ShareLinkUpdate 는 is_enabled 만 담아야 한다(토글 전용): 관측 필드={sorted(fields)}"
    )


def test_public_document_schemas_minimal_exposure():
    """PublicDocumentNode/PublicDocumentRead 가 s01 최소 노출 규약과 일치(2.4).

    공개 렌더 노드는 id·title·content_html·children 만 노출하고 내부 필드(workspace_id·created_by·
    status·parent_id·sort_order)를 **노출하지 않음**을, 공개 응답 루트는 root 만 담음을 클래스
    수준에서 확인한다(읽기 전용 최소 노출로 내부 상태 은닉, INV-8 정보 비노출 계약의 스키마 근거).
    """
    node_fields = set(PublicDocumentNode.model_fields)
    assert node_fields == S01_PUBLIC_NODE_FIELDS, (
        f"PublicDocumentNode 필드 드리프트: s01 최소 노출={sorted(S01_PUBLIC_NODE_FIELDS)} "
        f"관측={sorted(node_fields)}"
    )
    leaked = S01_PUBLIC_NODE_FORBIDDEN_FIELDS & node_fields
    assert not leaked, (
        f"PublicDocumentNode 가 내부 필드를 노출하면 안 된다(최소 노출 위반): 유출={sorted(leaked)}"
    )
    read_fields = set(PublicDocumentRead.model_fields)
    assert read_fields == {"root"}, (
        f"PublicDocumentRead 는 root 만 담아야 한다: 관측 필드={sorted(read_fields)}"
    )


def test_public_attachment_response_is_binary_stream_not_json_schema(
    share_scenario, tmp_attachment_roots
):
    """링크 경유 첨부 응답이 스키마 본문이 아니라 스트리밍(binary)이고 원본 바이트열과 일치(2.4).

    editor 가 공유 문서(게이트 on·active 링크)에 실제 이미지를 업로드(tmp 저장 루트)한 뒤 익명 공개
    클라이언트가 링크 경유로 첨부를 조회하면, 응답 content-type 이 `application/json` 이 아니고
    (스키마 직렬화가 아니라 바이너리 스트림), 본문이 업로드한 원본 바이트열과 정확히 일치함을
    확인한다(링크 경유 파일 응답은 JSON 스키마 본문이 아님).
    """
    payload = b"\x89PNG\r\n\x1a\n-l6-public-binary-payload"
    att = helpers.l5_helpers.upload_image(
        share_scenario.editor_client, share_scenario.document_id, content=payload
    )
    resp = helpers.attempt_public_attachment(
        share_scenario.public_client, share_scenario.token, att["id"]
    )
    assert resp.status_code == 200, (
        f"공유 문서 범위 내 미보관 첨부는 링크 경유로 200 이어야 한다: "
        f"{resp.status_code} {resp.text}"
    )
    content_type = resp.headers.get("content-type", "")
    assert not content_type.startswith("application/json"), (
        f"링크 경유 첨부는 스키마 JSON 본문이 아니라 바이너리 스트림이어야 한다: "
        f"content-type={content_type!r}"
    )
    assert resp.content == payload, (
        f"링크 경유 첨부 본문은 업로드한 원본 바이트열과 일치해야 한다(스트리밍 바이너리): "
        f"기대={payload!r} 관측 길이={len(resp.content)}"
    )


# =============================================================================
# Group 5 — Settings additive 조정 항목 (Req 2.5)
# =============================================================================


def test_settings_additive_share_fields_present_and_existing_preserved(harness):
    """additive `share_*` 존재·기존 필드(s12 첨부 포함) 보존·로딩 정상 성공(2.5).

    실제 결합 부팅(harness 가 이미 `create_app()` 부팅)에서 `get_settings()` 로딩이 정상 성공하고,
    s14 가 additive 로 추가한 `share_token_bytes`·`share_invalidation_sweep_interval_seconds` 가
    `Settings` 스키마에 존재하며, 기존 s01 필드(및 s12 첨부 additive)가 모두 보존되고 유효한 값으로
    로드됨을 확인한다. additive 확장이 s01 Settings 계약을 깨지 않았음을 지목한다.
    """
    fields = set(Settings.model_fields)
    missing_additive = S01_SETTINGS_SHARE_ADDITIVE_FIELDS - fields
    assert not missing_additive, (
        f"s14 additive 필드가 Settings 스키마에 있어야 한다: 누락={sorted(missing_additive)} "
        f"관측 필드={sorted(fields)}"
    )
    missing_preserved = S01_SETTINGS_PRESERVED_FIELDS - fields
    assert not missing_preserved, (
        f"additive 확장으로 기존 Settings 필드(s01·s12)가 소실되면 안 된다(계약 파손): "
        f"누락={sorted(missing_preserved)}"
    )

    settings = get_settings()  # 실 결합 부팅 설정 로딩(부팅 실패 없이 성공해야 함).
    assert isinstance(settings.share_token_bytes, int) and settings.share_token_bytes > 0, (
        f"share_token_bytes 는 유효한 양수 int 여야 한다: {settings.share_token_bytes!r}"
    )
    assert isinstance(settings.share_invalidation_sweep_interval_seconds, int), (
        f"share_invalidation_sweep_interval_seconds 는 int 로 로드되어야 한다: "
        f"{settings.share_invalidation_sweep_interval_seconds!r}"
    )
    # 기존 필드(s01·s12)가 유효한 값으로 보존됨(대표 표본).
    assert isinstance(settings.file_storage_root, str) and settings.file_storage_root
    assert isinstance(settings.attachment_max_bytes, int) and settings.attachment_max_bytes > 0
    assert isinstance(settings.default_trash_retention_days, int)
    assert settings.default_trash_retention_days > 0
    assert settings.db_name and isinstance(settings.db_name, str)


def test_settings_single_accessor_is_cached(harness):
    """설정 접근이 단일 `get_settings` 접근자 경유(캐시된 동일 인스턴스)임을 확인(2.5).

    `get_settings()` 를 두 번 호출하면 lru_cache 로 **동일 인스턴스**가 반환됨을 확인해 설정 접근이
    모듈별 개별 로더가 아니라 단일 접근자를 통함을 관측한다.
    """
    assert get_settings() is get_settings(), (
        "설정 접근은 단일 `get_settings` 캐시 접근자를 경유해야 한다(동일 인스턴스)"
    )


def test_sharing_modules_have_no_direct_env_access():
    """공유 모듈(app/sharing)에 `os.environ`·`os.getenv` 직접 접근이 없음을 확인(2.5).

    s01 단일화 원칙(설정은 단일 `Settings`/`get_settings` 경유)에 따라 s14 공유 모듈에
    `os.environ[`·`os.environ.get(`·`os.getenv(` 같은 직접 환경변수 접근이 없어야 한다(모듈별
    설정 파일·직접 접근 부재). 실제 접근 패턴만 정규식으로 판정한다(docstring 문구 오탐 회피).
    """
    sharing_dir = Path(__file__).resolve().parents[2] / "app" / "sharing"
    pattern = re.compile(r"os\.environ\[|os\.environ\.get\(|os\.getenv\(")
    offenders: list[str] = []
    for py in sharing_dir.rglob("*.py"):
        if pattern.search(py.read_text(encoding="utf-8")):
            offenders.append(str(py))
    assert not offenders, (
        f"공유 설정 경로에 직접 환경변수 접근이 없어야 한다(단일 Settings 경유): {offenders}"
    )


# =============================================================================
# Group 6 — 무효화 스케줄러 APScheduler 결합 부팅 (design §2.6)
# =============================================================================


def test_create_app_boots_cleanly_with_invalidation_scheduler_wired(harness):
    """APScheduler 무효화 스케줄러 결합 상태에서 `create_app()` 이 정상 부팅됨(부팅 스모크, 2.6).

    부팅 앱은 lifespan 에 s14 무효화 스윕 스케줄러(APScheduler)를 결선한다. 이 결합이 기존 앱 부팅
    계약을 회귀시키지 않음을 (1) harness 부팅 앱이 lifespan 을 가지며 (2) 공유 라우트(34~37)와
    첨부 라우트(32~33)가 모두 조립되어 있음으로 확인한다(스케줄러 job 대기 없이 부팅 관찰).
    """
    app = harness.app
    assert app.router.lifespan_context is not None, (
        "부팅 앱은 s14 무효화 스케줄러 결선을 위한 lifespan 을 가져야 한다(부팅 계약)"
    )
    observed = _observed_routes(harness)
    for pair in S01_SHARE_CATALOG_34_TO_37:
        assert pair in observed, (
            f"APScheduler 결합 부팅이 s14 공유 라우트 {pair} 조립을 회귀시키면 안 된다"
        )
    # 이전 spec(s12 첨부) 표면 무회귀도 함께 확인.
    assert ("/documents/{}/attachments", "post") in observed, (
        "무효화 스케줄러 결합 부팅이 s12 첨부 업로드 라우트를 회귀시키면 안 된다"
    )
    assert ("/attachments/{}", "get") in observed, (
        "무효화 스케줄러 결합 부팅이 s12 첨부 서빙 라우트를 회귀시키면 안 된다"
    )


def test_invalidation_scheduler_starts_when_interval_positive(harness):
    """`share_invalidation_sweep_interval_seconds > 0` 이면 무효화 스윕 스케줄러가 기동됨(2.6).

    실제 config(3600 > 0) 값으로 `share_scheduler.start(app)` 를 호출해 APScheduler 가 기동
    (running=True)되고 무효화 스윕 job 이 등록됨을 모듈 상태로 관측한다. 스케줄러 job 은 interval
    주기(3600초) 뒤 첫 실행이므로 테스트 중 실행되지 않는다(대기·sleep 없음). 종료는 finally 에서
    반드시 정리한다(background thread 누수 방지).
    """
    share_scheduler.stop()  # 잔여 상태 정리(멱등 no-op 가능).
    assert get_settings().share_invalidation_sweep_interval_seconds > 0, (
        "이 테스트는 실제 config 의 interval 이 >0 임을 전제한다(현재 config.yml=3600)"
    )
    try:
        share_scheduler.start(harness.app)
        sched = share_scheduler._scheduler
        assert sched is not None, (
            "interval>0 이면 무효화 스윕 스케줄러가 기동되어야 한다(_scheduler 비어있음=미기동)"
        )
        assert sched.running, "기동된 스케줄러는 running 상태여야 한다"
        assert sched.get_job(share_scheduler._JOB_ID) is not None, (
            f"무효화 스윕 job({share_scheduler._JOB_ID})이 등록되어야 한다"
        )
    finally:
        share_scheduler.stop()
    assert share_scheduler._scheduler is None, (
        "stop() 후 스케줄러 홀더가 정리(None)되어야 한다"
    )


def test_invalidation_scheduler_not_started_when_interval_non_positive(harness, monkeypatch):
    """`share_invalidation_sweep_interval_seconds <= 0` 이면 스케줄러가 기동되지 않음(2.6).

    실제 `Settings`/`get_settings` 로더 경로에 환경변수로 interval=0 을 주입(pydantic-settings 가
    실제로 로드하는 값이며 mock 이 아님)한 뒤 `share_scheduler.start(app)` 를 호출해 인프로세스
    스케줄러가 기동되지 않음(_scheduler=None, 외부 cron 신호 분기)을 관측한다. 환경변수·설정 캐시는
    finally 에서 원상 복구한다(harness 의 테스트 DB 설정은 DB_NAME 환경변수로 유지되므로 캐시
    재적재 시에도 개발 DB 로 새지 않는다).
    """
    share_scheduler.stop()  # 잔여 상태 정리.
    monkeypatch.setenv("SHARE_INVALIDATION_SWEEP_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    try:
        assert get_settings().share_invalidation_sweep_interval_seconds <= 0, (
            "환경변수 주입으로 interval 이 <=0 로 로드되어야 한다(설정 경로 확인)"
        )
        share_scheduler.start(harness.app)
        assert share_scheduler._scheduler is None, (
            "interval<=0 이면 인프로세스 스케줄러가 기동되지 않아야 한다(외부 cron 신호)"
        )
    finally:
        share_scheduler.stop()
        get_settings.cache_clear()  # 주입값 제거(monkeypatch 가 env 를 되돌림).
