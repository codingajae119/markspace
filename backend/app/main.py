"""FastAPI 애플리케이션 부트스트랩 (Requirement 8).

``create_app()`` 은 공용 인프라(단일 Settings 로드·세션 미들웨어·공통 에러
핸들러·health 라우터)를 조립하고, 하위 spec(s02~s14)이 자신의 라우터를 추가할
비어 있는 조립 지점을 제공한다. 이 spec은 feature 라우터의 동작을 구현하지
않는다(8.4). 모든 요청은 단일 Settings·공통 에러 계약·세션 미들웨어를
거친다(8.5, 8.6).
"""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
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
from app.user_settings.router import router as user_settings_router
from app.workspace.admin_router import router as workspace_admin_router
from app.workspace.router import router as workspace_router

# 전송(HTTP) 네임스페이스. 모든 API 는 이 버전 prefix 하위에 마운트된다. 각 라우터
# 데코레이터 경로(`/auth/login` 등)와 콘텐츠에 박히는 논리 참조 토큰
# (`/attachments/{id}`·`/public/{token}`)은 prefix 를 포함하지 않으며, 실제 발신 시
# 프론트 `apiConfig.baseUrl`(또는 테스트 클라이언트)이 이 prefix 를 앞에 붙인다.
API_V1_PREFIX = "/api/1.0"


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
    # 모든 라우터를 단일 버전 네임스페이스(`/api/1.0`) 하위에 조립한다. 각 라우터의
    # 경로는 그대로 두고 전송 prefix 만 이 조립 지점에서 일괄 부여한다(라우터 데코레이터
    # 는 prefix 를 모른다 — 단위 라우터 테스트는 bare 라우터를 그대로 검증).
    api = APIRouter(prefix=API_V1_PREFIX)
    api.include_router(health_router)
    # feature 라우터 조립 지점: s02~s14가 여기에 include_router로 추가한다
    # (s01 Req 8.4는 이 지점을 비운 채 제공했고, s02가 auth 라우터를, s03가 admin_account
    # 라우터를 등록한다).
    api.include_router(auth_router)
    api.include_router(admin_account_router)
    api.include_router(workspace_router)
    api.include_router(workspace_admin_router)
    api.include_router(document_router)
    api.include_router(lock_version_router)
    api.include_router(trash_router)
    api.include_router(attachment_router)
    api.include_router(sharing_router)
    # user_setting additive 확장: 본인 설정 조회·수정(/me/settings).
    api.include_router(user_settings_router)
    app.include_router(api)
    return app


app = create_app()
