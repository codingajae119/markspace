"""AdminAccountService: 계정 생성·목록·상태 전이·비밀번호 재설정 로직
(design.md §Components and Interfaces #AdminAccountService, §System Flows).

UserRepository(생성자 주입)·s01 Security(해싱)·s01 Errors(도메인 오류) 를 소비한다.
세션(`db`)은 s03 계약에 따라 메서드별 인자로 전달받아 repo 로 그대로 넘긴다.

경계(design.md §Dependency Direction): 이 서비스는 UserRepository·s01 `common`·s03
`schemas` 만 소비하며 라우터·다른 feature 를 import 하지 않는다. 스키마 검증(필수·형식)은
pydantic 이 라우터 계층에서 422 로 처리하므로 서비스는 재검증하지 않는다. login_id 중복
(409)·대상 미존재(404)·단일 admin 잠금(409) 만 서비스의 도메인 판정이다.
"""

from sqlalchemy.orm import Session

from app.admin_account.repository import UserRepository
from app.admin_account.schemas import (
    AdminPasswordResetRequest,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.common.errors import DomainError, ErrorCode
from app.common.security import hash_password
from app.schemas.base import Page

__all__ = ["AdminAccountService"]


class AdminAccountService:
    """계정 생명주기(생성·목록·상태 전이·비밀번호 재설정) 비즈니스 로직.

    저장소는 생성자 주입(s02 `AuthService.__init__(self, repo)` 정합)하고, DB 세션은
    메서드별 인자로 전달받는다(s03 UserRepository 계약).
    """

    def __init__(self, repo: UserRepository) -> None:
        self._repo = repo

    def create_user(self, db: Session, payload: UserCreate) -> UserRead:
        """신규 계정을 생성한다 (Req 2.1·2.2·2.3·2.4).

        login_id 가 이미 존재하면 계정을 만들지 않고 409 로 거부한다(Req 2.4). 그렇지
        않으면 평문 비밀번호를 s01 `hash_password` 로 해싱해(평문 저장 금지, Req 2.3)
        저장소에 위임하며, 기본 상태(`is_active=True`·`is_deleted=False`·`is_admin=False`)
        는 저장소가 설정한다(Req 2.2). 관리자 표시·상태 flag 는 입력받지 않아 승격을
        원천 차단한다(D3, Req 2.6).
        """
        if self._repo.get_by_login_id(db, payload.login_id) is not None:
            raise DomainError(
                code=ErrorCode.CONFLICT,
                message="login_id already exists",
                http_status=409,
            )

        user = self._repo.create(
            db,
            login_id=payload.login_id,
            password_hash=hash_password(payload.password),
            name=payload.name,
            email=payload.email,
        )
        return UserRead.model_validate(user)

    def list_users(self, db: Session, limit: int, offset: int) -> Page[UserRead]:
        """계정 목록을 페이지네이션하여 공통 `Page` 엔벨로프로 반환한다 (Req 3.1·3.3·3.4).

        삭제·비활동 계정도 제외하지 않으며(관리 대상 노출), `total` 은 저장소가 계산한
        전체(삭제 포함) 개수를 그대로 전달한다.
        """
        items, total = self._repo.list_paginated(db, limit, offset)
        return Page[UserRead](
            items=[UserRead.model_validate(user) for user in items],
            total=total,
        )

    def update_user(
        self, db: Session, user_id: int, changes: UserUpdate
    ) -> UserRead:
        """계정 상태·필드를 부분 갱신한다 (Req 4.1·4.4·4.5·5.1·5.5·6.1·6.2).

        대상을 로드해 없으면 404 로 거부한다(Req 4.3·5.4·6.3). 대상이 관리자
        (`is_admin=True`)이고 요청이 **비활성 방향**(`is_active` 를 False 로 또는
        `is_deleted` 를 True 로) 전환하면 단일 admin 잠금 방지를 위해 409 로 거부하며
        영속하지 않는다(Req 4.4·5.5). 재활성화(`is_deleted=False`)·재활동
        (`is_active=True`)·이름/이메일 편집은 admin 대상에도 허용한다.

        갱신은 명시적으로 제공된 필드만(`model_dump(exclude_unset=True)`) 저장소에
        위임한다. `is_active`·`is_deleted` 는 독립적으로 취급되어 한 flag 전환이 다른
        flag 를 건드리지 않는다(Req 4.5·6.2).
        """
        user = self._repo.get_by_id(db, user_id)
        if user is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="User not found",
                http_status=404,
            )

        update_fields = changes.model_dump(exclude_unset=True)

        # 단일 admin 잠금 방지: 관리자 대상은 비활성 방향 전환만 거부한다. 재활성화·
        # 재활동·이름/이메일 편집은 허용하므로 명시적으로 제공된 값만 검사한다(Req 4.4·5.5).
        if user.is_admin and (
            update_fields.get("is_active") is False
            or update_fields.get("is_deleted") is True
        ):
            raise DomainError(
                code=ErrorCode.CONFLICT,
                message="Cannot deactivate or delete an admin account",
                http_status=409,
            )

        updated = self._repo.apply_updates(db, user, update_fields)
        return UserRead.model_validate(updated)

    def reset_password(
        self, db: Session, user_id: int, req: AdminPasswordResetRequest
    ) -> None:
        """대상 사용자의 비밀번호를 새 값으로 재설정한다 (Req 7.1·7.2·7.4).

        대상을 로드해 없으면 404 로 거부한다(Req 7.4). 새 비밀번호는 s01 `hash_password`
        로 해싱하여 저장한다(평문 저장 금지, Req 7.2). admin 전용 경로이며(라우터 게이트),
        사용자 self-reset 인자는 노출하지 않는다(Req 7.3).
        """
        user = self._repo.get_by_id(db, user_id)
        if user is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="User not found",
                http_status=404,
            )

        self._repo.set_password_hash(db, user, hash_password(req.new_password))
