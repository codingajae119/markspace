"""공용 Read 스키마 규약(Base Schemas) — 계약 계층의 순수 타입.

리소스별 요청/응답 스키마 명명 규약과 Read 공통 필드 베이스를 단일 소스로 정의한다
(Requirement 6.2, 6.5). 각 feature spec 은 이 베이스를 상속해 구체 스키마를 정의한다.

명명 규약 (Req 6.2)
-------------------
- ``{Resource}Create`` — 생성 요청 본문. 서버가 채우는 식별자/타임스탬프는 포함하지 않는다.
- ``{Resource}Read``   — 응답 스키마. id·타임스탬프를 가지면 ``TimestampedRead`` 를 상속한다.
- ``{Resource}Update`` — 부분 수정 요청 본문. 필드는 선택적(Optional)으로 정의한다.
- 목록 응답은 ``Page[{Resource}Read]`` 제네릭 엔벨로프를 사용한다.

Read 공통 필드 규약 (Req 6.5)
----------------------------
식별자/타임스탬프처럼 여러 Read 스키마가 공유하는 필드는 ``TimestampedRead`` 에
한 번만 정의해 스키마 중복을 방지한다.

경계(Boundary)
--------------
이 모듈은 pydantic/stdlib 만 import 하는 순수 계약 타입이다. db/models/auth/feature 를
import 하지 않는다. ORM 객체는 ``from_attributes`` 로 덕 타이핑되어 직렬화되므로
ORM 모델 클래스를 직접 참조하지 않는다.
"""

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

__all__ = ["ORMReadModel", "TimestampedRead", "Page"]


class ORMReadModel(BaseModel):
    """ORM 속성 객체로부터 검증을 허용하는 Read 스키마 베이스.

    ``from_attributes=True`` 로 ``model_validate(orm_obj)`` 가 속성 접근으로 동작한다.
    """

    model_config = ConfigDict(from_attributes=True)


class TimestampedRead(ORMReadModel):
    """id 와 생성/수정 타임스탬프를 공통 제공하는 Read 베이스 (Req 6.5).

    ``{Resource}Read`` 스키마는 이 클래스를 상속하고 리소스 고유 필드만 추가한다.
    """

    id: int
    created_at: datetime
    updated_at: datetime | None = None


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """목록 응답 공통 엔벨로프.

    ``items`` 는 페이지 항목 리스트, ``total`` 은 전체 개수다.
    """

    items: list[T]
    total: int
