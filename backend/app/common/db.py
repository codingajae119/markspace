"""SQLAlchemy 공통 데이터 계층 (Requirement 1.9, 8.3).

선언적 ``Base``, 단일 ``engine``·세션 팩토리(``SessionLocal``), 요청 스코프
세션 의존성 ``get_db`` 를 정의한다. 접속 정보는 오직 :func:`app.config.get_settings`
를 통해서만 조립된다(하드코딩 금지).

의존 방향: Config → Db. 이 모듈은 어떤 feature/model 도메인도 import 하지
않는다. ORM 모델 클래스는 별도 ``models`` 패키지가 정의하며, 그때 채워지는
``Base.metadata`` 를 Alembic 이 target 으로 사용한다.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """모든 ORM 모델의 선언적 기반 클래스.

    ``models`` 패키지가 하위 클래스를 정의하며 ``Base.metadata`` 를 채운다.
    """


engine = create_engine(get_settings().sqlalchemy_url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """요청 스코프 세션을 yield 하고 종료 시 반드시 close 한다.

    FastAPI 의존성으로 사용된다. 요청 처리 종료(정상·예외 무관) 시점에
    세션을 close 하여 커넥션을 풀로 반환한다.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
