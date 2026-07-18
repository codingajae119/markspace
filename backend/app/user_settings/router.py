"""user_settings HTTP 라우터.

`GET /me/settings`·`PATCH /me/settings` 의 HTTP 결선을 소유한다. 요청 본문 파싱·
상태코드만 담당하고, 조회·부분 수정의 **동작**은 :class:`UserSettingsService` 에
위임한다. 두 엔드포인트 모두 s01 ``get_current_user`` 로 인증을 강제하며(미인증·
비활동·삭제 세션은 401), 대상은 항상 인증된 본인(``ctx.user_id``)으로 한정된다.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.auth import AuthContext, get_current_user
from app.common.db import get_db
from app.user_settings.repository import UserSettingRepository
from app.user_settings.schemas import UserSettingsRead, UserSettingsUpdate
from app.user_settings.service import UserSettingsService

__all__ = ["router", "get_user_settings_service"]

router = APIRouter()


def get_user_settings_service(
    db: Session = Depends(get_db),
) -> UserSettingsService:
    """요청 스코프 세션으로 UserSettingsService 를 조립하는 의존성 provider.

    테스트는 ``app.dependency_overrides[get_user_settings_service]`` 로 이 provider
    를 대체하여 DB 없이 라우터 결선만 검증할 수 있다(auth 패턴).
    """
    return UserSettingsService(UserSettingRepository(db))


@router.get("/me/settings", response_model=UserSettingsRead)
def get_my_settings(
    service: UserSettingsService = Depends(get_user_settings_service),
    ctx: AuthContext = Depends(get_current_user),
) -> UserSettingsRead:
    """현재 인증된 사용자 본인 설정을 조회한다.

    ``get_current_user`` 로 인증을 강제한다(미인증 401). 레코드가 없으면 서비스가
    공용 Settings 기본값으로 채운 응답을 반환한다.
    """
    return service.get(ctx)


@router.patch("/me/settings", response_model=UserSettingsRead)
def update_my_settings(
    payload: UserSettingsUpdate,
    service: UserSettingsService = Depends(get_user_settings_service),
    ctx: AuthContext = Depends(get_current_user),
) -> UserSettingsRead:
    """현재 인증된 사용자 본인 설정을 부분 수정한다.

    대상은 항상 ``ctx.user_id`` 로 한정된다(본인 것만). ``get_current_user`` 로
    인증을 강제하며(미인증 401), 성공 시 갱신된 설정을 200 으로 반환한다.
    """
    return service.update(ctx, payload)
