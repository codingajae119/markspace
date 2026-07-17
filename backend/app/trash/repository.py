"""휴지통 데이터 접근 계층 — `TrashRepository`
(design.md §Components and Interfaces #TrashRepository, Feature/Data).

워크스페이스 보관일 조회와 스윕 스코프 열거의 단일 데이터 접근점이다. s01 `workspace`·
`document` 모델과 `get_db`/`SessionLocal` 세션을 사용하며, 문서 상태 질의·전이·묶음 식별은
하지 않는다(엔진 소관). 두 가지 읽기만 제공한다: (1) 만료 산정 근거인 워크스페이스
`trash_retention_days`(s05 설정값) 조회, (2) trashed 문서를 보유한 워크스페이스 id 열거로
보관 스윕 스코프를 축소.

계약 주의(design.md §DocumentRepository/LockVersionRepository 리포지토리 정합): 세션(`db`)은
메서드마다 인자로 전달받는다(생성자 주입 아님). 이 리포지토리는 **읽기 전용**이며 어떤 상태
전이·묶음 식별·물리 삭제도 하지 않는다. 무엇이 묶음인지·복구 위치·완전삭제는 s07
`DocumentStateEngine` 이 결정하고, 여기서는 워크스페이스 설정 읽기와 스윕 스코프 질의만
담당한다(Boundary).

경계: s01(`app.models.Workspace`·`app.models.Document`, sqlalchemy, stdlib)만 import 하며 다른
feature 도메인을 import 하지 않는다. s01 `common`·`models` 를 수정하지 않는다. 문서는 INV-4
대상이므로 어떤 메서드도 물리 DELETE 를 발행하지 않는다(읽기 전용).
"""

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.models import Document, Workspace

__all__ = ["TrashRepository"]

# 문서의 "휴지통" 상태 값(s01 document.status ENUM). 스윕 스코프 열거가 소비하는 필터로,
# app/document/repository.py `list_trashed_by_workspace` 와 동일한 리터럴을 사용한다.
_TRASHED = "trashed"


class TrashRepository:
    """워크스페이스 보관일 조회·스윕 스코프 열거의 단일 데이터 접근점(Req 1.4, 4.3).

    세션은 메서드별 인자로 전달받는다. 읽기 전용이며 상태 전이·묶음 식별·물리 삭제를 하지
    않는다(엔진 위임, INV-4). 워크스페이스 설정(`trash_retention_days`) 읽기와 trashed 보유
    워크스페이스 열거만 제공한다.
    """

    def get_retention_days(self, db: Session, workspace_id: int) -> int:
        """워크스페이스의 `trash_retention_days`(s05 설정값)를 스칼라로 반환한다(Req 1.4).

        보관 만료 예정 시각(`expires_at = trashed_at + retention_days`) 산정의 유일 근거다.
        전체 행을 로드하지 않고 설정 컬럼만 질의한다. 워크스페이스가 존재하지 않으면 None 이
        반환될 수 있으나, 호출자(서비스)는 유효 워크스페이스 스코프에서만 사용한다.
        """
        return db.scalar(
            select(Workspace.trash_retention_days).where(
                Workspace.id == workspace_id
            )
        )

    def list_workspace_ids_with_trashed(self, db: Session) -> list[int]:
        """trashed 문서를 1개 이상 보유한 워크스페이스 id 를 DISTINCT 로 열거한다(Req 4.3).

        보관 스윕 스코프를 축소하는 질의다. `status == "trashed"` 인 문서가 없는 워크스페이스는
        제외하며, trashed 문서가 어디에도 없으면 빈 목록을 반환한다. 같은 워크스페이스에 여러
        trashed 문서가 있어도 `distinct` 로 정확히 한 번만 나타난다.
        `(workspace_id, status, trashed_at)` 인덱스가 상태 필터를 지원한다. 묶음 경계·문서 상태
        판정은 하지 않는다(엔진 위임).
        """
        return list(
            db.scalars(
                select(distinct(Document.workspace_id)).where(
                    Document.status == _TRASHED
                )
            )
        )
