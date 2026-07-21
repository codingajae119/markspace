"""워크스페이스 단위 권한 resolver + admin 게이트 (Requirement 5.1~5.7, INV-1·2·3).

design.md §Common/Permissions #PermissionResolver 계약을 구현한다. 권한은
**워크스페이스 단위로만** 판정하며(INV-1, 문서별 개별 권한 없음), role 위계는
owner ≥ member 2단계이다(:class:`Role` IntEnum 비교). 요청자가 admin 이면
멤버십·role 과 무관하게 항상 통과한다(INV-3 admin bypass).

권한 검사 단일화(steering config/permission-singularity): admin 전용 게이트
:func:`require_admin` 은 이 모듈에 **단 한 번** 정의되며, admin 전용 엔드포인트
(카탈로그 row 5–9)는 이 유일한 정의를 소비한다. feature spec 은 자체
``require_admin`` 을 재정의해서는 안 된다(MUST NOT).

의존 방향: db·auth·errors·models(공통/좌측) + fastapi/sqlalchemy/stdlib 만
import 한다. routers·main·feature 도메인은 import 하지 않는다.
"""

from enum import IntEnum
from typing import Callable

from fastapi import Depends
from sqlalchemy.orm import Session

from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import DomainError, ErrorCode
from app.models import WorkspaceMember


class Role(IntEnum):
    """워크스페이스 role 위계 비교용 (Req 1.1·1.2).

    정수 순서가 곧 권한 포함 관계다: OWNER(2) ≥ MEMBER(1). owner 는 member 의
    모든 권한을 포함한다. 편집·읽기 작업은 최소 요구 role 을 ``MEMBER`` 로,
    관리 작업은 ``OWNER`` 로 표현한다. VIEWER/EDITOR 는 삭제되었으며 하위 호환
    alias 는 두지 않는다.
    """

    MEMBER = 1
    OWNER = 2


# WorkspaceMember.role 은 ENUM('owner','member') 컬럼으로 Python str 을 돌려준다.
# 위계 비교가 가능한 Role 로 매핑한다. 미정의/None 은 매핑에서 제외되어
# resolve() 가 None 을 돌려준다(멤버 아님과 동일 취급).
_ROLE_MAP: dict[str, Role] = {
    "owner": Role.OWNER,
    "member": Role.MEMBER,
}


class WorkspaceRoleResolver:
    """workspace_member 조회로 role 위계·admin bypass 를 판정한다 (Req 5.1~5.6)."""

    def resolve(
        self, db: Session, ctx: AuthContext, workspace_id: int
    ) -> Role | None:
        """``(workspace_id, ctx.user_id)`` 멤버의 :class:`Role` 을 돌려준다.

        멤버가 아니거나 role 문자열이 알 수 없는 값이면 ``None`` (Req 5.3).
        판정은 오직 workspace_id 기준이며 문서별 권한 개념은 없다(INV-1).
        """
        member = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == ctx.user_id,
            )
            .one_or_none()
        )
        if member is None:
            return None
        return _ROLE_MAP.get(member.role)

    def has_at_least(
        self, db: Session, ctx: AuthContext, workspace_id: int, minimum: Role
    ) -> bool:
        """요구 최소 role 충족 여부. admin 이면 조회 없이 항상 True (INV-3).

        비-admin 은 :meth:`resolve` 결과가 존재하고 ``role >= minimum`` 일 때만
        True (owner ≥ member 위계, Req 5.2·5.4·5.6).
        """
        if ctx.is_admin:
            return True
        role = self.resolve(db, ctx, workspace_id)
        return role is not None and role >= minimum


def require_ws_role(minimum: Role) -> Callable[..., AuthContext]:
    """요구 최소 role 을 강제하는 FastAPI 의존성 팩토리 (Req 5.7).

    사용법(하위 spec): ``current = Depends(require_ws_role(Role.MEMBER))``.

    반환되는 의존성은 경로 파라미터 ``workspace_id: int`` 와 현재 사용자·DB 세션을
    주입받아 :meth:`WorkspaceRoleResolver.has_at_least` 로 판정한다. 충족하면
    ``AuthContext`` 를 그대로 돌려주고, 미충족이면 표준 403 ``DomainError``
    (FORBIDDEN) 를 raise 한다(Req 5.3, INV-2). admin 은 항상 통과한다(INV-3).

    workspace_id 어댑터: 경로가 ``/workspaces/{workspace_id}/...`` 형태이면 이
    기본 의존성이 그대로 쓰인다. workspace_id 가 경로 파라미터 ``workspace_id``
    가 아닌(예: 본문·문서 id→ws 매핑) feature 는 자체 얇은 어댑터에서
    :class:`WorkspaceRoleResolver` 를 호출해 동일 판정을 재사용한다(Req 5.7 경계).
    """
    resolver = WorkspaceRoleResolver()

    def dependency(
        workspace_id: int,
        ctx: AuthContext = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> AuthContext:
        if not resolver.has_at_least(db, ctx, workspace_id, minimum):
            raise _forbidden()
        return ctx

    return dependency


def require_admin(ctx: AuthContext = Depends(get_current_user)) -> AuthContext:
    """admin 전용 게이트 (권한 단일화, INV-3 admin 판정과 정합).

    사용법(하위 spec): ``current: AuthContext = Depends(require_admin)``.

    ``not ctx.is_admin`` 이면 표준 403 ``DomainError(FORBIDDEN)`` 을 raise 하고,
    admin 이면 ``ctx`` 를 그대로 통과시킨다. 이 정의가 admin 전용 엔드포인트
    (카탈로그 row 5–9)의 **유일한** admin 검사 지점이다(feature 재정의 금지).
    """
    if not ctx.is_admin:
        raise _forbidden()
    return ctx


def _forbidden() -> DomainError:
    return DomainError(
        code=ErrorCode.FORBIDDEN,
        message="Insufficient permission",
        http_status=403,
    )
