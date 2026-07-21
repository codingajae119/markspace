"""워크스페이스·멤버십 리포지토리 (design.md §Feature/Data).

`WorkspaceRepository`·`MembershipRepository` 가 s01 workspace·workspace_member·user 모델을
대상으로 데이터 접근을 담당한다. 이 모듈은 두 리포지토리를 함께 보유하며, 현재는
`WorkspaceRepository`(task 2.1)만 구현되어 있고 `MembershipRepository`(task 2.2)는 후속
task 에서 이 모듈에 추가된다.

계약 주의(design.md §WorkspaceRepository, s03 UserRepository 정합): 세션(`db`)은 메서드마다
인자로 전달받는다(생성자 주입 아님). 쓰기 메서드(`create`·`apply_updates`·`delete`)는 commit
하여 별도 세션 재조회가 변경을 관찰하도록 내구 영속화한다.

경계: s01(`app.models.Workspace`·`app.models.WorkspaceMember`, sqlalchemy, stdlib)만 import 하며
다른 feature 도메인을 import 하지 않는다. s01 `common`·`models` 를 수정하지 않는다. workspace 는
INV-4 비대상이므로 `delete` 는 물리 DELETE 를 발행한다(멤버십 선삭제·FK RESTRICT→409 변환은
서비스의 책임이며 리포지토리는 DELETE 만 발행한다).
"""

from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.models import User, Workspace, WorkspaceMember

__all__ = ["WorkspaceRepository", "MembershipRepository"]

# apply_updates 가 부분 갱신할 수 있는 필드 화이트리스트.
# 제공된 키 중 이 집합에 속한 것만 적용하여 예기치 않은 컬럼 변경을 차단한다.
_WRITABLE_FIELDS = frozenset({"name", "is_shareable", "trash_retention_days"})


class WorkspaceRepository:
    """workspace 조회·생성·수정·물리 삭제 데이터 접근 (Req 1.3, 1.4, 2.1, 2.5).

    세션은 메서드별 인자로 전달받는다. 쓰기 메서드는 commit 으로 영속화한다.
    목록은 요청자 멤버 스코프(`list_for_user`)와 admin 전체(`list_all`)로 나뉘며 total 은
    limit/offset 이전 전체 개수, items 는 limit/offset 을 적용한 페이지다.
    """

    def get_by_id(self, db: Session, workspace_id: int) -> Workspace | None:
        """PK 로 워크스페이스를 로드한다. 없으면 None 을 반환한다(Req 1.6)."""
        return db.get(Workspace, workspace_id)

    def list_for_user(
        self, db: Session, user_id: int, limit: int, offset: int
    ) -> tuple[list[tuple[Workspace, str]], int]:
        """요청자가 멤버인 워크스페이스를 ((Workspace, role) 목록, total) 로 반환한다(Req 1.1·1.3·1.4).

        `workspace_member` 를 inner 조인해 `user_id` 가 멤버인 워크스페이스만 스코프하며, 조인한
        멤버십 행에서 `role` 을 함께 SELECT 해 각 항목을 `(Workspace, role)` 튜플로 돌려준다(inner
        조인이라 모든 항목이 멤버십 role 을 가진다). 이로써 워크스페이스별 추가 조회(N+1) 없이 단일
        쿼리로 호출자 role 을 조달한다(Req 1.4). `total` 은 멤버 스코프 전체 개수이며 `limit`/`offset`
        은 items 에만 적용한다. items 는 `Workspace.id` 오름차순으로 정렬한다.

        role 은 `workspace_member.role` 원시 문자열(owner/member)을 그대로 반환하며 계층
        비교·admin bypass 판정은 하지 않는다(resolver 의 책임).
        """
        member_scope = select(WorkspaceMember.workspace_id).where(
            WorkspaceMember.user_id == user_id
        )
        total = (
            db.scalar(
                select(func.count())
                .select_from(Workspace)
                .where(Workspace.id.in_(member_scope))
            )
            or 0
        )
        rows = db.execute(
            select(Workspace, WorkspaceMember.role)
            .join(
                WorkspaceMember,
                (WorkspaceMember.workspace_id == Workspace.id)
                & (WorkspaceMember.user_id == user_id),
            )
            .order_by(Workspace.id)
            .limit(limit)
            .offset(offset)
        ).all()
        items = [(ws, role) for ws, role in rows]
        return items, total

    def list_all(
        self, db: Session, user_id: int, limit: int, offset: int
    ) -> tuple[list[tuple[Workspace, str | None]], int]:
        """전체 워크스페이스를 ((Workspace, role|None) 목록, total) 로 반환한다(admin, Req 1.2·1.3·1.4).

        호출자 `user_id` 로 `workspace_member` 를 LEFT OUTER JOIN 한다. 상관 조건은 `workspace_id
        == Workspace.id` **와** `user_id == 호출자` 를 **함께** JOIN ON 절에 둔다: 호출자가 멤버인
        WS 는 실제 멤버십 role 을, 비멤버 WS 는 NULL→`None` 을 얻는다(Req 1.3). admin 여부로 role 을
        상승시키지 않는다(Req 1.2, INV-3) — role 은 오직 호출자 멤버십에서만 산출한다.

        주의(anti-join 방지): `user_id == 호출자` 조건은 반드시 JOIN ON 절에 있어야 한다. 이를 WHERE
        로 옮기면 outer 조인이 사실상 inner 조인이 되어 비멤버 WS 가 결과에서 탈락한다(`_assignable_filters`
        의 상관 서브쿼리 idiom 과 동일한 상관 원칙). `total` 은 전체 WS 개수(멤버 여부 무관)이며
        `limit`/`offset` 은 items 에만 적용한다. items 는 `Workspace.id` 오름차순으로 정렬한다.
        """
        total = db.scalar(select(func.count()).select_from(Workspace)) or 0
        rows = db.execute(
            select(Workspace, WorkspaceMember.role)
            .outerjoin(
                WorkspaceMember,
                (WorkspaceMember.workspace_id == Workspace.id)
                & (WorkspaceMember.user_id == user_id),
            )
            .order_by(Workspace.id)
            .limit(limit)
            .offset(offset)
        ).all()
        items = [(ws, role) for ws, role in rows]
        return items, total

    def create(
        self, db: Session, *, name: str, trash_retention_days: int
    ) -> Workspace:
        """신규 워크스페이스를 생성하고 commit 하여 영속화한다(Req 2.1).

        생성 불변식으로 `is_shareable=False` 를 강제한다(입력과 무관). `created_at` 을
        명시적으로 설정한다(Workspace 모델에 created_at 서버 기본값 없음). `trash_retention_days`
        의 양수 검증은 서비스의 책임이며 리포지토리는 전달된 값을 그대로 저장한다.
        """
        workspace = Workspace(
            name=name,
            is_shareable=False,
            trash_retention_days=trash_retention_days,
            created_at=datetime.utcnow(),
        )
        db.add(workspace)
        db.commit()
        db.refresh(workspace)
        return workspace

    def apply_updates(
        self, db: Session, ws: Workspace, changes: dict
    ) -> Workspace:
        """제공된 키만 부분 갱신하고 commit 하여 영속화한다(Req 2.1·2.2·2.3).

        갱신 가능 필드는 `name`·`is_shareable`·`trash_retention_days` 로 한정한다. 화이트리스트
        밖 키는 무시하여 예기치 않은 컬럼 변경을 차단한다. `updated_at` 을 설정한다.
        `trash_retention_days` 의 양수(>0) 검증은 서비스의 책임이며 리포지토리는 영속화만 한다.
        """
        for key, value in changes.items():
            if key in _WRITABLE_FIELDS:
                setattr(ws, key, value)
        ws.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(ws)
        return ws

    def delete(self, db: Session, ws: Workspace, commit: bool = True) -> None:
        """워크스페이스 행을 물리적으로 제거하고(기본) commit 한다(INV-4 비대상, Req 2.5).

        workspace 는 INV-4 비대상 엔티티이므로 물리 DELETE 가 정당하다. 멤버십 선삭제와
        문서 참조 FK `ON DELETE RESTRICT` 위반(비-empty)→409 변환은 서비스의 책임이며,
        리포지토리의 `delete` 는 DELETE 만 발행한다.

        `commit=False` 로 호출하면 DELETE 만 flush 대상으로 스테이징하고 commit 은 호출자에게
        위임한다. 이는 멤버십 선삭제와 워크스페이스 DELETE 를 단일 트랜잭션으로 묶어 비-empty
        FK RESTRICT 위반 시 하나의 rollback 으로 아무것도 제거되지 않게 하려는 서비스의 요구
        (design.md §Invariants 단일 트랜잭션)를 위한 것이다.
        """
        db.delete(ws)
        if commit:
            db.commit()


class MembershipRepository:
    """workspace_member CRUD·role 조회·대상 user 존재 확인 데이터 접근
    (Req 3.1, 3.2, 3.6, 3.8, 4.2, 4.7, 5.2, 5.3).

    세션은 메서드별 인자로 전달받는다. 쓰기 메서드(`add`·`set_role`·`remove`·
    `remove_all_for_workspace`)는 commit 으로 영속화한다. 멤버십은 INV-4 비대상이므로
    `remove`·`remove_all_for_workspace` 는 물리 삭제를 발행한다.

    경계(design.md §MembershipRepository Boundary): resolver 의 비교·bypass 로직은 소유하지
    않는다. `get_role` 은 role 데이터 조회만 제공하며 role 계층/우회 판정은 s01 resolver 의
    책임이다.
    """

    def get(
        self, db: Session, workspace_id: int, user_id: int
    ) -> WorkspaceMember | None:
        """(workspace_id, user_id) 멤버 행을 로드한다. 없으면 None 을 반환한다(Req 4.2)."""
        return db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )

    def get_role(
        self, db: Session, workspace_id: int, user_id: int
    ) -> str | None:
        """(workspace_id, user_id) 의 role 문자열을 반환한다. 비멤버는 None(Req 4.2).

        이는 s01 resolver 가 소비하는 role 데이터의 조회 지점이다. 원시 role 문자열
        (owner/member)을 그대로 반환하며 계층 비교·admin bypass 판정은 하지 않는다
        (resolver 의 책임).
        """
        return db.scalar(
            select(WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )

    def add(
        self, db: Session, *, workspace_id: int, user_id: int, role: str
    ) -> WorkspaceMember:
        """(workspace_id, user_id, role) 멤버 행을 생성하고 commit 하여 영속화한다(Req 3.1).

        WorkspaceMember 에는 created_at/updated_at 컬럼이 없어 타임스탬프를 설정하지 않는다.
        (workspace_id, user_id) 유일성은 s01 UNIQUE 제약(uq_workspace_member_ws_user)이
        강제한다. 중복 삽입은 IntegrityError 로 표면화되며 리포지토리는 이를 삼키지 않는다
        (사전 조회·409 변환은 서비스의 책임).
        """
        member = WorkspaceMember(
            workspace_id=workspace_id, user_id=user_id, role=role
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        return member

    def set_role(
        self, db: Session, member: WorkspaceMember, role: str
    ) -> WorkspaceMember:
        """멤버의 role 을 갱신하고 commit 하여 영속화한다(Req 5.2)."""
        member.role = role
        db.commit()
        db.refresh(member)
        return member

    def remove(self, db: Session, member: WorkspaceMember) -> None:
        """멤버 행을 물리적으로 제거하고 commit 한다(INV-4 비대상, Req 5.3)."""
        db.delete(member)
        db.commit()

    def remove_all_for_workspace(
        self, db: Session, workspace_id: int, commit: bool = True
    ) -> None:
        """워크스페이스의 모든 멤버 행을 물리적으로 제거하고(기본) commit 한다(Req 3.6).

        워크스페이스 삭제 시 멤버십 선삭제에 사용된다(INV-4 비대상, 물리 삭제 정당).

        `commit=False` 로 호출하면 bulk DELETE 만 발행하고 commit 은 호출자에게 위임한다.
        이는 멤버십 선삭제와 이어지는 워크스페이스 DELETE 를 단일 트랜잭션으로 묶어, 비-empty
        FK RESTRICT 위반 시 하나의 rollback 으로 멤버십 제거까지 되돌리려는 서비스의 요구
        (design.md §Invariants 단일 트랜잭션 / 409 시 아무것도 제거되지 않음)를 위한 것이다.
        """
        db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace_id
        ).delete()
        if commit:
            db.commit()

    @staticmethod
    def _assignable_filters(workspace_id: int) -> list:
        """배정 가능 필터 절을 단일 소스로 반환한다(items·count 공유 → 드리프트 차단).

        "배정 가능" = admin 아님 ∧ 활성 ∧ 비삭제 ∧ 대상 워크스페이스의 비-멤버. 마지막
        조건은 상관 `NOT EXISTS` 로 표현하며, 서브쿼리는 `WorkspaceMember.workspace_id ==
        workspace_id` 와 `WorkspaceMember.user_id == User.id` 를 **함께** 상관시킨다.
        `user_id == User.id` 상관을 빠뜨리면 임의 워크스페이스의 멤버가 전부 제외되는
        anti-join 버그가 된다(design.md §Risks).
        """
        return [
            User.is_admin.is_(False),
            User.is_active.is_(True),
            User.is_deleted.is_(False),
            ~exists(
                select(WorkspaceMember.id).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == User.id,
                )
            ),
        ]

    def list_assignable_users(
        self, db: Session, workspace_id: int, limit: int, offset: int
    ) -> tuple[list[User], int]:
        """대상 워크스페이스에 배정 가능한 사용자를 (items, total) 로 반환한다(Req 1.1, 1.5).

        배정 가능 = admin 아님·활성·비삭제·해당 워크스페이스의 비-멤버(상관 NOT EXISTS).
        items 와 total 은 :meth:`_assignable_filters` 의 **동일한** where 절을 공유해 드리프트를
        차단한다(무필터 count 관례를 복제하지 않는다 — count 에도 상태 필터를 적용한다). items 는
        `User.id` 오름차순으로 결정적 정렬하며 `limit`/`offset` 은 items 에만 적용한다. `total` 은
        limit/offset 이전의 배정 가능 전체 개수다.
        """
        filters = self._assignable_filters(workspace_id)
        items = list(
            db.scalars(
                select(User)
                .where(*filters)
                .order_by(User.id)
                .limit(limit)
                .offset(offset)
            )
        )
        total = (
            db.scalar(select(func.count()).select_from(User).where(*filters)) or 0
        )
        return items, total

    def list_members(
        self, db: Session, workspace_id: int, limit: int, offset: int
    ) -> tuple[list[tuple[User, str]], int]:
        """대상 워크스페이스의 소속 멤버 전량을 ((User, role) 목록, total) 로 반환한다(Req 1.1·1.3·1.5·1.6).

        `User` ⋈ `WorkspaceMember`(ON `user_id`, WHERE `workspace_id`) inner-join 으로 소속
        멤버 전량을 조회하며, 조인한 멤버십 행에서 `role` 을 함께 SELECT 해 각 항목을
        `(User, role)` 튜플로 돌려준다. items 는 `User.id` 오름차순으로 결정적 정렬하며
        `limit`/`offset` 은 items 에만 적용한다. `total` 은 소속 멤버십 전체 개수로 items 와
        **동일한 `workspace_id` 필터만** 공유하며(드리프트 차단) limit/offset 은 적용하지 않는다.

        결정적 divergence(design.md §결정적 divergence) — 이 메서드는 인접한
        :meth:`list_assignable_users` 의 **정반대**다: **소프트삭제 필터를 적용하지 않는다**
        (`is_active`/`is_deleted`/`is_admin` 미필터). 비활성·삭제 상태 멤버도 role 과 함께
        포함해야 하므로(Req 1.5) `_assignable_filters` 를 재사용하지 않는다. INV-4(물리삭제
        없음)로 멤버십↔user FK dangling 이 없어 무필터 inner-join 이 안전하다.

        role 은 `workspace_member.role` 원시 문자열(owner/member)을 그대로 반환하며
        위계 비교·admin bypass 판정은 하지 않는다(resolver 의 책임). workspace_id 존재 여부는
        게이트가 선행 처리하므로 리포지토리는 존재검사를 하지 않는다.
        """
        rows = db.execute(
            select(User, WorkspaceMember.role)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(User.id)
            .limit(limit)
            .offset(offset)
        ).all()
        items = [(user, role) for user, role in rows]
        total = (
            db.scalar(
                select(func.count())
                .select_from(WorkspaceMember)
                .where(WorkspaceMember.workspace_id == workspace_id)
            )
            or 0
        )
        return items, total

    def user_exists(self, db: Session, user_id: int) -> bool:
        """user 행이 존재하면 True 를 반환한다(Req 3.2).

        is_deleted=True 사용자도 존재로 간주한다(is_deleted/is_active 로 필터하지 않는
        존재 확인). 대상 사용자 존재 확인은 멤버 추가·소유권 변경의 선행 조건이다.
        """
        return db.get(User, user_id) is not None
