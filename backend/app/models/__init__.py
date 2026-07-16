"""ORM 모델 패키지 (design.md §File Structure Plan, Req 1.1).

모든 모델 클래스를 import 하여 ``Base.metadata`` 에 7개 테이블을 등록하고,
``Base`` 및 각 모델을 재노출한다. Alembic 은 ``Base.metadata`` 를 target 으로
사용한다(app.common.db). 모델은 services/routers/errors 를 import 하지 않는다.
"""

from app.common.db import Base
from app.models.attachment import Attachment
from app.models.document import Document, DocumentVersion
from app.models.share_link import ShareLink
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

__all__ = [
    "Base",
    "User",
    "Workspace",
    "WorkspaceMember",
    "Document",
    "DocumentVersion",
    "Attachment",
    "ShareLink",
]
