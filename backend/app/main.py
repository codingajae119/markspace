"""FastAPI 애플리케이션 부트스트랩 (Requirement 8).

``create_app()`` 은 공용 인프라(단일 Settings 로드·세션 미들웨어·공통 에러
핸들러·health 라우터)를 조립하고, 하위 spec(s02~s14)이 자신의 라우터를 추가할
비어 있는 조립 지점을 제공한다. 이 spec은 feature 라우터의 동작을 구현하지
않는다(8.4). 모든 요청은 단일 Settings·공통 에러 계약·세션 미들웨어를
거친다(8.5, 8.6).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.admin_account.router import router as admin_account_router
from app.attachment import scheduler as attachment_scheduler
from app.attachment.router import router as attachment_router
from app.auth.router import router as auth_router
from app.common.errors import register_error_handlers
from app.config import get_settings
from app.document.router import router as document_router
from app.lock_version.router import router as lock_version_router
from app.routers.health import router as health_router
from app.sharing import scheduler as sharing_scheduler
from app.sharing.router import router as sharing_router
from app.trash import scheduler as trash_scheduler
from app.trash.router import router as trash_router
from app.workspace.admin_router import router as workspace_admin_router
from app.workspace.router import router as workspace_router


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """앱 lifespan startup/shutdown 에 s10 보관 스윕·s12 아카이브 스윕·s14 무효화 스윕 스케줄러를 연결한다 (Req 6.5, s12 7.4, s14 7.4).

    startup 에서 ``trash_scheduler.start(app)``·``attachment_scheduler.start(app)``·
    ``sharing_scheduler.start(app)`` 를 호출하고 shutdown 에서 각각 ``stop()`` 으로 정리한다.
    조립·lifespan 방식은 s01·s05·s07·s10·s12 를 따른다.
    """
    trash_scheduler.start(app)
    attachment_scheduler.start(app)
    sharing_scheduler.start(app)
    try:
        yield
    finally:
        sharing_scheduler.stop()
        attachment_scheduler.stop()
        trash_scheduler.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=_lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie=settings.session_cookie_name,
        max_age=settings.session_max_age_seconds,
        same_site="lax",
    )
    register_error_handlers(app)
    app.include_router(health_router)
    # feature 라우터 조립 지점: s02~s14가 여기에 include_router로 추가한다
    # (s01 Req 8.4는 이 지점을 비운 채 제공했고, s02가 auth 라우터를, s03가 admin_account
    # 라우터를 등록한다).
    app.include_router(auth_router)
    app.include_router(admin_account_router)
    app.include_router(workspace_router)
    app.include_router(workspace_admin_router)
    app.include_router(document_router)
    app.include_router(lock_version_router)
    app.include_router(trash_router)
    app.include_router(attachment_router)
    app.include_router(sharing_router)
    return app


app = create_app()
