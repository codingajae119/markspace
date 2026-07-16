"""문서 id → workspace_id 추출 어댑터 (design.md §Components and Interfaces #DocumentWsAdapter).

`/documents/{id}` 경로에서 문서의 workspace_id 를 추출해 s01 `require_ws_role` 판정에
주입한다(Req 10.3·10.4). 문서 미존재 시 404, 존재 시 workspace_id 로 판정을 위임한다.
`/workspaces/{id}/*` 경로는 경로 {id} 를 직접 workspace_id 로 사용하므로 이 어댑터 대상이
아니다(s01/s05 `require_ws_role` 직접 사용).

**판정 로직 재구현 없음**: role 위계 비교(owner ≥ editor ≥ viewer)·admin bypass(INV-3)·
403 raise 는 전부 s01 `WorkspaceRoleResolver`/`require_ws_role` 이 소유한다(Req 10.4). 이
어댑터는 문서 id → workspace_id 로 매핑한 뒤 s01 내부 의존성에 workspace_id 를 넘겨
**위임만** 한다. 매핑이 실패(문서 미존재)하면 s01 판정에 앞서 404 로 거부한다.

편의를 위해 s01 `Role` IntEnum 만 재노출한다(라우터가 role 상수를 한 곳에서 import).
`Role` 은 s01 원본과 **동일 객체**이며 재정의가 아니다(s05 dependencies.py 와 동일 패턴).

경계: s01 `common`(auth·db·permissions·errors)·document `repository` 만 import 하며 다른
feature 도메인을 import 하지 않는다. s01 계약을 수정하지 않는다.
"""

from typing import Callable

from fastapi import Depends
from sqlalchemy.orm import Session

from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.common.errors import DomainError, ErrorCode
from app.common.permissions import Role, require_ws_role as _s01_require_ws_role
from app.document.repository import DocumentRepository

__all__ = ["Role", "ws_role_for_document"]

# 어댑터가 문서 id → workspace_id 매핑에만 쓰는 경량 조회 지점. 세션은 요청별로
# 주입받고 리포지토리 인스턴스 자체는 무상태이므로 모듈 단일 인스턴스를 재사용한다.
_repository = DocumentRepository()


def ws_role_for_document(minimum: Role) -> Callable[..., AuthContext]:
    """문서 `{id}` 를 workspace_id 로 잇는 문서 role 게이트 어댑터 (Req 10.3·10.4).

    사용법(문서 라우터): ``Depends(ws_role_for_document(Role.EDITOR))`` 를 경로
    ``/documents/{id}`` 라우트에 부착한다.

    반환되는 의존성은 경로 파라미터 ``id: int``(문서 id)를 받아 `get_workspace_id` 로
    소속 workspace_id 를 확정한다. 문서가 없으면(``None``) s01 판정에 앞서 404
    ``DomainError(NOT_FOUND)`` 를 raise 한다. 존재하면 s01 ``require_ws_role(minimum)`` 이
    돌려준 내부 의존성에 ``workspace_id`` 를 넘겨 위임한다 — 충족 시 ``AuthContext`` 를 그대로
    돌려주고, 미충족·비멤버는 s01 이 표준 403 을 raise 하며, admin 은 s01 이 bypass 시킨다
    (INV-1·2·3). 위계·bypass·403 판정은 모두 s01 소유이며 여기서 재구현하지 않는다.
    """
    _delegate = _s01_require_ws_role(minimum)

    def dependency(
        id: int,
        ctx: AuthContext = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> AuthContext:
        # 문서 id → workspace_id 매핑을 판정보다 먼저 수행한다: 문서 자체가 없으면
        # role 판정(403)이 아니라 404 를 낸다.
        workspace_id = _repository.get_workspace_id(db, id)
        if workspace_id is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="Document not found",
                http_status=404,
            )
        # s01 내부 의존성은 평범한 sync 함수이므로 직접 호출한다. 위계·bypass·403 판정은
        # 전적으로 s01 에 위임한다(재구현 없음).
        return _delegate(workspace_id=workspace_id, ctx=ctx, db=db)

    return dependency
