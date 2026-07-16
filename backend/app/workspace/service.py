"""워크스페이스·멤버십 서비스 (design.md §Feature/Service).

`WorkspaceService`·`MembershipService` 가 생성(owner화)·목록·상세·설정·삭제 및 멤버 추가·
role 변경·제거·admin 소유권 변경 로직을 담당한다. 현재 `WorkspaceService`(task 2.3)만
구현되어 있고 `MembershipService`(task 2.4)는 후속 task 에서 이 모듈에 추가된다.

경계(design.md §Dependency Direction): 서비스는 `WorkspaceRepository`·`MembershipRepository`
(생성자 주입)·s01 `common`·s05 `schemas` 만 소비하며 라우터·다른 feature 를 import 하지 않는다.
저장소는 생성자 주입(s02 `AuthService`·s03 `AdminAccountService` 정합)하고, DB 세션은 메서드별
인자로 전달받아 repo 로 그대로 넘긴다(s05 Repository 계약). 스키마 형식 검증(필수·형식·공백)은
pydantic 이 라우터 계층에서 422 로 처리하므로 서비스는 재검증하지 않는다. 도메인 판정만 담당한다:
미존재(404)·비-empty 삭제(409)·trash_retention_days≤0(422).
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.auth import AuthContext
from app.common.errors import DomainError, ErrorCode, FieldError
from app.config import get_settings
from app.schemas.base import Page
from app.workspace.repository import MembershipRepository, WorkspaceRepository
from app.workspace.schemas import (
    MemberCreate,
    MemberRead,
    MemberUpdate,
    OwnerChangeRequest,
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceUpdate,
)

__all__ = ["WorkspaceService", "MembershipService"]


class WorkspaceService:
    """워크스페이스 생성(owner화)·목록·상세·설정·삭제 비즈니스 로직
    (design.md §Components → WorkspaceService, Req 1.1~1.6, 2.1~2.5, 2.7, 6.6).

    저장소는 생성자 주입하고 DB 세션은 메서드별 인자로 전달받는다. 도메인 오류는 s01
    `DomainError` 로 raise 하며 s01 전역 핸들러가 공통 `ErrorResponse` 로 변환한다.
    """

    def __init__(
        self, ws_repo: WorkspaceRepository, member_repo: MembershipRepository
    ) -> None:
        self._ws_repo = ws_repo
        self._member_repo = member_repo

    def create_workspace(
        self, db: Session, ctx: AuthContext, payload: WorkspaceCreate
    ) -> WorkspaceRead:
        """워크스페이스를 생성하고 요청자를 owner 멤버로 등록한다 (Req 1.1·1.2·6.6).

        기본 `trash_retention_days` 는 s01 단일 `Settings`(`default_trash_retention_days`)에서
        읽어 적용하며(단일 접근자 `get_settings()` 경유), `is_shareable=False` 강제는 저장소가
        담당한다. 워크스페이스 insert 직후 요청자를 owner role 멤버로 등록한다. 관찰 가능한
        사후조건은 워크스페이스와 owner 멤버십이 함께 존재함이다(design.md 생성 흐름).
        """
        workspace = self._ws_repo.create(
            db,
            name=payload.name,
            trash_retention_days=get_settings().default_trash_retention_days,
        )
        self._member_repo.add(
            db, workspace_id=workspace.id, user_id=ctx.user_id, role="owner"
        )
        return WorkspaceRead.model_validate(workspace)

    def list_workspaces(
        self, db: Session, ctx: AuthContext, limit: int, offset: int
    ) -> Page[WorkspaceRead]:
        """워크스페이스 목록을 공통 `Page` 엔벨로프로 반환한다 (Req 1.3·1.4).

        admin 은 전체 워크스페이스를(`list_all`), 비-admin 은 요청자가 멤버인 워크스페이스만
        (`list_for_user`) 조회한다. `total` 은 저장소가 계산한 스코프 전체 개수를 그대로 전달한다.
        """
        if ctx.is_admin:
            items, total = self._ws_repo.list_all(db, limit, offset)
        else:
            items, total = self._ws_repo.list_for_user(db, ctx.user_id, limit, offset)
        return Page[WorkspaceRead](
            items=[WorkspaceRead.model_validate(ws) for ws in items],
            total=total,
        )

    def get_workspace(self, db: Session, workspace_id: int) -> WorkspaceRead:
        """워크스페이스 상세를 조회한다 (Req 1.5·1.6).

        대상을 로드해 없으면 404 로 거부한다. 권한 게이트(viewer 이상)는 라우터의
        `require_ws_role(VIEWER)` 가 담당하며 서비스의 책임이 아니다.
        """
        workspace = self._ws_repo.get_by_id(db, workspace_id)
        if workspace is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="Workspace not found",
                http_status=404,
            )
        return WorkspaceRead.model_validate(workspace)

    def update_workspace(
        self, db: Session, workspace_id: int, changes: WorkspaceUpdate
    ) -> WorkspaceRead:
        """워크스페이스 설정을 부분 갱신한다 (Req 2.1·2.2·2.3·2.4·1.6).

        대상을 로드해 없으면 404 로 거부한다. 명시적으로 제공된 필드만
        (`model_dump(exclude_unset=True)`) 갱신한다. `trash_retention_days` 가 제공되면 양의
        정수(>0)여야 하며, ≤0 이면 422 로 거부하고 아무것도 영속하지 않는다(design.md error
        table: trash_retention_days≤0 → 422 validation_error). 검증 통과 후 저장소에 위임한다.
        """
        workspace = self._ws_repo.get_by_id(db, workspace_id)
        if workspace is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="Workspace not found",
                http_status=404,
            )

        update_fields = changes.model_dump(exclude_unset=True)

        # trash_retention_days 양의 정수 검증: 제공된 경우에만 검사하고 위반 시 영속 없이 422.
        # 명시적 null(None)은 NOT NULL 컬럼에 부적합하므로 ≤0 과 동일하게 거부한다(None<=0
        # TypeError 로 인한 500 방지). None 검사를 <=0 앞에 두어 단락 평가한다.
        if "trash_retention_days" in update_fields and (
            update_fields["trash_retention_days"] is None
            or update_fields["trash_retention_days"] <= 0
        ):
            raise DomainError(
                code=ErrorCode.VALIDATION_ERROR,
                message="trash_retention_days must be positive",
                http_status=422,
                field_errors=[
                    FieldError(
                        field="trash_retention_days",
                        message="must be a positive integer",
                    )
                ],
            )

        updated = self._ws_repo.apply_updates(db, workspace, update_fields)
        return WorkspaceRead.model_validate(updated)

    def delete_workspace(self, db: Session, workspace_id: int) -> None:
        """워크스페이스를 삭제한다 — 빈 워크스페이스만 허용 (Req 2.5·2.7·1.6).

        대상을 로드해 없으면 404 로 거부한다. 그렇지 않으면 멤버십을 전부 제거한 뒤 워크스페이스를
        물리 삭제한다(단일 논리 트랜잭션). 문서가 남은 비-empty 워크스페이스는 s01 FK
        `ON DELETE RESTRICT` 위반으로 물리 DELETE 가 `IntegrityError` 를 일으키며, 이를 rollback
        후 `DomainError(CONFLICT, 409)` 로 변환해 거부한다(INV-4·FK 정합, design.md 사후조건:
        비-empty 삭제는 409 이며 아무것도 제거되지 않는다).

        L2 시점에는 문서 테이블이 없어 항상 빈 워크스페이스이며 409 경로는 s07 문서 도입 이후
        실효화된다(단위 테스트는 mock IntegrityError 로 변환 경로를 검증, 실 end-to-end 409 는
        체크포인트 s08 로 이연 — design.md Revalidation Triggers / Testing Strategy).
        """
        workspace = self._ws_repo.get_by_id(db, workspace_id)
        if workspace is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="Workspace not found",
                http_status=404,
            )

        try:
            self._member_repo.remove_all_for_workspace(db, workspace_id)
            self._ws_repo.delete(db, workspace)
        except IntegrityError as exc:
            db.rollback()
            raise DomainError(
                code=ErrorCode.CONFLICT,
                message="Cannot delete a non-empty workspace",
                http_status=409,
            ) from exc


class MembershipService:
    """멤버 추가·role 변경·제거 및 admin 소유권 변경 비즈니스 로직
    (design.md §Components → MembershipService, Req 3.1~3.9, 5.1·5.2·5.3·5.5·5.6).

    저장소는 생성자 주입하고 DB 세션은 메서드별 인자로 전달받는다. 도메인 오류는 s01
    `DomainError` 로 raise 하며 s01 전역 핸들러가 공통 `ErrorResponse` 로 변환한다. 권한
    게이팅(require_ws_role/require_admin)은 라우터 의존성이 담당하며 서비스는 데이터 규칙
    (존재·유일·upsert)만 판정한다. role 문자열은 s01 ENUM(owner/editor/viewer)과 동일하게
    `MemberRole` 값(`.value`)으로 저장소에 전달한다. owner 개수에 하한을 두지 않는다(docs 3.7).
    """

    def __init__(
        self, member_repo: MembershipRepository, ws_repo: WorkspaceRepository
    ) -> None:
        self._member_repo = member_repo
        self._ws_repo = ws_repo

    def add_member(
        self, db: Session, workspace_id: int, payload: MemberCreate
    ) -> MemberRead:
        """대상 사용자를 지정 role 의 멤버로 등록한다 (Req 3.1·3.2·3.3·3.4·3.8).

        대상 user 가 존재하지 않으면 404, 이미 해당 워크스페이스 멤버이면 409 로 거부한다.
        잘못된 role 문자열은 pydantic 이 라우터 계층에서 422 로 거부하므로 서비스는 재검증하지
        않는다. role 은 `MemberRole` 값(원시 문자열)으로 저장소에 전달한다.
        """
        if not self._member_repo.user_exists(db, payload.user_id):
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="User not found",
                http_status=404,
            )
        if self._member_repo.get(db, workspace_id, payload.user_id) is not None:
            raise DomainError(
                code=ErrorCode.CONFLICT,
                message="User is already a member",
                http_status=409,
            )
        member = self._member_repo.add(
            db,
            workspace_id=workspace_id,
            user_id=payload.user_id,
            role=payload.role.value,
        )
        return MemberRead.model_validate(member)

    def change_role(
        self, db: Session, workspace_id: int, user_id: int, payload: MemberUpdate
    ) -> MemberRead:
        """멤버의 role 을 갱신한다 (Req 3.5·3.9).

        대상 멤버십이 없으면 404 로 거부한다. 유일/마지막 owner 를 강등해도 하한 가드 없이
        허용한다(Req 3.9) — owner 소실은 editor·viewer 판정에 영향을 주지 않는다.
        """
        member = self._member_repo.get(db, workspace_id, user_id)
        if member is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="Membership not found",
                http_status=404,
            )
        updated = self._member_repo.set_role(db, member, payload.role.value)
        return MemberRead.model_validate(updated)

    def remove_member(self, db: Session, workspace_id: int, user_id: int) -> None:
        """멤버십을 물리적으로 제거한다 (Req 3.6·3.9).

        대상 멤버십이 없으면 404 로 거부한다. 유일/마지막 owner 제거도 하한 가드 없이
        허용한다(Req 3.9).
        """
        member = self._member_repo.get(db, workspace_id, user_id)
        if member is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="Membership not found",
                http_status=404,
            )
        self._member_repo.remove(db, member)

    def change_owner(
        self, db: Session, workspace_id: int, payload: OwnerChangeRequest
    ) -> WorkspaceRead:
        """admin 소유권 변경: 대상 사용자를 owner 로 upsert 한다 (Req 5.1·5.2·5.3·5.5·5.6·3.7).

        워크스페이스가 없으면 404, 대상 user 가 없으면 404 로 거부한다. 대상이 이미 멤버이면
        role 을 owner 로 갱신하고, 비멤버이면 owner role 로 신규 등록한다(upsert-to-owner).
        기존 다른 owner 는 강등하지 않으며(복수 owner 허용), owner 부재 워크스페이스에도 새
        owner 를 지정할 수 있다(Req 5.6). admin 게이트는 라우터 `require_admin` 이 담당한다.
        """
        workspace = self._ws_repo.get_by_id(db, workspace_id)
        if workspace is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="Workspace not found",
                http_status=404,
            )
        if not self._member_repo.user_exists(db, payload.new_owner_user_id):
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="User not found",
                http_status=404,
            )
        existing = self._member_repo.get(db, workspace_id, payload.new_owner_user_id)
        if existing is not None:
            self._member_repo.set_role(db, existing, "owner")
        else:
            self._member_repo.add(
                db,
                workspace_id=workspace_id,
                user_id=payload.new_owner_user_id,
                role="owner",
            )
        return WorkspaceRead.model_validate(workspace)
