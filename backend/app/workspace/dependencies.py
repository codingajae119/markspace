"""워크스페이스 라우터용 의존성 (design.md §Feature/Dependency #WsIdAdapter).

경로 파라미터 ``{id}`` 를 workspace_id 로 추출해 s01 공통 ``require_ws_role(minimum)`` 에
주입하는 **얇은 어댑터**를 소유한다. s05 워크스페이스 라우트는 경로가 ``/workspaces/{id}``
형태(s01 카탈로그 행 10~17)이지만, s01 ``require_ws_role`` 의 내부 의존성은 경로 파라미터를
``workspace_id`` 로 문자 그대로 읽는다. 이 이름 차이를 잇는 것이 이 어댑터의 유일한 책임이다.

**판정 로직 재구현 없음**: role 위계 비교(owner ≥ editor ≥ viewer)·admin bypass(INV-3)·
403 raise 는 전부 s01 ``WorkspaceRoleResolver``/``require_ws_role`` 이 소유한다. 이 어댑터는
s01 의존성을 한 번 구성한 뒤 경로 ``{id}`` 를 ``workspace_id`` 로 넘겨 **위임만** 한다.

**admin 게이트는 s05 가 정의하지 않는다**: ``require_admin`` 은 s01 ``common/permissions`` 의
공통 게이트로 중앙화되었으므로 이 모듈은 이를 소유·재정의하지 않는다. ``admin_router.py``
(task 3.2)는 ``from app.common.permissions import require_admin`` 으로 직접 소비한다
(design.md §require_admin — feature-local 정의 폐기).

편의를 위해 s01 ``Role`` IntEnum 만 재노출한다(라우터가 role 상수를 한 곳에서 import).
``Role`` 은 s01 원본과 **동일 객체**이며 재정의가 아니다.
"""

from typing import Callable

from fastapi import Depends
from sqlalchemy.orm import Session

from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.permissions import Role, require_ws_role as _s01_require_ws_role

__all__ = ["Role", "require_ws_role"]


def require_ws_role(minimum: Role) -> Callable[..., AuthContext]:
    """경로 ``{id}`` 를 workspace_id 로 잇는 워크스페이스 role 게이트 어댑터 (Req 4.1~4.6).

    사용법(워크스페이스 라우터): ``Depends(require_ws_role(Role.OWNER))`` 를 경로
    ``/workspaces/{id}/...`` 라우트에 부착한다.

    반환되는 의존성은 경로 파라미터 ``id: int`` 를 받아 s01 ``require_ws_role(minimum)`` 이
    돌려준 내부 의존성에 ``workspace_id=id`` 로 넘겨 위임한다. 충족하면 ``AuthContext`` 를
    그대로 돌려주고, 미충족·비멤버는 s01 이 표준 403 ``DomainError(FORBIDDEN)`` 을 raise
    하며, admin 은 s01 이 bypass 시킨다(INV-1·2·3). 위계·bypass·403 판정은 모두 s01 소유이며
    여기서 재구현하지 않는다.
    """
    _delegate = _s01_require_ws_role(minimum)

    def dependency(
        id: int,
        ctx: AuthContext = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> AuthContext:
        # s01 내부 의존성은 평범한 sync 함수이므로 직접 호출한다. 경로 {id} 를
        # workspace_id 로 매핑하는 것 외의 판정은 전적으로 s01 에 위임한다.
        return _delegate(workspace_id=id, ctx=ctx, db=db)

    return dependency
