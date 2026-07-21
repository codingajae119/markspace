"""마이그레이션 적용·왕복 통합 테스트 (Task 2.3 / Req 1.1, 1.10, 1.11).

Alembic 파이썬 API 로 ``upgrade head`` 를 실행해 전체 DB 계약이 물리적으로
생성되는지(7테이블·``is_admin``·UNIQUE·soft-delete 인덱스·ENUM) 검증하고,
``downgrade base`` 로 스키마가 재현 가능하게 원복되는지 검증한다. 재적용
가능성까지 확인하기 위해 upgrade→downgrade 를 한 번 더 반복한다.

격리: 개발 DB(``notion_lite``)를 건드리지 않도록 전용 테스트 DB
(``notion_lite_test``)를 대상으로 한다. ``DB_NAME`` 환경변수로 대상 DB 를
바꾸고(env 소스가 YAML 보다 우선), :func:`app.config.get_settings` 캐시를
비워 ``migrations/env.py`` 가 실행 시점에 테스트 DB URL 을 읽게 한다. 테스트
종료 시 환경변수·캐시를 원복하고 테스트 DB 를 비워, 이후 다른 테스트가 다시
개발 DB 를 바라보게 한다(캐시 누수 방지).
"""

import os
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

TEST_DB_NAME = "notion_lite_test"

# 애플리케이션 계약 테이블(alembic_version 은 제외) — Req 1.1.
# s01 초기 7개 + additive 확장 user_setting(0002 마이그레이션).
APP_TABLES = {
    "user",
    "workspace",
    "workspace_member",
    "document",
    "document_version",
    "attachment",
    "share_link",
    "user_setting",
}

# 기대 UNIQUE 제약: (테이블, frozenset(컬럼)).
EXPECTED_UNIQUES = {
    ("user", frozenset({"login_id"})),
    ("share_link", frozenset({"token"})),
    ("workspace_member", frozenset({"workspace_id", "user_id"})),
    ("user_setting", frozenset({"user_id"})),
}

# 기대 soft-delete/필터 인덱스: 인덱스명 → (테이블, 순서 있는 컬럼) — Req 1.11.
EXPECTED_INDEXES = {
    "ix_user_is_deleted_is_active": ("user", ["is_deleted", "is_active"]),
    "ix_document_ws_status_parent": ("document", ["workspace_id", "status", "parent_id"]),
    "ix_document_ws_status_trashed_at": (
        "document",
        ["workspace_id", "status", "trashed_at"],
    ),
    "ix_attachment_ws_is_archived": ("attachment", ["workspace_id", "is_archived"]),
}

# 기대 ENUM: (테이블, 컬럼) → 값 집합.
# workspace_member.role 은 s26(0004) open-access-roles 이 head 에서 owner/member 2단계로
# 재편한다. 이 검증은 upgrade head 직후의 구조를 보므로 head=0004 기준 {owner, member} 다.
# (downgrade 시 ENUM 구조는 owner/editor/viewer 로 되돌아가지만 데이터는 비대칭 — member→
# editor, viewer 미복구, R2.5. 구조 roundtrip 은 구조만 보므로 이 상수와 무관하게 통과한다.)
EXPECTED_ENUMS = {
    ("workspace_member", "role"): {"owner", "member"},
    ("document", "status"): {"active", "trashed", "deleted"},
    ("attachment", "kind"): {"image", "file"},
}


def _drop_everything(engine) -> None:
    """대상 DB 의 모든 테이블을 FK 무시하고 제거해 빈 상태로 만든다(견고한 teardown)."""
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        names = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = DATABASE()"
                )
            )
        ]
        for name in names:
            conn.execute(text(f"DROP TABLE IF EXISTS `{name}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


@pytest.fixture
def alembic_test_env():
    """테스트 DB 를 가리키는 Alembic ``Config`` + 엔진을 제공하고, 종료 시 정리한다."""
    from app.config import get_settings

    backend_dir = Path(__file__).resolve().parent.parent

    prev_db_name = os.environ.get("DB_NAME")
    os.environ["DB_NAME"] = TEST_DB_NAME
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.db_name == TEST_DB_NAME, "테스트가 개발 DB 로 새면 안 된다"
    engine = create_engine(settings.sqlalchemy_url)

    # pytest cwd 와 무관하게 동작하도록 절대 경로로 Config 를 구성한다.
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))

    try:
        yield cfg, engine, TEST_DB_NAME
    finally:
        try:
            _drop_everything(engine)
        finally:
            engine.dispose()
            # 환경변수 원복 후 캐시를 비워 다음 테스트가 개발 DB 설정을 다시 읽게 한다.
            if prev_db_name is None:
                os.environ.pop("DB_NAME", None)
            else:
                os.environ["DB_NAME"] = prev_db_name
            get_settings.cache_clear()


def _app_tables(engine, db_name) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :db AND table_name <> 'alembic_version'"
            ),
            {"db": db_name},
        )
        return {row[0] for row in rows}


def _column_exists(engine, db_name, table, column) -> bool:
    with engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.columns "
                "WHERE table_schema = :db AND table_name = :t AND column_name = :c"
            ),
            {"db": db_name, "t": table, "c": column},
        ).scalar()
        return count == 1


def _indexes(engine, db_name, table):
    """{index_name: (non_unique, [seq 순 컬럼])} 을 반환한다."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT index_name, non_unique, seq_in_index, column_name "
                "FROM information_schema.statistics "
                "WHERE table_schema = :db AND table_name = :t "
                "ORDER BY index_name, seq_in_index"
            ),
            {"db": db_name, "t": table},
        ).all()
    result: dict[str, tuple[int, list[str]]] = {}
    for index_name, non_unique, _seq, column_name in rows:
        non_unique_val, cols = result.setdefault(index_name, (int(non_unique), []))
        cols.append(column_name)
    return result


def _column_type(engine, db_name, table, column) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT column_type FROM information_schema.columns "
                "WHERE table_schema = :db AND table_name = :t AND column_name = :c"
            ),
            {"db": db_name, "t": table, "c": column},
        ).scalar()


def _assert_full_schema(engine, db_name) -> None:
    """upgrade head 직후의 전체 물리 계약을 검증한다."""
    # Req 1.1 — 정확히 7개 애플리케이션 테이블.
    assert _app_tables(engine, db_name) == APP_TABLES

    # user.is_admin 존재.
    assert _column_exists(engine, db_name, "user", "is_admin")

    # UNIQUE 제약(login_id, token, (workspace_id, user_id)).
    unique_column_sets: set[tuple[str, frozenset]] = set()
    for table in {t for t, _ in EXPECTED_UNIQUES}:
        for _name, (non_unique, cols) in _indexes(engine, db_name, table).items():
            if non_unique == 0:
                unique_column_sets.add((table, frozenset(cols)))
    for expected in EXPECTED_UNIQUES:
        assert expected in unique_column_sets, f"UNIQUE 누락: {expected}"

    # soft-delete/필터 인덱스(Req 1.11) — 이름·컬럼 구성까지 검증.
    for index_name, (table, cols) in EXPECTED_INDEXES.items():
        table_indexes = _indexes(engine, db_name, table)
        assert index_name in table_indexes, f"인덱스 누락: {index_name}"
        assert table_indexes[index_name][1] == cols, (
            f"인덱스 컬럼 불일치: {index_name} -> {table_indexes[index_name][1]}"
        )

    # ENUM 값 집합.
    for (table, column), expected_values in EXPECTED_ENUMS.items():
        col_type = _column_type(engine, db_name, table, column)
        assert col_type is not None and col_type.lower().startswith("enum("), (
            f"ENUM 아님: {table}.{column} -> {col_type}"
        )
        values = set(re.findall(r"'((?:[^']|'')*)'", col_type))
        assert values == expected_values, (
            f"ENUM 값 불일치: {table}.{column} -> {values}"
        )


def test_migration_upgrade_downgrade_roundtrip(alembic_test_env):
    """upgrade→검증→downgrade→재검증(+재적용) 왕복이 통과한다 (Req 1.1, 1.10, 1.11)."""
    cfg, engine, db_name = alembic_test_env

    # 시작 전 테스트 DB 는 비어 있어야 한다(격리 전제).
    assert _app_tables(engine, db_name) == set()

    # 1) upgrade head → 전체 계약 검증.
    command.upgrade(cfg, "head")
    _assert_full_schema(engine, db_name)

    # 2) downgrade base → 7개 앱 테이블이 모두 사라진다(Req 1.10 재현 가능 역전).
    command.downgrade(cfg, "base")
    assert _app_tables(engine, db_name) == set()

    # 3) 재적용 가능성 확인: 다시 upgrade → 동일 계약 재검증.
    command.upgrade(cfg, "head")
    _assert_full_schema(engine, db_name)

    # 4) 다시 downgrade base 로 원복(정리는 fixture teardown 이 보증).
    command.downgrade(cfg, "base")
    assert _app_tables(engine, db_name) == set()
