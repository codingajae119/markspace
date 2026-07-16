"""DB 공통 모듈 단위/통합 테스트 (Requirement 1.9, 8.3).

- ``Base`` 는 SQLAlchemy 2.0 ``DeclarativeBase`` 하위 클래스로 ``metadata`` 를 노출한다.
- ``get_db()`` 는 요청 스코프 세션을 yield 하고 종료 시 close 한다(1.9).
- ``get_db()`` 로 얻은 세션에서 ``SELECT 1`` 이 실제 개발 MySQL 8 에 대해 성공한다(8.3).

close 생명주기 테스트는 결정성을 위해 ``SessionLocal`` 을 목으로 대체한다.
``SELECT 1`` 테스트는 실제 개발 DB 연결을 요구한다(8.3 검증 목적).
"""

from unittest.mock import MagicMock, patch

from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase, Session

from app.common import db as db_module
from app.common.db import Base, get_db


def test_base_is_declarative_base_with_metadata():
    """Base 는 DeclarativeBase 하위 클래스이며 usable metadata 를 가진다."""
    assert issubclass(Base, DeclarativeBase)
    assert hasattr(Base, "metadata")
    # metadata 는 models 패키지가 채우기 전이라도 tables 매핑을 노출한다.
    assert hasattr(Base.metadata, "tables")


def test_get_db_closes_session_exactly_once():
    """get_db() 는 제너레이터 소진 시 세션을 정확히 한 번 close 한다 (1.9)."""
    fake_session = MagicMock(spec=Session)
    with patch.object(db_module, "SessionLocal", return_value=fake_session):
        gen = get_db()
        yielded = next(gen)
        assert yielded is fake_session
        fake_session.close.assert_not_called()
        # 제너레이터 소진 → finally 블록에서 close.
        with __import__("pytest").raises(StopIteration):
            next(gen)
    fake_session.close.assert_called_once()


def test_get_db_closes_session_on_early_close():
    """소비자가 제너레이터를 조기에 close 해도 세션이 close 된다 (1.9, 요청 스코프)."""
    fake_session = MagicMock(spec=Session)
    with patch.object(db_module, "SessionLocal", return_value=fake_session):
        gen = get_db()
        next(gen)
        gen.close()
    fake_session.close.assert_called_once()


def test_get_db_select_one_against_real_mysql():
    """get_db() 세션에서 SELECT 1 이 실제 개발 MySQL 에 대해 성공한다 (8.3)."""
    gen = get_db()
    db = next(gen)
    try:
        assert isinstance(db, Session)
        result = db.execute(text("SELECT 1")).scalar()
        assert result == 1
    finally:
        gen.close()
