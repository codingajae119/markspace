"""LockVersionService — 편집 잠금 생명주기·저장 오케스트레이션
(design.md §Components and Interfaces #LockVersionService).

start_edit·save·cancel_edit·force_unlock·list_versions 5개 유스케이스의 충돌·멱등·보유자
판정 규칙을 소유한다. 저장은 버전 생성·`current_version_id` 갱신·잠금 해제를 단일 트랜잭션
으로 원자 처리한다(REQ-2). 모든 동작은 문서 status 를 검사하지 않는다(§4.3).

save·cancel_edit·force_unlock·list_versions 는 이후 task 에서 구현한다(현재 미구현).
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.common.auth import AuthContext
from app.common.errors import DomainError, ErrorCode
from app.lock_version.repository import LockVersionRepository
from app.lock_version.schemas import (
    DocumentLockRead,
    DocumentSaveRequest,
    DocumentVersionRead,
)

__all__ = ["LockVersionService"]


class LockVersionService:
    """편집 잠금 생명주기(시작·취소·강제해제)와 저장(버전+잠금해제) 오케스트레이션·규칙
    (Req 1.x, 2.x, 3.x, 4.x, 5.x, 6.x).

    충돌·멱등·보유자 판정 규칙을 소유하고, 데이터 접근·행 잠금·커밋 대상 변이는
    :class:`LockVersionRepository` 에 위임한다. 커밋 경계는 이 서비스가 통제한다(리포지토리
    mutator 는 커밋하지 않음). 잠금 판정 근거는 `document.lock_user_id` 단일 컬럼(INV-9)이며
    문서 `status` 는 검사·변경하지 않는다(잠금·삭제 독립, §4.3).
    """

    def __init__(self, repository: LockVersionRepository) -> None:
        self._repository = repository

    def start_edit(
        self, db: Session, ctx: AuthContext, document_id: int
    ) -> DocumentLockRead:
        """미잠금 문서에 편집 잠금을 획득하거나 멱등/충돌을 판정한다 (Req 1.1·1.2·1.3·1.4·1.6).

        문서를 행 잠금(`FOR UPDATE`)으로 로드해 동시 획득 경합에서도 INV-9(최대 1인)를
        보장한다(design §편집 시작(획득) flowchart). `lock_user_id` 상태로 분기한다:

        - 문서 미존재 → 404 not_found (Req 1.6).
        - NULL(미잠금) → 요청자·현재 시각으로 잠금 획득 후 커밋(영속화). (Req 1.1)
        - 요청자 본인(현재 보유자 재요청) → 기존 잠금을 그대로 유지한 멱등 성공. 획득 시각을
          bump 하지 않으며 어떤 write 도 하지 않는다. (Req 1.3·1.4)
        - 타인 → 409 conflict("다른 사용자가 편집 중"). 잠금을 변경하지 않는다. (Req 1.2)

        문서 `status` 는 검사·변경하지 않는다(잠금·삭제 독립, §4.3·6.1). 응답은 스키마
        필드명이 ORM 속성과 다르므로(`document_id` ≠ `Document.id`) 명시적으로 구성한다.
        """
        doc = self._repository.get_for_update(db, document_id)
        if doc is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="문서를 찾을 수 없습니다",
                http_status=404,
            )

        if doc.lock_user_id is None:
            # 미잠금: 행 잠금 하에서 요청자·now 로 획득하고 커밋해 영속화한다(경합 안전).
            self._repository.acquire_lock(
                db, doc, user_id=ctx.user_id, at=datetime.utcnow()
            )
            db.commit()
        elif doc.lock_user_id != ctx.user_id:
            # 타인 잠금: 잠금을 변경하지 않고 충돌로 거부한다(잠금 보유자 충돌, INV-9).
            raise DomainError(
                code=ErrorCode.CONFLICT,
                message="다른 사용자가 편집 중입니다",
                http_status=409,
            )
        # 동일 보유자 재요청은 멱등 성공 — 기존 잠금을 그대로 유지하고 변이하지 않는다.

        return DocumentLockRead(
            document_id=doc.id,
            lock_user_id=doc.lock_user_id,
            lock_acquired_at=doc.lock_acquired_at,
        )

    def save(
        self,
        db: Session,
        ctx: AuthContext,
        document_id: int,
        payload: DocumentSaveRequest,
    ) -> DocumentVersionRead:
        """잠금 보유자의 저장을 버전 생성·current 갱신·잠금 해제로 원자 처리한다 (Req 2.1~2.6).

        문서를 행 잠금(`FOR UPDATE`)으로 로드한 뒤 `lock_user_id` 단일 컬럼(INV-9)으로 보유자를
        판정하고, 다음을 **단일 트랜잭션**으로 적용한다(design §저장 flowchart, REQ-2.4):

        1. 문서 미존재 → 404 not_found.
        2. 보유자 검사: `lock_user_id != 요청자`(미잠금·타인 잠금 모두 포함) → 409 conflict.
           **어떤 insert 보다 먼저** raise 하므로 버전을 만들지 않고 잠금·상태가 불변으로 롤백된다
           (REQ-2.5). 방어적으로 롤백해 행 잠금을 즉시 해제한다.
        3. `insert_version`(flush 로 새 버전 id 확보) → `set_current_version`(순환 nullable FK 갱신)
           → `clear_lock`(`lock_user_id`·`lock_acquired_at` → NULL) 을 한 커밋으로 확정한다.

        빈 문자열 본문도 유효한 저장이다(Req 2.6). 문서 `status` 는 검사·변경하지 않으며 상태 전이도
        수행하지 않는다(잠금·삭제 독립, §4.3·6.1). 저장 시각(`created_at`)은 repo 관례대로
        `datetime.utcnow()` 를 쓰고 버전 생성에 그대로 전달한다. 응답은 영속된 버전 행을 반영하는
        `DocumentVersionRead`(식별자·저장자·저장 시각) 이다.
        """
        doc = self._repository.get_for_update(db, document_id)
        if doc is None:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="문서를 찾을 수 없습니다",
                http_status=404,
            )

        if doc.lock_user_id != ctx.user_id:
            # 미잠금(NULL)·타인 잠금 모두 보유자 아님 — insert 이전에 거부해 버전을 만들지 않는다.
            # 아직 어떤 write 도 없었으므로 트랜잭션은 깨끗이 롤백된다(방어적 명시 롤백).
            db.rollback()
            raise DomainError(
                code=ErrorCode.CONFLICT,
                message="문서의 편집 잠금 보유자가 아닙니다",
                http_status=409,
            )

        at = datetime.utcnow()
        version = self._repository.insert_version(
            db,
            document_id=doc.id,
            content=payload.content,
            created_by=ctx.user_id,
            at=at,
        )
        self._repository.set_current_version(db, doc, version.id)
        self._repository.clear_lock(db, doc)
        db.commit()

        return DocumentVersionRead.model_validate(version)
