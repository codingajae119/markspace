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
from app.lock_version.schemas import DocumentLockRead

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
