"""보관 배치 조정 로직 — `ArchivalSweepService`
(design.md §Components and Interfaces #ArchivalSweepService, Feature/Service·Batch).

문서 완전삭제(8.6)·저장 참조 소멸(8.7)에 대한 첨부 보관 이동을 **관측 기반**으로 조정하는
멱등 스윕 로직이다. s12 는 상태 전이·버전 생성·묶음 규칙을 소유하지 않고, 하위 계층(`s10`/`s07`)이
만든 `document.status='deleted'` 같은 관측 가능한 결과만 스캔해 판정한다(REQ-4.3·7.7). 보관 이동은
물리 삭제 없이 파일을 워크스페이스 보관 폴더로 옮기고 `is_archived=true`·`file_path` 를 갱신하는
것뿐이며(INV-4), 이미 보관된 첨부는 스코프 질의에서 제외되어 멱등하다(REQ-4.4).

경계(design.md §Dependency Direction): 리포지토리·스토리지는 생성자 주입하고 DB 세션은 메서드
인자로 전달받는다. 이 task(2.3)는 8.6 완전삭제 반응(`archive_for_deleted_documents`)만 구현하며
`AttachmentRepository`(스코프 질의·`mark_archived`)와 `AttachmentStorage`(`move_to_archive`)만
소비한다. `s09`/`s10`/`s14` 를 import 하지 않고, 상태/버전을 직접 갱신하지 않는다(관측만).
스케줄러 어댑터·`run_archival_sweep` 엔트리포인트와 8.7 참조 소멸 조정은 별도 task 소관이다.
"""

import logging

from sqlalchemy.orm import Session

from app.attachment.repository import AttachmentRepository
from app.attachment.storage import AttachmentStorage

__all__ = ["ArchivalSweepService"]

logger = logging.getLogger(__name__)


class ArchivalSweepService:
    """완전삭제 반응·참조 소멸 보관 이동을 관측 기반으로 조정하는 멱등 스윕 서비스(Req 4·5).

    리포지토리(스코프 질의·`mark_archived`)와 스토리지(`move_to_archive`)를 생성자 주입하고
    DB 세션은 메서드 인자로 전달받는다. 상태 전이·버전 생성은 하지 않고 하위 계층 결과 상태만
    관측하며, 물리 삭제 없이 보관 이동만 수행한다(INV-4). 첨부 단위 예외를 격리해 한 첨부의
    실패가 전체 스윕을 중단시키지 않는다.
    """

    def __init__(
        self,
        *,
        repository: AttachmentRepository | None = None,
        storage: AttachmentStorage | None = None,
    ) -> None:
        self._repository = repository or AttachmentRepository()
        self._storage = storage or AttachmentStorage()

    def archive_for_deleted_documents(self, db: Session) -> int:
        """deleted 문서에 연결된 미보관 첨부를 보관 폴더로 이동하고 이동 건수를 반환한다
        (design.md §System Flows 완전삭제 반응 보관 이동 8.6, Req 4.1~4.5·7.7, INV-4).

        절차:
        1. `list_unarchived_on_deleted_documents` 로 미보관이며 소속 문서가 deleted 인 첨부만
           열거한다(8.6 스코프). 이미 보관된 첨부는 제외되어 멱등하고(REQ-4.4), deleted 문서의
           첨부에만 적용된다(REQ-4.5). deleted 판정은 s10/s07 이 만든 status 관측이며 전이를
           수행하지 않는다(REQ-4.3).
        2. 각 첨부에 대해 `move_to_archive` 로 워크스페이스 보관 폴더로 파일을 이동하고(물리
           삭제 없음, INV-4·REQ-4.2), 반환된 보관 경로로 `mark_archived`(`is_archived=true`·
           `file_path` 갱신, commit)한다(REQ-4.1).
        3. 성공한 첨부 수를 세어 반환한다.

        예외 격리(견고성): 개별 첨부의 이동/표시 실패를 try/except 로 격리해 그 첨부만 건너뛰고
        로그로 남긴 뒤 스윕을 계속한다 — 한 첨부의 실패가 전체 스윕을 중단시키지 않는다. 조용히
        삼키지 않으며(`logger.exception`), 세션 오염을 막기 위해 실패 시 롤백한 뒤 다음 첨부로
        진행한다. 상태 전이·버전 생성·물리 삭제는 하지 않는다(관측 + 보관 이동만).
        """
        archived = 0
        attachments = self._repository.list_unarchived_on_deleted_documents(db)
        for att in attachments:
            try:
                # 물리 삭제 없이 보관 폴더로 이동(INV-4). 이미 이동된 파일엔 멱등 no-op.
                archived_path = self._storage.move_to_archive(
                    workspace_id=att.workspace_id, file_path=att.file_path
                )
                # 보관 표시: is_archived=true·file_path 갱신(commit, 관측만).
                self._repository.mark_archived(
                    db, att, archived_path=archived_path
                )
            except Exception:
                # 첨부 단위 예외 격리: 실패를 로그로 남기고 계속. 조용히 삼키지 않는다.
                # 세션 오염 방지를 위해 롤백 후 다음 첨부로 진행한다.
                logger.exception(
                    "완전삭제 반응 보관 이동: 첨부 id=%s 보관 이동 실패, "
                    "건너뛰고 계속 진행",
                    att.id,
                )
                db.rollback()
                continue
            archived += 1
        return archived
