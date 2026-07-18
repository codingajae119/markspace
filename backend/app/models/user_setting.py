"""``user_setting`` 테이블 ORM 모델 (s01 계약에 대한 additive 확장).

사용자별 개인 설정을 ``user`` 테이블에 컬럼을 추가하지 않고 별도 1:1 테이블로
분리해 보관한다(비파괴적 확장). ``user_id`` 는 FK + UNIQUE 로 사용자당 최대 한 행을
보장한다. 레코드가 없을 때의 값은 저장하지 않고 서비스 계층이 공용 Settings
기본값(``default_autosave_enabled``)으로 대체한다.
"""

from sqlalchemy import BigInteger, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class UserSetting(Base):
    __tablename__ = "user_setting"
    __table_args__ = ({"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 사용자당 1행(UNIQUE). soft-delete 대상 아님(설정은 사용자 생명주기에 종속).
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user.id"), nullable=False, unique=True
    )
    autosave_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
