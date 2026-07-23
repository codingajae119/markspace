"""활성 사용자 워크스페이스 읽기 게이트 단위 테스트 (Task 3.1 / Req 3.2·3.6·3.7·3.8·7.2).

``require_active_workspace`` 는 읽기 전역 개방 게이트로, 활성 사용자(get_current_user
재사용)와 워크스페이스 존재만 요구하고 **role 을 판정하지 않는다**. 따라서 비멤버
활성 사용자도 존재하는 워크스페이스에 대해 403 없이 통과해야 한다(R3.8, R7.2).

FastAPI DI 를 거치지 않고 게이트 함수를 직접 호출해 분기를 검증한다.

격리: ``test_permissions.py`` 와 동일하게 전용 테스트 DB(``markspace_test``)를
대상으로 ``DB_NAME`` 을 바꾸고 ``get_settings`` 캐시를 비운 뒤 새 엔진을 만든다.
종료 시 테이블을 모두 제거하고 환경변수·캐시를 원복한다.
"""

import os
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — side-effect: Base.metadata 채움
from app.common.auth import AuthContext
from app.common.db import Base
from app.common.errors import DomainError, ErrorCode
from app.common.permissions import require_active_workspace
from app.models import User, Workspace

TEST_DB_NAME = "markspace_test"


def _drop_everything(engine) -> None:
    """대상 DB 의 모든 테이블을 FK 무시하고 제거해 빈 상태로 만든다."""
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
def test_session():
    """테스트 DB 에 전체 스키마를 생성하고 세션을 제공한 뒤 정리한다."""
    from app.config import get_settings

    prev_db_name = os.environ.get("DB_NAME")
    os.environ["DB_NAME"] = TEST_DB_NAME
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.db_name == TEST_DB_NAME, "테스트가 개발 DB 로 새면 안 된다"

    engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
    _drop_everything(engine)
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = SessionFactory()

    try:
        yield session
    finally:
        session.close()
        try:
            _drop_everything(engine)
        finally:
            engine.dispose()
            if prev_db_name is None:
                os.environ.pop("DB_NAME", None)
            else:
                os.environ["DB_NAME"] = prev_db_name
            get_settings.cache_clear()


def _make_user(session, *, is_admin=False):
    """테스트 세션에 User 를 삽입하고 flush 하여 id 를 확정한다."""
    suffix = f"{is_admin}-{datetime.utcnow().timestamp()}"
    user = User(
        login_id=f"user-{suffix}",
        password_hash="x",
        name="테스트 사용자",
        is_admin=is_admin,
        is_active=True,
        is_deleted=False,
        created_at=datetime.utcnow(),
    )
    session.add(user)
    session.flush()
    return user


def _make_workspace(session):
    """테스트 세션에 Workspace 를 삽입하고 flush 하여 id 를 확정한다."""
    ws = Workspace(
        name="테스트 워크스페이스",
        is_shareable=False,
        trash_retention_days=30,
        created_at=datetime.utcnow(),
    )
    session.add(ws)
    session.flush()
    return ws


def _ctx(user):
    return AuthContext(user_id=user.id, is_admin=user.is_admin)


def test_active_non_member_passes_without_403(test_session):
    """비멤버 활성 사용자는 존재하는 WS 에 대해 403 없이 ctx 를 돌려받는다 (R3.8, R7.2)."""
    ws = _make_workspace(test_session)
    user = _make_user(test_session)  # 멤버십 없음
    ctx = _ctx(user)

    result = require_active_workspace(workspace_id=ws.id, ctx=ctx, db=test_session)

    assert result is ctx


def test_absent_workspace_raises_404(test_session):
    """존재하지 않는 워크스페이스는 404 NOT_FOUND (R3.7)."""
    user = _make_user(test_session)
    ctx = _ctx(user)

    with pytest.raises(DomainError) as exc:
        require_active_workspace(workspace_id=999_999, ctx=ctx, db=test_session)

    assert exc.value.code == ErrorCode.NOT_FOUND
    assert exc.value.http_status == 404


def test_no_403_branch_for_non_member(test_session):
    """게이트에는 403 발생 지점이 없어 비멤버가 FORBIDDEN 을 받지 않는다 (R3.8)."""
    ws = _make_workspace(test_session)
    user = _make_user(test_session)
    ctx = _ctx(user)

    try:
        require_active_workspace(workspace_id=ws.id, ctx=ctx, db=test_session)
    except DomainError as exc:  # pragma: no cover - 실패 시 진단용
        assert exc.code != ErrorCode.FORBIDDEN, "읽기 게이트는 403 을 내면 안 된다"
        raise


def test_gate_delegates_auth_401_propagation():
    """게이트는 get_current_user 의 401 을 그대로 전파한다 (R3.6, 위임 계약).

    실제 세션 검증은 get_current_user 소관이므로, 게이트 시그니처가 활성 게이트를
    ``Depends(get_current_user)`` 로 주입해 미인증·비활성 401 을 재사용함을 확인한다.
    """
    import inspect

    from app.common.auth import get_current_user

    sig = inspect.signature(require_active_workspace)
    ctx_default = sig.parameters["ctx"].default
    # FastAPI Depends 래퍼의 dependency 가 get_current_user 여야 한다.
    assert getattr(ctx_default, "dependency", None) is get_current_user
