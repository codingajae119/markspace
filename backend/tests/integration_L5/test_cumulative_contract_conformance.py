"""누적 계약 대조 스위트 (Task 2.1 / Req 2.1, 2.2, 2.3, 2.4, 2.5, 2.6,
design §CumulativeContractConformanceSuite · §Settings additive 조정 항목 · 계약 대조 판정).

실제 결합된 런타임(마이그레이션 적용 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10⊕**s12**) +
실 세션 + 실 파일시스템 저장/보관 루트 + APScheduler 결합 아카이브 스케줄러)을
**s01-contract-foundation 단일 소스**와 대조하는 외부 관찰자 스위트다. 대조 기준은 s12 의
design 이 아니라 **항상 s01**(`design.md` §Physical Data Model `attachment` 테이블(`workspace_id`·
`document_id`·`file_path`·`original_name`·`kind ENUM('image','file')`·`is_archived`·인덱스
`(workspace_id, is_archived)`·`(document_id)`) · §API Endpoint Catalog 행 32~33 · §Errors 에러
코드 카탈로그 · §Base Schemas `ORMReadModel`·`Page` · §Settings 스키마(`file_storage_root`))이며,
실제 앱이 s01 계약에서 벗어났다면 단언을 약화시키지 않고 그대로 실패시켜 **어느 계약 요소가
드리프트했는지** 를 assertion 메시지가 지목한다.

이 스위트는 L4 `test_cumulative_contract_conformance.py`(스키마·API·에러·Base·Settings 대조
템플릿)를 첨부 표면(행 32~33)과 s12 Settings additive 조정 항목·아카이브 스케줄러 APScheduler
결합으로 확장한다. 여섯 개의 단언 그룹(task 2.1):

- **Group 1 — attachment 스키마 vs s01 물리 모델(Req 2.1)**: 마이그레이션된 DB 의
  `information_schema` 로 `attachment` 컬럼(타입 계열·nullability·varchar 길이·`kind` ENUM 값·
  `is_archived` DDL 기본값 FALSE)·FK·인덱스(`(workspace_id, is_archived)`·`(document_id)`)를
  대조하고, s12 가 새 마이그레이션을 추가하지 않고 s01 단일 리비전(0001)만 씀을 확인한다.
- **Group 2 — 엔드포인트 카탈로그 32~33 노출·게이트 강제(Req 2.2)**: 부팅 앱 OpenAPI 가 s01
  카탈로그 행 32~33 을 정확한 경로 구조·메서드로 노출하고, 요구 role 게이트가 런타임에서 실제로
  강제됨(미인증 401·viewer 업로드 403)을 대표 요청으로 확인.
- **Group 3 — 에러 모델 vs s01 에러 카탈로그(Req 2.3)**: 401/403/404/422 를 실제로 유발해
  상태코드와 `ErrorResponse` 형태(`{code, message, field_errors?}`)·`code` 문자열을 대조.
- **Group 4 — Base Schemas 규약·참조 URL·바이너리 응답(Req 2.4)**: `AttachmentRead` 가 s01
  `ORMReadModel` 을 상속하고 계약 필드를 노출하며 `url` 이 `/attachments/{id}` 규약과 일치하고,
  바이너리 조회 응답이 스키마 본문이 아니라 스트리밍(binary)임을, `AttachmentCreate` 가 multipart
  규약(kind 선택)임을 확인.
- **Group 5 — Settings additive 조정 항목(Req 2.5)**: s12 가 additive 로 추가한
  `attachment_archive_root`·`attachment_sweep_interval_seconds`·`attachment_max_bytes` 가 존재하는
  실제 결합 부팅에서 `s01` `Settings`/`get_settings` 로딩이 정상 성공하고 기존 필드
  (`file_storage_root`·`default_trash_retention_days`·`trash_sweep_interval_seconds`·db_*·
  session_* 등)가 보존되며 설정 접근이 단일 `Settings`/`get_settings` 경유(첨부 모듈에 `os.environ`
  직접 접근 부재)임을 확인.
- **Group 6 — 아카이브 스케줄러 결합 부팅(Req 2.6)**: APScheduler 의존성이 결합된 상태에서
  `create_app()` 이 정상 부팅되고, `attachment_sweep_interval_seconds` `>0` 이면 스케줄러 기동·
  `<=0` 이면 미기동되며 이 결합이 기존 앱 부팅 계약을 회귀시키지 않음(부팅 스모크)을 확인한다.

재검증 트리거(design §Revalidation Triggers): `s01`(계약)·`s02`·`s03`·`s05`·`s07`·`s09`·`s10`·
`s12` 중 하나라도 수정되면 이 체크포인트를 누적 집합 기준으로 재실행한다(`s01` 수정 시 모든
체크포인트).

`harness`(L1 conftest)·`ws_scenario`(L2 conftest)·`tmp_attachment_roots`(L5 conftest) 픽스처가
제공하는 실 결합 환경 위에서만 동작하며 mock/stub/fake 를 쓰지 않는다(스케줄러 직접 기동은 실제
s12 코드 실행). 크기 초과 422 는 25MiB 페이로드를 쓰지 않도록 서비스의 `get_settings` 크기 한도만
테스트 시점에 낮춰 **실제 422 분기**를 결정적으로 태우는 test-time 한도 조정이며 스택 mock 이 아니다.
"""

import re
import types
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

import app.attachment.service as attachment_service_mod
from app.attachment import scheduler as archival_scheduler
from app.attachment.schemas import AttachmentCreate, AttachmentRead
from app.config import Settings, get_settings
from app.schemas.base import ORMReadModel
from tests.integration_L5 import helpers

# =============================================================================
# s01 단일 소스 계약 상수 — §Physical Data Model attachment · §API Catalog 32~33 · §Settings
# =============================================================================

# s01 §Physical Data Model — attachment 컬럼 nullability("NO" = NOT NULL). 전 컬럼 NOT NULL.
S01_ATTACHMENT_COLUMNS_NULLABILITY = {
    "id": "NO",
    "workspace_id": "NO",
    "document_id": "NO",
    "file_path": "NO",
    "original_name": "NO",
    "kind": "NO",
    "is_archived": "NO",
    "created_at": "NO",
}

# s01 attachment 타입 계열: BIGINT→bigint, VARCHAR→varchar, ENUM→enum, BOOLEAN→tinyint(MySQL),
# DATETIME→datetime.
S01_ATTACHMENT_TYPE_FAMILY = {
    "id": "bigint",
    "workspace_id": "bigint",
    "document_id": "bigint",
    "file_path": "varchar",
    "original_name": "varchar",
    "kind": "enum",
    "is_archived": "tinyint",
    "created_at": "datetime",
}

# s01 VARCHAR 길이 계약(file_path VARCHAR(1024)·original_name VARCHAR(255)).
S01_ATTACHMENT_VARCHAR_LENGTHS = {
    "file_path": 1024,
    "original_name": 255,
}

# s01 `kind ENUM('image','file')` — MySQL column_type 표현.
S01_ATTACHMENT_KIND_COLUMN_TYPE = "enum('image','file')"

# s01 attachment FK 계약 — (컬럼, 참조테이블, 참조컬럼).
S01_ATTACHMENT_FOREIGN_KEYS = {
    ("workspace_id", "workspace", "id"),
    ("document_id", "document", "id"),
}

# s01 attachment 인덱스 계약 — 선두 (workspace_id, is_archived) 과 (document_id) 를 덮는 인덱스.
S01_ATTACHMENT_INDEX_LAYOUTS = [
    ["workspace_id", "is_archived"],
    ["document_id"],
]

# s01 §API Endpoint Catalog rows 32~33 — (정규화 경로, 메서드, 요구 role).
# 경로는 파라미터 명명(`{id}`)에 비의존하도록 `_normalize_path` 로 정규화해 구조로 대조한다.
# 요구 role 은 대표 요청(미인증 401·viewer 업로드 403)으로 강제 관찰한다.
S01_ATTACHMENT_CATALOG_32_TO_33 = [
    ("/documents/{}/attachments", "post", "editor"),  # row 32
    ("/attachments/{}", "get", "viewer"),             # row 33
]

# s01 §Base Schemas 규약상 AttachmentRead 가 노출해야 하는 필드(파생 url 포함).
S01_ATTACHMENT_READ_FIELDS = {
    "id",
    "workspace_id",
    "document_id",
    "kind",
    "original_name",
    "is_archived",
    "created_at",
    "url",
}

# s12 가 additive 로 추가한 Settings 필드(존재해야 함, s01 계약을 비파괴적으로 확장).
S01_SETTINGS_ATTACHMENT_ADDITIVE_FIELDS = {
    "attachment_archive_root",
    "attachment_sweep_interval_seconds",
    "attachment_max_bytes",
}

# s01 §Settings 스키마 — additive 확장 이후에도 보존되어야 하는 기존 필드.
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
}

# 인증되었으나 대상이 존재하지 않을 때 어댑터 404 를 관측하기 위한 미존재 id.
MISSING_DOCUMENT_ID = 999_999_999
MISSING_ATTACHMENT_ID = 999_999_999


def _normalize_path(path: str) -> str:
    """경로의 `{param}` 세그먼트를 `{}` 로 정규화한다(파라미터 명명 비의존 구조 대조).

    s01 카탈로그와 s12 라우트는 경로 파라미터 식별자(`{id}`)를 다르게 적을 수 있으나 계약 요소는
    **경로 구조(세그먼트 배열 + 파라미터 위치) + 메서드 + 요구 role** 이므로 양쪽을 동일 규칙으로
    정규화해 대조한다.
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
# Group 1 — attachment 스키마 vs s01 물리 모델 (Req 2.1)
# =============================================================================


def test_attachment_columns_match_s01_physical_model(harness):
    """마이그레이션된 attachment 테이블의 컬럼·nullability·타입 계열·varchar 길이가 s01 과 일치(2.1).

    `information_schema.columns` 를 조회해 s01 이 정한 컬럼 집합(id·workspace_id·document_id·
    file_path·original_name·kind·is_archived·created_at)이 정확히 존재하고, 각 nullability(전 컬럼
    NOT NULL)·타입 계열·VARCHAR 길이(file_path 1024·original_name 255)가 s01 과 일치함을 대조한다.
    s12 가 첨부 스키마 형태를 드리프트시켰다면 어떤 컬럼이 어긋났는지 메시지에 명시한다.
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT column_name, is_nullable, data_type, character_maximum_length "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'attachment'"
            )
        ).all()
    assert rows, "마이그레이션된 DB 에 attachment 테이블 컬럼이 존재해야 한다(스키마 미적용?)"

    observed = {
        row[0]: (row[1].upper(), row[2].lower(), row[3]) for row in rows
    }

    expected_cols = set(S01_ATTACHMENT_COLUMNS_NULLABILITY)
    observed_cols = set(observed)
    missing = expected_cols - observed_cols
    extra = observed_cols - expected_cols
    assert not missing, f"attachment 테이블에 s01 계약 컬럼 누락: {sorted(missing)}"
    assert not extra, (
        f"attachment 테이블에 s01 계약 밖 컬럼 초과(업로더 FK 등 없어야 함): {sorted(extra)}"
    )

    for col, expected_nullable in S01_ATTACHMENT_COLUMNS_NULLABILITY.items():
        observed_nullable = observed[col][0]
        assert observed_nullable == expected_nullable, (
            f"attachment.{col} nullability 드리프트: s01={expected_nullable} "
            f"관측={observed_nullable}"
        )

    for col, expected_family in S01_ATTACHMENT_TYPE_FAMILY.items():
        observed_family = observed[col][1]
        assert observed_family == expected_family, (
            f"attachment.{col} 타입 계열 드리프트: s01={expected_family} "
            f"관측={observed_family}"
        )

    for col, expected_len in S01_ATTACHMENT_VARCHAR_LENGTHS.items():
        observed_len = observed[col][2]
        assert observed_len == expected_len, (
            f"attachment.{col} VARCHAR 길이 드리프트: s01={expected_len} "
            f"관측={observed_len}"
        )


def test_attachment_kind_enum_and_is_archived_default_match_s01(harness):
    """attachment.kind ENUM 값과 is_archived DDL 기본값 FALSE 가 s01 물리 모델과 일치(2.1).

    `kind` 는 `ENUM('image','file')`(column_type)로, `is_archived` 는 DDL DEFAULT FALSE(=0)로 s01
    이 정했다. `information_schema.columns` 의 column_type·column_default 로 대조한다(BOOLEAN 은
    MySQL 에서 tinyint(1)+DEFAULT 0 으로 실체화되며 0 이 FALSE 다).
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT column_name, column_type, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = 'attachment' "
                "AND column_name IN ('kind', 'is_archived')"
            )
        ).all()
    observed = {row[0]: (row[1].lower(), row[2]) for row in rows}

    assert "kind" in observed, "attachment 에 kind 컬럼이 존재해야 한다"
    observed_kind_type = observed["kind"][0].replace(" ", "")
    assert observed_kind_type == S01_ATTACHMENT_KIND_COLUMN_TYPE, (
        f"attachment.kind ENUM 드리프트: s01={S01_ATTACHMENT_KIND_COLUMN_TYPE!r} "
        f"관측={observed_kind_type!r} (s01 물리 모델 kind ENUM('image','file'))"
    )

    assert "is_archived" in observed, "attachment 에 is_archived 컬럼이 존재해야 한다"
    observed_default = observed["is_archived"][1]
    normalized_default = str(observed_default).strip("'\"") if observed_default is not None else None
    assert normalized_default == "0", (
        f"attachment.is_archived DDL 기본값 드리프트: s01=FALSE(0) "
        f"관측={observed_default!r} (보관 폴더 이동=영구삭제 soft-delete 기본 미보관)"
    )


def test_attachment_foreign_keys_match_s01(harness):
    """attachment 의 FK 가 s01 물리 모델과 일치(2.1).

    `information_schema.key_column_usage` 에서 참조 테이블이 있는 행을 조회해 s01 이 정한 FK
    (`workspace_id`→workspace.id·`document_id`→document.id, WS 격리 INV-6·문서 연결)가 존재함을
    대조한다.
    """
    with harness.session_local() as db:
        rows = db.execute(
            text(
                "SELECT column_name, referenced_table_name, referenced_column_name "
                "FROM information_schema.key_column_usage "
                "WHERE table_schema = DATABASE() AND table_name = 'attachment' "
                "AND referenced_table_name IS NOT NULL"
            )
        ).all()
    observed_fks = {(row[0], row[1], row[2]) for row in rows}
    missing = S01_ATTACHMENT_FOREIGN_KEYS - observed_fks
    assert not missing, (
        f"attachment FK 드리프트: s01 계약 FK 누락={sorted(missing)} "
        f"관측 FK={sorted(observed_fks)}"
    )


def test_attachment_indexes_match_s01(harness):
    """attachment 에 INDEX(workspace_id,is_archived)·INDEX(document_id)가 존재(s01, 2.1).

    s01 이 정한 두 인덱스(soft-delete 보관 필터 `(workspace_id, is_archived)` 과 문서 연결
    조회 `(document_id)`)를 컬럼 순서열 구조로 대조한다.
    """
    index_rows = _statistics_rows(harness, "attachment")
    assert index_rows, "attachment 에 인덱스가 존재해야 한다"
    grouped = _index_columns_by_name(index_rows)
    observed_layouts = list(grouped.values())
    for expected_layout in S01_ATTACHMENT_INDEX_LAYOUTS:
        assert expected_layout in observed_layouts, (
            f"attachment 인덱스 드리프트: s01 계약 인덱스 {expected_layout} 를 정확히 덮는 "
            f"인덱스가 없다. 관측 인덱스 레이아웃={observed_layouts}"
        )


def test_s12_adds_no_new_migration_over_s01_initial_schema():
    """s12 가 새 마이그레이션 없이 s01 단일 리비전(0001)만으로 동작함을 확인(2.1).

    (1) `migrations/versions/` 에 리비전 파일이 정확히 하나(`0001_initial_schema.py`)이고,
    (2) alembic head 가 단일 `0001` 리비전이며 그 down_revision 이 None(base)임을 확인한다.
    s12(첨부·이미지 저장·아카이브)는 attachment 테이블을 포함한 s01 단일 리비전 위에서 동작하며
    스키마 형태를 신설하지 않는다(Settings 만 additive 확장, DB 마이그레이션 무추가).
    """
    backend_dir = Path(__file__).resolve().parents[2]  # integration_L5 -> tests -> backend
    versions_dir = backend_dir / "migrations" / "versions"

    revision_files = sorted(
        p.name for p in versions_dir.glob("*.py") if p.name != "__init__.py"
    )
    # s01 baseline(0001) + additive user_setting(0002). s12 가 자기 마이그레이션을
    # 추가하지 않았음을 검증하는 것이 목적이므로 additive user_setting 은 허용한다.
    assert revision_files == ["0001_initial_schema.py", "0002_user_setting.py"], (
        "s12 는 새 마이그레이션을 추가하지 않고 s01 단일 리비전(0001) + additive user_setting 위에서 동작해야 "
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
# Group 2 — 엔드포인트 카탈로그 32~33 노출·게이트 강제 (Req 2.2)
# =============================================================================


def test_openapi_exposes_attachment_catalog_rows_32_to_33(harness):
    """부팅 앱 OpenAPI 가 s01 카탈로그 행 32~33 을 정확한 경로 구조·메서드로 노출(2.2).

    각 (정규화 경로, 메서드) 쌍이 앱 OpenAPI 에 존재함을 확인한다. 경로 파라미터 명명(`{id}`)은
    계약 요소가 아니므로 `_normalize_path` 로 정규화해 구조로 대조한다. 업로드
    (`POST /documents/{id}/attachments`)·서빙(`GET /attachments/{id}`) 표면이 s01 카탈로그
    32~33 과 정합함을 보증한다.
    """
    paths = harness.app.openapi()["paths"]
    observed = {
        (_normalize_path(path), method.lower())
        for path, methods in paths.items()
        for method in methods
    }

    for expected_path, expected_method, _role in S01_ATTACHMENT_CATALOG_32_TO_33:
        assert (expected_path, expected_method) in observed, (
            f"카탈로그 {expected_method.upper()} {expected_path} 가 앱 OpenAPI 에 노출되어야 "
            f"한다(API 드리프트): 관측 첨부 라우트="
            f"{sorted(o for o in observed if 'attachment' in o[0])}"
        )


def test_attachment_upload_route_unauthenticated_returns_401(harness):
    """업로드 라우트를 세션 없이 호출하면 401(요구 role 게이트 이전 인증 게이트 강제, 2.2).

    미인증 요청은 요구 role(editor)·문서 존재(404) 판정 이전에 `get_current_user` 가 401 을
    산출한다. multipart 파일을 실어도 인증 게이트가 먼저 걸림을 관측한다.
    """
    resp = helpers.attempt_upload_attachment(
        harness.new_client(),
        MISSING_DOCUMENT_ID,
        filename="x.png",
        content=b"\x89PNG\r\n\x1a\n",
        content_type="image/png",
    )
    assert resp.status_code == 401, (
        f"미인증 POST /documents/{{id}}/attachments 은 401 이어야 한다(인증 게이트): "
        f"{resp.status_code} {resp.text}"
    )


def test_attachment_serve_route_unauthenticated_returns_401(harness):
    """서빙 라우트를 세션 없이 호출하면 401(인증 게이트 강제, 2.2)."""
    resp = helpers.attempt_get_attachment(harness.new_client(), MISSING_ATTACHMENT_ID)
    assert resp.status_code == 401, (
        f"미인증 GET /attachments/{{id}}는 401 이어야 한다(인증 게이트): "
        f"{resp.status_code} {resp.text}"
    )


def test_attachment_upload_route_viewer_returns_403(ws_scenario, tmp_attachment_roots):
    """viewer 가 업로드 라우트를 호출하면 403(요구 role editor 게이트 강제, 2.2, INV-2).

    카탈로그 행 32(업로드)의 요구 role 이 실제로 editor 게이트로 걸려 있는지 — viewer(멤버지만
    editor 미만)의 업로드 요청이 런타임에서 거부됨(403)으로 확인한다. 실제 문서 위에서 게이트를
    통과하지 못함을 관측한다(tmp 저장 루트로 실제 저장 루트 오염 방지).
    """
    doc = helpers.l3_helpers.create_document(
        ws_scenario.editor_client, ws_scenario.workspace_id, "viewer게이트-업로드"
    )
    resp = helpers.attempt_upload_attachment(
        ws_scenario.viewer_client,
        doc["id"],
        filename="x.png",
        content=b"\x89PNG\r\n\x1a\n",
        content_type="image/png",
    )
    assert resp.status_code == 403, (
        f"viewer 의 업로드는 editor 게이트에서 403 이어야 한다(요구 role 강제, INV-2): "
        f"{resp.status_code} {resp.text}"
    )


# =============================================================================
# Group 3 — 에러 모델 vs s01 에러 카탈로그 (Req 2.3)
# =============================================================================


def test_error_401_unauthenticated_upload(harness):
    """미인증 업로드 요청 → 401 + code=unauthenticated + ErrorResponse 형태(2.3)."""
    resp = helpers.attempt_upload_attachment(
        harness.new_client(),
        MISSING_DOCUMENT_ID,
        filename="x.png",
        content=b"\x89PNG\r\n\x1a\n",
        content_type="image/png",
    )
    assert resp.status_code == 401, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "unauthenticated", (
        f"401 은 s01 에러 카탈로그상 code=unauthenticated 여야 한다: {body!r}"
    )


def test_error_403_forbidden_viewer_upload(ws_scenario, tmp_attachment_roots):
    """viewer 의 업로드 거부 → 403 + code=forbidden + ErrorResponse 형태(2.3)."""
    doc = helpers.l3_helpers.create_document(
        ws_scenario.editor_client, ws_scenario.workspace_id, "403-업로드"
    )
    resp = helpers.attempt_upload_attachment(
        ws_scenario.viewer_client,
        doc["id"],
        filename="x.png",
        content=b"\x89PNG\r\n\x1a\n",
        content_type="image/png",
    )
    assert resp.status_code == 403, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "forbidden", (
        f"403 은 s01 에러 카탈로그상 code=forbidden 여야 한다: {body!r}"
    )


def test_error_404_missing_document_upload(ws_scenario):
    """게이트를 통과하는 editor 로 미존재 문서 업로드 → 404 + code=not_found(문서→WS 어댑터, 2.3).

    비멤버는 resolver 가 role None 을 반환해 403 으로 막히므로, 문서→WS 어댑터가 매핑 실패로 404 를
    내는 경로를 관측하려면 게이트를 통과하는 인증 멤버(editor)로 호출한다. 문서 부재는 저장 이전에
    404 로 거부되므로 tmp 저장 루트가 필요 없다.
    """
    resp = helpers.attempt_upload_attachment(
        ws_scenario.editor_client,
        MISSING_DOCUMENT_ID,
        filename="x.png",
        content=b"\x89PNG\r\n\x1a\n",
        content_type="image/png",
    )
    assert resp.status_code == 404, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "not_found", (
        f"404 는 s01 에러 카탈로그상 code=not_found 여야 한다: {body!r}"
    )


def test_error_404_missing_attachment_serve(ws_scenario):
    """게이트를 통과하는 viewer 로 미존재 첨부 조회 → 404 + code=not_found(첨부→WS 어댑터, 2.3)."""
    resp = helpers.attempt_get_attachment(
        ws_scenario.viewer_client, MISSING_ATTACHMENT_ID
    )
    assert resp.status_code == 404, f"{resp.status_code} {resp.text}"
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "not_found", (
        f"404 는 s01 에러 카탈로그상 code=not_found 여야 한다: {body!r}"
    )


def test_error_422_oversize_upload(ws_scenario, monkeypatch):
    """크기 한도 초과 업로드 → 422 + code=unprocessable + ErrorResponse 형태(2.3).

    실제 config 의 `attachment_max_bytes`(25MiB)를 초과하는 페이로드를 쓰지 않도록, 서비스가
    호출 시점에 읽는 `app.attachment.service.get_settings` 의 크기 한도만 아주 작게(=1) 낮춰 **실제
    422 도메인 규칙 위반 분기**를 결정적으로 태운다(스택 mock 이 아니라 test-time 한도 조정 —
    서비스는 여전히 실제 코드 경로로 크기를 측정·비교한다). s01 §Errors 상 크기 초과 같은 도메인
    규칙 위반은 `code=unprocessable`(422)로 직렬화된다. 게이트를 통과하는 editor·실존 문서 위에서
    유발해 서비스 크기 판정에 도달함을 보장한다(문서 존재·게이트 통과 후 크기 검사).
    """
    doc = helpers.l3_helpers.create_document(
        ws_scenario.editor_client, ws_scenario.workspace_id, "422-크기초과"
    )
    small_limit_settings = types.SimpleNamespace(attachment_max_bytes=1)
    monkeypatch.setattr(
        attachment_service_mod, "get_settings", lambda: small_limit_settings
    )
    resp = helpers.attempt_upload_attachment(
        ws_scenario.editor_client,
        doc["id"],
        filename="big.bin",
        content=b"0123456789",  # 10바이트 > 1바이트 한도 → 실제 422 분기.
        content_type="application/octet-stream",
        kind="file",
    )
    assert resp.status_code == 422, (
        f"크기 초과 업로드는 422 여야 한다: {resp.status_code} {resp.text}"
    )
    body = resp.json()
    _assert_error_response_shape(body)
    assert body["code"] == "unprocessable", (
        f"크기 초과(도메인 규칙 위반)는 s01 에러 카탈로그상 code=unprocessable(422)여야 한다: "
        f"{body!r}"
    )


# =============================================================================
# Group 4 — Base Schemas 규약·참조 URL·바이너리 응답 (Req 2.4)
# =============================================================================


def test_attachment_read_inherits_s01_base_and_exposes_contract_fields():
    """AttachmentRead 가 s01 ORMReadModel 을 상속하고 계약 필드를 노출(2.4).

    s12 응답 Read 스키마가 s01 공통 Read 베이스(`ORMReadModel`, from_attributes)를 상속하고, s01
    계약 필드(id·workspace_id·document_id·kind·original_name·is_archived·created_at + 파생 url)를
    정확히 노출함을 클래스 수준에서 확인한다(file_path 는 미노출).
    """
    assert issubclass(AttachmentRead, ORMReadModel), (
        "AttachmentRead 는 s01 ORMReadModel 을 상속해야 한다(Base Schemas 드리프트)"
    )
    fields = set(AttachmentRead.model_fields)
    assert fields == S01_ATTACHMENT_READ_FIELDS, (
        f"AttachmentRead 필드 드리프트: s01 계약 필드={sorted(S01_ATTACHMENT_READ_FIELDS)} "
        f"관측={sorted(fields)} (file_path 미노출·url 파생 필드 포함)"
    )
    assert "file_path" not in fields, (
        "AttachmentRead 는 저장 경로(file_path)를 노출하지 않아야 한다(내부 구현 은닉)"
    )


def test_attachment_create_is_multipart_contract_with_optional_kind():
    """AttachmentCreate 가 multipart 규약(선택 kind, 바이너리 미포함)임을 확인(2.4).

    업로드 요청 스키마는 선택 메타데이터 `kind` 만 담고 파일 바이너리는 라우터 `UploadFile` 로
    별도 수신한다(스키마에 두지 않음). `kind` 가 선택(미지정 시 content-type 추론)임을 확인한다.
    """
    fields = set(AttachmentCreate.model_fields)
    assert fields == {"kind"}, (
        f"AttachmentCreate 는 선택 kind 만 담아야 한다(바이너리는 UploadFile 로 별도 수신): "
        f"관측 필드={sorted(fields)}"
    )
    assert not AttachmentCreate.model_fields["kind"].is_required(), (
        "AttachmentCreate.kind 는 선택 필드여야 한다(미지정 시 content-type 추론)"
    )


def test_upload_response_url_matches_reference_contract(ws_scenario, tmp_attachment_roots):
    """업로드 응답 `AttachmentRead.url` 이 `/attachments/{id}` 규약과 일치(2.4, 8.7 판정 근거).

    editor 가 실제 이미지를 업로드(tmp 저장 루트)해 201 응답의 `url` 이 서버 산정 파생값
    `/attachments/{id}` 규약(문서 본문 참조 토큰·8.7 참조 소멸 판정 근거)과 정확히 일치함을
    실제 결합 응답으로 확인한다.
    """
    doc = helpers.l3_helpers.create_document(
        ws_scenario.editor_client, ws_scenario.workspace_id, "url-규약"
    )
    att = helpers.upload_image(ws_scenario.editor_client, doc["id"])
    assert att["url"] == f"/attachments/{att['id']}", (
        f"AttachmentRead.url 은 `/attachments/{{id}}` 규약이어야 한다(참조 URL 드리프트): "
        f"id={att['id']} url={att['url']!r}"
    )
    assert att["kind"] == "image", (
        f"image/png 업로드는 kind=image 로 기록되어야 한다: {att!r}"
    )


def test_serve_response_is_binary_stream_not_json_schema(ws_scenario, tmp_attachment_roots):
    """미보관 첨부 조회 응답이 스키마 본문이 아니라 스트리밍(binary)임을 확인(2.4).

    viewer 가 업로드된 첨부를 조회하면 응답 content-type 이 `application/json` 이 아니고(스키마
    직렬화가 아니라 바이너리 스트림), 본문이 업로드한 원본 바이트열과 정확히 일치함을 확인한다.
    """
    doc = helpers.l3_helpers.create_document(
        ws_scenario.editor_client, ws_scenario.workspace_id, "binary-서빙"
    )
    payload = b"\x89PNG\r\n\x1a\n-contract-binary-payload"
    att = helpers.upload_image(ws_scenario.editor_client, doc["id"], content=payload)

    resp = helpers.get_attachment(ws_scenario.viewer_client, att["id"])
    content_type = resp.headers.get("content-type", "")
    assert not content_type.startswith("application/json"), (
        f"첨부 서빙은 스키마 JSON 본문이 아니라 바이너리 스트림이어야 한다: content-type={content_type!r}"
    )
    assert resp.content == payload, (
        f"서빙 본문은 업로드한 원본 바이트열과 일치해야 한다(스트리밍 바이너리): "
        f"기대={payload!r} 관측 길이={len(resp.content)}"
    )


# =============================================================================
# Group 5 — Settings additive 조정 항목 (Req 2.5)
# =============================================================================


def test_settings_additive_attachment_fields_present_and_existing_preserved(harness):
    """additive `attachment_*` 존재·기존 필드 보존·로딩 정상 성공(2.5).

    실제 결합 부팅(harness 가 이미 `create_app()` 부팅)에서 `get_settings()` 로딩이 정상 성공하고,
    s12 가 additive 로 추가한 `attachment_archive_root`·`attachment_sweep_interval_seconds`·
    `attachment_max_bytes` 가 `Settings` 스키마에 존재하며, 기존 s01 필드(`file_storage_root`·
    `default_trash_retention_days`·`trash_sweep_interval_seconds`·db_*·session_* 등)가 모두 보존되고
    유효한 값으로 로드됨을 확인한다. additive 확장이 s01 Settings 계약을 깨지 않았음을 지목한다.
    """
    fields = set(Settings.model_fields)
    missing_additive = S01_SETTINGS_ATTACHMENT_ADDITIVE_FIELDS - fields
    assert not missing_additive, (
        f"s12 additive 필드가 Settings 스키마에 있어야 한다: 누락={sorted(missing_additive)} "
        f"관측 필드={sorted(fields)}"
    )
    missing_preserved = S01_SETTINGS_PRESERVED_FIELDS - fields
    assert not missing_preserved, (
        f"additive 확장으로 s01 기존 Settings 필드가 소실되면 안 된다(계약 파손): "
        f"누락={sorted(missing_preserved)}"
    )

    settings = get_settings()  # 실 결합 부팅 설정 로딩(부팅 실패 없이 성공해야 함).
    assert isinstance(settings.attachment_archive_root, str) and settings.attachment_archive_root, (
        f"attachment_archive_root 는 비어있지 않은 str 로 로드되어야 한다: "
        f"{settings.attachment_archive_root!r}"
    )
    assert isinstance(settings.attachment_sweep_interval_seconds, int), (
        f"attachment_sweep_interval_seconds 는 int 로 로드되어야 한다: "
        f"{settings.attachment_sweep_interval_seconds!r}"
    )
    assert isinstance(settings.attachment_max_bytes, int) and settings.attachment_max_bytes > 0, (
        f"attachment_max_bytes 는 유효한 양수 int 여야 한다: {settings.attachment_max_bytes!r}"
    )
    # 기존 s01 필드가 유효한 값으로 보존됨(대표 표본).
    assert isinstance(settings.file_storage_root, str) and settings.file_storage_root, (
        f"기존 필드 file_storage_root 가 보존되어야 한다: {settings.file_storage_root!r}"
    )
    assert isinstance(settings.default_trash_retention_days, int)
    assert settings.default_trash_retention_days > 0
    assert settings.db_name and isinstance(settings.db_name, str)


def test_settings_single_accessor_is_cached(harness):
    """설정 접근이 단일 `get_settings` 접근자 경유(캐시된 동일 인스턴스)임을 확인(2.5).

    `get_settings()` 를 두 번 호출하면 lru_cache 로 **동일 인스턴스**가 반환됨을 확인해 설정
    접근이 모듈별 개별 로더가 아니라 단일 접근자를 통함을 관측한다.
    """
    assert get_settings() is get_settings(), (
        "설정 접근은 단일 `get_settings` 캐시 접근자를 경유해야 한다(동일 인스턴스)"
    )


def test_attachment_modules_have_no_direct_env_access():
    """첨부 모듈(app/attachment)에 `os.environ`·`os.getenv` 직접 접근이 없음을 확인(2.5).

    s01 단일화 원칙(설정은 단일 `Settings`/`get_settings` 경유)에 따라 s12 첨부 모듈에
    `os.environ[`·`os.environ.get(`·`os.getenv(` 같은 직접 환경변수 접근이 없어야 한다(모듈별
    설정 파일·직접 접근 부재). 실제 접근 패턴만 정규식으로 판정한다(docstring 문구 오탐 회피).
    """
    attachment_dir = Path(__file__).resolve().parents[2] / "app" / "attachment"
    pattern = re.compile(r"os\.environ\[|os\.environ\.get\(|os\.getenv\(")
    offenders: list[str] = []
    for py in attachment_dir.rglob("*.py"):
        if pattern.search(py.read_text(encoding="utf-8")):
            offenders.append(str(py))
    assert not offenders, (
        f"첨부 설정 경로에 직접 환경변수 접근이 없어야 한다(단일 Settings 경유): {offenders}"
    )


# =============================================================================
# Group 6 — 아카이브 스케줄러 APScheduler 결합 부팅 (Req 2.6)
# =============================================================================


def test_create_app_boots_cleanly_with_archival_scheduler_wired(harness):
    """APScheduler 아카이브 스케줄러 결합 상태에서 `create_app()` 이 정상 부팅됨(부팅 스모크, 2.6).

    부팅 앱은 lifespan 에 s12 아카이브 스윕 스케줄러(APScheduler)를 결선한다. 이 결합이 기존 앱
    부팅 계약을 회귀시키지 않음을 (1) harness 부팅 앱이 lifespan 을 가지며 (2) 첨부 업로드·서빙
    라우트가 조립되어 있음으로 확인한다(스케줄러 job 대기 없이 부팅 관찰).
    """
    app = harness.app
    assert app.router.lifespan_context is not None, (
        "부팅 앱은 s12 아카이브 스케줄러 결선을 위한 lifespan 을 가져야 한다(부팅 계약)"
    )
    observed = {
        (_normalize_path(path), method.lower())
        for path, methods in app.openapi()["paths"].items()
        for method in methods
    }
    assert ("/documents/{}/attachments", "post") in observed, (
        "APScheduler 결합 부팅이 s12 첨부 업로드 라우트 조립을 회귀시키면 안 된다"
    )
    assert ("/attachments/{}", "get") in observed, (
        "APScheduler 결합 부팅이 s12 첨부 서빙 라우트 조립을 회귀시키면 안 된다"
    )


def test_archival_scheduler_starts_when_interval_positive(harness):
    """`attachment_sweep_interval_seconds > 0` 이면 아카이브 스윕 스케줄러가 기동됨(2.6).

    실제 config(3600 > 0) 값으로 `archival_scheduler.start(app)` 를 호출해 APScheduler 가 기동
    (running=True)되고 아카이브 스윕 job 이 등록됨을 모듈 상태로 관측한다. 스케줄러 job 은 interval
    주기(3600초) 뒤 첫 실행이므로 테스트 중 실행되지 않는다(대기·sleep 없음). 종료는 finally 에서
    반드시 정리한다(background thread 누수 방지).
    """
    archival_scheduler.stop()  # 잔여 상태 정리(멱등 no-op 가능).
    assert get_settings().attachment_sweep_interval_seconds > 0, (
        "이 테스트는 실제 config 의 interval 이 >0 임을 전제한다(현재 config.yml=3600)"
    )
    try:
        archival_scheduler.start(harness.app)
        sched = archival_scheduler._scheduler
        assert sched is not None, (
            "interval>0 이면 아카이브 스윕 스케줄러가 기동되어야 한다(_scheduler 비어있음=미기동)"
        )
        assert sched.running, "기동된 스케줄러는 running 상태여야 한다"
        assert sched.get_job(archival_scheduler._JOB_ID) is not None, (
            f"아카이브 스윕 job({archival_scheduler._JOB_ID})이 등록되어야 한다"
        )
    finally:
        archival_scheduler.stop()
    assert archival_scheduler._scheduler is None, (
        "stop() 후 스케줄러 홀더가 정리(None)되어야 한다"
    )


def test_archival_scheduler_not_started_when_interval_non_positive(harness, monkeypatch):
    """`attachment_sweep_interval_seconds <= 0` 이면 스케줄러가 기동되지 않음(2.6).

    실제 `Settings`/`get_settings` 로더 경로에 환경변수로 interval=0 을 주입(pydantic-settings 가
    실제로 로드하는 값이며 mock 이 아님)한 뒤 `archival_scheduler.start(app)` 를 호출해 인프로세스
    스케줄러가 기동되지 않음(_scheduler=None, 외부 cron 신호 분기)을 관측한다. 환경변수·설정 캐시는
    finally 에서 원상 복구한다(harness 의 테스트 DB 설정은 DB_NAME 환경변수로 유지되므로 캐시
    재적재 시에도 개발 DB 로 새지 않는다).
    """
    archival_scheduler.stop()  # 잔여 상태 정리.
    monkeypatch.setenv("ATTACHMENT_SWEEP_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    try:
        assert get_settings().attachment_sweep_interval_seconds <= 0, (
            "환경변수 주입으로 interval 이 <=0 로 로드되어야 한다(설정 경로 확인)"
        )
        archival_scheduler.start(harness.app)
        assert archival_scheduler._scheduler is None, (
            "interval<=0 이면 인프로세스 스케줄러가 기동되지 않아야 한다(외부 cron 신호)"
        )
    finally:
        archival_scheduler.stop()
        get_settings.cache_clear()  # 주입값 제거(monkeypatch 가 env 를 되돌림).
