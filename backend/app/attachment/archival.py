"""보관 배치 조정 로직 — `ArchivalSweepService`
(design.md §Components and Interfaces #ArchivalSweepService, Feature/Service·Batch).

문서 완전삭제(8.6)·저장 참조 소멸(8.7)에 대한 첨부 보관 이동을 **관측 기반**으로 조정하는
멱등 스윕 로직이다. s12 는 상태 전이·버전 생성·묶음 규칙을 소유하지 않고, 하위 계층(`s10`/`s07`/
`s09`)이 만든 `document.status='deleted'`·현재 버전 참조 같은 관측 가능한 결과만 스캔해 판정한다
(REQ-4.3·5.4·7.7). 보관 이동은 물리 삭제 없이 파일을 워크스페이스 보관 폴더로 옮기고
`is_archived=true`·`file_path` 를 갱신하는 것뿐이며(INV-4), 이미 보관된 첨부는 스코프 질의에서
제외되어 멱등하다(REQ-4.4·5.4).

경계(design.md §Dependency Direction): 리포지토리·스토리지·참조 스캐너·문서 리포지토리는 생성자
주입하고 DB 세션은 메서드 인자로 전달받는다. 8.6 완전삭제 반응(`archive_for_deleted_documents`)은
`AttachmentRepository`(스코프 질의·`mark_archived`)와 `AttachmentStorage`(`move_to_archive`)만,
8.7 참조 소멸(`archive_dereferenced_images`)은 여기에 더해 `ReferenceScanner`(참조 판정)와 s07
`DocumentRepository`(현재 버전 본문 로드 `load_current_content`)만 소비한다. `s09`/`s10`/`s14` 를
import 하지 않고(s07 `DocumentRepository` 는 허용 상위 의존), 상태/버전을 직접 갱신하지 않는다
(관측만). 통합 진입점 `sweep(db, now)` 이 두 조정을 순서대로 수행한다.
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.attachment.reference import ReferenceScanner
from app.attachment.repository import AttachmentRepository
from app.attachment.storage import AttachmentStorage
from app.document.repository import DocumentRepository

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
        reference_scanner: ReferenceScanner | None = None,
        document_repository: DocumentRepository | None = None,
    ) -> None:
        self._repository = repository or AttachmentRepository()
        self._storage = storage or AttachmentStorage()
        self._scanner = reference_scanner or ReferenceScanner()
        self._documents = document_repository or DocumentRepository()

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

    def archive_dereferenced_images(self, db: Session) -> int:
        """현재 버전이 더 이상 참조하지 않는 image 첨부를 보관 폴더로 이동하고 이동 건수를 반환한다
        (design.md §System Flows 저장 참조 소멸 아카이브 8.7, Req 5.1~5.6·7.7, INV-4).

        절차(8.7 flowchart):
        1. `list_unarchived_images_with_current_version` 로 미보관 image 이며 소속 문서가
           active/trashed 이고 `current_version_id` 가 있는 첨부와 그 현재 버전 메타
           `(att, current_version_id, current_version_created_at)` 를 열거한다(8.7 스코프).
           이미지 한정·미보관·현재버전 존재는 스코프가 강제하므로 일반 파일은 8.6 으로만
           처리된다(REQ-5.6·5.4).
        2. **붙여넣기 보호(REQ-5.3, G1)**: `att.created_at > current_version.created_at` 이면 아직
           어떤 저장 버전에도 반영되지 않은 새 붙여넣기로 간주해 skip 한다(오아카이브 방지).
           `att.created_at <= current_version.created_at` 일 때만 진행한다.
        3. 현재 버전 본문을 s07 `load_current_content` 로 로드하고(직접 재구현하지 않음),
           `ReferenceScanner.is_referenced(content, att.id)` 가 False 이면(현재 버전이 참조 안 함)
           `move_to_archive` 로 이동 후 `mark_archived`(is_archived=true·file_path 갱신)한다
           (REQ-5.1·5.2). 현재 버전이 여전히 참조하면 보관하지 않는다(REQ-5.5).
        4. 성공한 첨부 수를 세어 반환한다.

        저장·버전 생성·상태 전이는 하지 않고 현재 버전 참조 관측으로만 판정한다(REQ-5.4·7.7).
        첨부 단위 예외를 격리(로그 후 롤백·계속)해 한 첨부의 실패가 전체 스윕을 중단시키지 않는다.
        """
        archived = 0
        rows = self._repository.list_unarchived_images_with_current_version(db)
        for att, _cur_ver_id, cur_ver_created_at in rows:
            try:
                # 붙여넣기 보호(REQ-5.3): 현재 버전보다 나중에 생성된 미저장 붙여넣기는 skip.
                if att.created_at > cur_ver_created_at:
                    continue
                # 현재 버전 본문을 s07 로 로드해 참조 관측(직접 로딩 재구현 없음).
                doc = self._documents.get(db, att.document_id)
                content = self._documents.load_current_content(db, doc)
                if self._scanner.is_referenced(content, att.id):
                    # 현재 버전이 여전히 참조: 유지(REQ-5.5).
                    continue
                # 참조 소멸: 물리 삭제 없이 보관 폴더로 이동(INV-4) 후 보관 표시(REQ-5.1).
                archived_path = self._storage.move_to_archive(
                    workspace_id=att.workspace_id, file_path=att.file_path
                )
                self._repository.mark_archived(
                    db, att, archived_path=archived_path
                )
            except Exception:
                # 첨부 단위 예외 격리: 실패를 로그로 남기고 계속. 조용히 삼키지 않는다.
                # 세션 오염 방지를 위해 롤백 후 다음 첨부로 진행한다.
                logger.exception(
                    "참조 소멸 아카이브: 첨부 id=%s 보관 이동 실패, 건너뛰고 계속 진행",
                    att.id,
                )
                db.rollback()
                continue
            archived += 1
        return archived

    def sweep(self, db: Session, now: datetime) -> int:
        """두 보관 조정(8.6 완전삭제 반응 → 8.7 참조 소멸)을 순서대로 수행하고 합산 건수를 반환한다
        (design.md §Components ArchivalSweepService, Req 4·5, INV-4).

        완전삭제 반응(`archive_for_deleted_documents`)을 먼저, 참조 소멸
        (`archive_dereferenced_images`)을 다음으로 실행하고 두 처리 건수를 합산해 반환한다.
        스코프가 항상 `is_archived=false` 만 대상으로 하므로 재적용은 무해하고 반복 실행이
        멱등하다(REQ-4.4·5.4).

        `now` 는 배치 계약 일관성(`app/trash/retention.py` 가 `now` 를 주입받는 것과 정합)을 위해
        인자로 받아 예약해 둔다. 8.7 붙여넣기 보호는 저장된 시각 비교
        (`att.created_at` vs `current_version.created_at`)로 판정하므로 `now` 에 직접 의존하지
        않으며, 테스트 결정성을 위해 내부에서 `datetime.utcnow()` 등을 호출하지 않는다(주입값 유지).
        """
        return self.archive_for_deleted_documents(db) + self.archive_dereferenced_images(
            db
        )
