"""인증 범위 user 데이터 접근 (s02-auth design.md §auth/Data #AuthUserRepository).

인증 목적의 user 조회와 본인 ``password_hash`` 갱신만 소유한다. s01 ``User`` 모델과
요청 스코프 세션(``get_db``)을 재사용하며 재정의하지 않는다(Req 5.1).

경계(design.md §Out of Boundary):
- ``find_by_login_id`` 는 상태(``is_active``/``is_deleted``)로 **필터링하지 않는다**.
  상태 게이트 판정은 AuthService 가 수행하여 동일한 401 응답으로 통제한다(계정 열거 방지).
- 계정 생성·삭제·플래그 전환 등 계정 생명주기 mutation 은 s03 소유이며 여기서 수행하지 않는다.
  이 저장소는 읽기와 본인 ``password_hash`` 갱신만 한다.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User

__all__ = ["AuthUserRepository"]


class AuthUserRepository:
    """인증 범위 user 조회·본인 password_hash 갱신 (Req 1.1, 4.1)."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def find_by_login_id(self, login_id: str) -> User | None:
        """``login_id`` 로 사용자를 조회한다. 상태 무관(active/deleted 필터 없음).

        상태 게이트는 AuthService 가 수행하므로(동일 401 통제) 여기서는 비활동·삭제
        사용자도 그대로 반환한다. 일치하는 사용자가 없으면 None 을 반환한다(Req 1.1).
        """
        return self._db.scalar(select(User).where(User.login_id == login_id))

    def get_by_id(self, user_id: int) -> User | None:
        """PK 로 사용자를 로드한다. 없으면 None 을 반환한다(Req 4.1)."""
        return self._db.get(User, user_id)

    def update_password_hash(self, user: User, password_hash: str) -> None:
        """본인 ``password_hash`` 를 새 해시로 교체하고 commit 하여 영속화한다(Req 4.1).

        평문 저장 금지: 호출부는 s01 해싱 헬퍼가 만든 해시만 전달한다.
        """
        user.password_hash = password_hash
        self._db.commit()
