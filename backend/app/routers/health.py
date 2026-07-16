"""상태 점검(health) 라우터 (Requirement 8.2, 8.3).

``GET /health`` 는 애플리케이션 가용 상태(`status:"ok"`, Req 8.2)와 경량
``SELECT 1`` 기반 DB 연결 여부(`db:"ok"|"down"`, Req 8.3)를 반영한다. DB
점검이 실패해도 이는 실패가 아니라 준비 상태(readiness) 신호이므로 예외를
전파하지 않고 200으로 응답하되 ``db="down"`` 을 반영한다.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.common.db import get_db

router = APIRouter()


class HealthRead(BaseModel):
    """상태 점검 응답 계약 (Req 8.2, 8.3)."""

    status: str
    db: str  # 경량 SELECT 1 결과: "ok"(연결 성공) | "down"(연결 실패).


@router.get("/health", response_model=HealthRead)
def health(db: Session = Depends(get_db)) -> HealthRead:
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:  # noqa: BLE001 - 모든 DB/연결 오류는 준비 상태 "down"으로 처리
        db_status = "down"
    return HealthRead(status="ok", db=db_status)
