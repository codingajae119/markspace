"""UserRepository: user 테이블 조회·생성·flag 전환 접근 (design.md §UserRepository).

s01 user 모델·`get_db` 세션을 사용하며 물리 DELETE 를 절대 발행하지 않는다(INV-4).
삭제·비활동은 flag 컬럼(`is_deleted`·`is_active`) 갱신으로만 표현한다.

계약 주의(design.md §UserRepository): 세션(`db`)은 메서드마다 인자로 전달받는다
(생성자 주입 아님 — s02 `AuthUserRepository` 와 다르며 s03 설계 계약을 따른다). 쓰기
메서드는 commit 하여 별도 세션 재조회가 변경을 관찰하도록 내구 영속화한다(s02
`app/auth/repository.py::update_password_hash` 의 영속 보증과 정합).

경계: s01(`app.models.User`, sqlalchemy, stdlib)만 import 하며 다른 feature 도메인을
import 하지 않는다. s01 `common`·`models` 를 수정하지 않는다.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User

__all__ = ["UserRepository"]

# apply_updates 가 부분 갱신할 수 있는 필드 화이트리스트.
# is_admin 은 애플리케이션 경로 승격·강등 차단(D3)을 위해 제외한다.
_WRITABLE_FIELDS = frozenset({"name", "email", "is_active", "is_deleted"})


class UserRepository:
    """user 조회·생성·flag 전환 데이터 접근 (Req 2.2, 3.1, 3.3, 3.4, 4.1, 5.1, 6.1, 7.1).

    세션은 메서드별 인자로 전달받는다. 쓰기 메서드는 commit 으로 영속화한다.
    """

    def get_by_id(self, db: Session, user_id: int) -> User | None:
        """PK 로 사용자를 로드한다. 없으면 None 을 반환한다(Req 4.1)."""
        return db.get(User, user_id)

    def get_by_login_id(self, db: Session, login_id: str) -> User | None:
        """`login_id` 로 사용자를 조회한다. 없으면 None 을 반환한다(Req 2.4)."""
        return db.scalar(select(User).where(User.login_id == login_id))

    def list_paginated(
        self, db: Session, limit: int, offset: int
    ) -> tuple[list[User], int]:
        """계정 목록을 페이지네이션하여 (items, total) 로 반환한다(Req 3.1·3.3·3.4).

        삭제(`is_deleted`)·비활동(`is_active`) 계정을 제외하지 않는다(관리 대상 노출).
        `total` 은 삭제·비활동 포함 전체 개수이며 `limit`/`offset` 은 items 에만 적용한다.
        """
        total = db.scalar(select(func.count()).select_from(User)) or 0
        items = list(
            db.scalars(
                select(User).order_by(User.id).limit(limit).offset(offset)
            )
        )
        return items, total

    def create(
        self,
        db: Session,
        *,
        login_id: str,
        password_hash: str,
        name: str,
        email: str | None,
    ) -> User:
        """신규 사용자를 기본 상태로 생성하고 commit 하여 영속화한다(Req 2.2).

        기본값은 `is_admin=False`·`is_active=True`·`is_deleted=False` 이며 `created_at`
        을 설정한다(User 모델에 created_at 서버 기본값 없음). `password_hash` 는 이미
        해싱된 값이며 저장소는 해싱하지 않는다(호출부가 해싱).
        """
        user = User(
            login_id=login_id,
            password_hash=password_hash,
            name=name,
            email=email,
            is_admin=False,
            is_active=True,
            is_deleted=False,
            created_at=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def apply_updates(self, db: Session, user: User, changes: dict) -> User:
        """제공된 키만 부분 갱신하고 commit 하여 영속화한다(Req 4.1·4.5·5.1·6.1·6.2).

        갱신 가능 필드는 `name`·`email`·`is_active`·`is_deleted` 로 한정한다. `is_admin`
        은 화이트리스트에서 제외되어 애플리케이션 경로로 변경되지 않는다(D3). `is_active`
        와 `is_deleted` 는 독립적으로 취급되어 한 flag 전환이 다른 flag 를 건드리지 않는다.
        물리 삭제는 발행하지 않으며 삭제는 `is_deleted=True` flag 로만 표현한다(INV-4).
        """
        for key, value in changes.items():
            if key in _WRITABLE_FIELDS:
                setattr(user, key, value)
        user.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
        return user

    def set_password_hash(
        self, db: Session, user: User, password_hash: str
    ) -> User:
        """`password_hash` 를 새 해시로 교체하고 commit 하여 영속화한다(Req 7.1).

        평문 저장 금지: 호출부는 s01 해싱 헬퍼가 만든 해시만 전달한다.
        """
        user.password_hash = password_hash
        user.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(user)
        return user
