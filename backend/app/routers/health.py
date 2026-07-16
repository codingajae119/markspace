"""상태 점검(health) 라우터 (Requirement 8.2, 8.3).

이 파일은 부트스트랩(task 4.1)이 라우터 조립 지점에 포함할 수 있도록 만든
최소 스텁이다. 실제 DB 연결 점검(경량 ``SELECT 1``, 실패 시 ``db="down"``,
Req 8.3)은 task 4.2가 이 핸들러를 대체하며 소유한다. 현재는 앱이 부팅되고
라우터가 조립되었음을 확인할 수 있도록 고정값을 반환한다.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class HealthRead(BaseModel):
    """상태 점검 응답 계약 (Req 8.2, 8.3)."""

    status: str
    db: str  # task 4.2가 실제 DB 연결 점검 결과("ok"|"down")로 채운다.


@router.get("/health", response_model=HealthRead)
def health() -> HealthRead:
    # NOTE: db는 임시 고정값이다. task 4.2가 실제 DB 연결 점검으로 대체한다.
    return HealthRead(status="ok", db="ok")
