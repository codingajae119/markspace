"""공용 Read 스키마 규약(Base Schemas) 단위 테스트 (Requirement 6.2, 6.5).

ORM 객체(from_attributes)로부터 ``TimestampedRead`` 가 직렬화되고,
``Page[T]`` 가 items/total 을 담으며, ``{Resource}Read`` 명명 규약대로
``TimestampedRead`` 를 상속한 하위 스키마가 동작함을 관찰 가능하게 검증한다.
ORM 행을 흉내내기 위해 속성만 가진 단순 스탠드인(``SimpleNamespace``/더미 클래스)을 사용한다.
"""

from datetime import datetime
from types import SimpleNamespace

from app.schemas.base import ORMReadModel, Page, TimestampedRead


def test_ormreadmodel_enables_from_attributes() -> None:
    """ORMReadModel 은 from_attributes=True 를 활성화한다 (Req 6.5)."""
    assert ORMReadModel.model_config.get("from_attributes") is True


def test_timestamped_read_validates_from_orm_object() -> None:
    """속성 기반 ORM 유사 객체에서 TimestampedRead 가 직렬화된다 (Req 6.5)."""
    created = datetime(2026, 1, 1, 12, 0, 0)
    updated = datetime(2026, 1, 2, 9, 30, 0)
    row = SimpleNamespace(id=7, created_at=created, updated_at=updated)

    model = TimestampedRead.model_validate(row)

    assert model.id == 7
    assert model.created_at == created
    assert model.updated_at == updated


def test_timestamped_read_updated_at_defaults_to_none() -> None:
    """updated_at 이 없으면 None 으로 기본 설정된다 (Req 6.5)."""
    row = SimpleNamespace(id=1, created_at=datetime(2026, 1, 1))

    model = TimestampedRead.model_validate(row)

    assert model.id == 1
    assert model.updated_at is None


def test_page_holds_items_and_total() -> None:
    """Page[T] 는 items 리스트와 total 정수를 담고 model_dump 형태가 일치한다 (observable-done)."""
    item = TimestampedRead(id=1, created_at=datetime(2026, 1, 1), updated_at=None)
    page: Page[TimestampedRead] = Page[TimestampedRead](items=[item], total=1)

    assert page.total == 1
    assert isinstance(page.items, list)
    assert page.items[0].id == 1

    dumped = page.model_dump()
    assert dumped["total"] == 1
    assert isinstance(dumped["items"], list)
    assert len(dumped["items"]) == 1
    assert dumped["items"][0]["id"] == 1


def test_page_generic_parameterization_round_trips() -> None:
    """Page[T] 의 제네릭 파라미터화가 JSON 검증까지 왕복한다 (observable-done)."""
    payload = {
        "items": [
            {"id": 2, "created_at": "2026-03-04T00:00:00", "updated_at": None}
        ],
        "total": 1,
    }

    page = Page[TimestampedRead].model_validate(payload)

    assert page.total == 1
    assert page.items[0].id == 2
    assert isinstance(page.items[0], TimestampedRead)


def test_read_naming_convention_subclass_from_orm_object() -> None:
    """{Resource}Read 규약: TimestampedRead 를 상속한 하위 스키마가 검증된다 (Req 6.2)."""

    class WidgetRead(TimestampedRead):
        name: str

    row = SimpleNamespace(
        id=42,
        created_at=datetime(2026, 5, 5),
        updated_at=None,
        name="gadget",
    )

    model = WidgetRead.model_validate(row)

    assert model.id == 42
    assert model.name == "gadget"
    assert model.updated_at is None
