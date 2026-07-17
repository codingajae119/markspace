"""보관 만료 자동 영구삭제 스윕 로직 — `RetentionSweepService`
(design.md §Components and Interfaces #RetentionSweepService, Feature/Service·Batch).

보관일을 경과한 휴지통 묶음을 **묶음별 독립 타이머**로 산정해 s07 완전삭제 primitive
(`purge_bundle`)로 자동 deleted 전환하는 멱등 스윕 로직이다. 각 묶음의 만료는 그 묶음의
`trashed_at` + 워크스페이스 `trash_retention_days` 기준으로 독립 산정하며(INV-12), 한 묶음의
처리가 다른 묶음의 만료 기준을 바꾸지 않는다. 상태 전이·묶음 식별 규칙(INV-10·11·12)은
s07 `DocumentStateEngine` 이 단일 구현으로 소유하고, 이 서비스는 만료 판정만 하고 전이는
엔진에 위임한다(Req 6.1). status/trashed_at 을 직접 갱신하지 않고 물리 삭제도 하지 않는다.

`now` 는 인자로 주입받아(테스트·수동 실행에서 만료 경계를 결정적으로 검증) 스윕 내부에서
`datetime.utcnow()` 를 호출하지 않는다. 스케줄러 어댑터·`run_sweep` 엔트리포인트(현재 시각
산정·세션 수명 관리)는 별도 task(3.2 scheduler)가 소유하며 여기서는 순수 스윕 서비스만
구현한다.

경계(design.md §Dependency Direction): 엔진·리포지토리는 생성자 주입하고 DB 세션은 메서드
인자로 전달받는다. s07 `DocumentStateEngine`(`identify_bundles`·`purge_bundle`)과 s10
`TrashRepository`(`list_workspace_ids_with_trashed`·`get_retention_days`)만 소비하며 라우터·
스케줄러·s12/s14 도메인을 import 하지 않는다. 상태 전이·묶음 경계는 엔진에 위임한다.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.document.engine import DocumentStateEngine
from app.document.repository import DocumentRepository
from app.trash.repository import TrashRepository

__all__ = ["RetentionSweepService", "run_sweep"]

logger = logging.getLogger(__name__)


class RetentionSweepService:
    """보관 만료 묶음을 묶음별 독립 타이머로 산정해 엔진 완전삭제로 자동 전환한다(Req 4).

    엔진(`identify_bundles`·`purge_bundle`)과 리포지토리
    (`list_workspace_ids_with_trashed`·`get_retention_days`)를 생성자 주입하고 DB 세션과
    현재 시각(`now`)은 메서드 인자로 전달받는다. 만료 판정만 이 서비스가 하고 상태 전이·
    묶음 식별은 엔진이 수행한다(INV-10·11·12 보장은 엔진 소관). 멱등하며 묶음 단위 예외를
    격리해 전체 스윕이 중단되지 않게 한다.
    """

    def __init__(
        self, engine: DocumentStateEngine, repository: TrashRepository
    ) -> None:
        self._engine = engine
        self._repository = repository

    def sweep_expired_bundles(self, db: Session, now: datetime) -> int:
        """주입된 `now` 기준으로 만료 묶음을 산정·완전삭제하고 전환한 묶음 수를 반환한다
        (design.md §System Flows 보관 만료 자동 영구삭제 스윕, Req 4.1~4.7·6.1, INV-12).

        절차:
        1. `list_workspace_ids_with_trashed` 로 스코프를 trashed 문서 보유 워크스페이스로
           축소한다(비어 있으면 아무 일도 하지 않고 0). (Req 4.3)
        2. 각 워크스페이스에서 `get_retention_days` 로 보관일을, 엔진 `identify_bundles` 로
           묶음 전체를 얻는다 — 무엇이 묶음인지 재구성하지 않는다(Req 4.3).
        3. 각 묶음에 대해 `bundle.trashed_at + retention_days <= now` 이면(경계는 `<=` 라
           정확히 now 인 묶음도 만료) 엔진 `purge_bundle(root)` 로 deleted 전환하고 카운트를
           증가시킨다(Req 4.1·4.4). 만료 판정은 각 묶음의 `trashed_at` 기준 **독립**이며,
           다른 묶음의 처리가 그 기준을 바꾸지 않는다(공유/집계 컷오프를 두지 않음으로써
           자연히 성립, Req 4.2·4.5, INV-12).

        멱등성(Req 4.6·4.7): 이미 deleted 되었거나 복구된 묶음은 `identify_bundles`(trashed
        만 열거)에 없거나 `purge_bundle` 이 안전 처리(get_bundle 404)하므로 오류 없이
        건너뛴다. deleted 는 종착이라 재적용이 무해하며, 같은 `now` 로 반복 실행해도 이미
        전환된 묶음에 중복 전이를 일으키지 않는다.

        예외 격리(Req 4.6·4.7): 개별 묶음의 `purge_bundle` 실패(예: 경쟁적으로 이미 사라짐·
        복구됨)를 try/except 로 격리해 그 묶음만 건너뛰고 로그로 남긴 뒤 스윕을 계속한다 —
        한 묶음의 실패가 전체 스윕을 중단시키지 않는다. 세션이 오염되지 않도록 실패 시
        롤백한 뒤 다음 묶음으로 진행한다.

        `now` 는 주입값이며 내부에서 `datetime.utcnow()` 를 호출하지 않는다(테스트 결정성).
        상태 전이·묶음 경계는 엔진에 위임하며 이 서비스는 status/trashed_at 을 직접 갱신하지
        않고 물리 삭제도 하지 않는다(Req 6.1).
        """
        purged = 0
        workspace_ids = self._repository.list_workspace_ids_with_trashed(db)
        for workspace_id in workspace_ids:
            retention_days = self._repository.get_retention_days(
                db, workspace_id
            )
            bundles = self._engine.identify_bundles(db, workspace_id)
            for bundle in bundles:
                # 만료 판정: 각 묶음의 trashed_at 기준 독립 산정(공유 컷오프 없음, INV-12).
                if bundle.trashed_at + timedelta(days=retention_days) > now:
                    continue  # 아직 보관 기간이 남은 묶음은 그대로 둔다(Req 4.4).
                try:
                    self._engine.purge_bundle(db, bundle.root_document_id)
                except Exception:
                    # 묶음 단위 예외 격리(Req 4.6·4.7): 실패를 로그로 남기고 계속.
                    # 조용히 삼키지 않는다. 세션 오염 방지를 위해 롤백 후 다음 묶음.
                    logger.exception(
                        "보관 만료 스윕: 묶음 root_document_id=%s 완전삭제 실패, "
                        "건너뛰고 계속 진행",
                        bundle.root_document_id,
                    )
                    db.rollback()
                    continue
                purged += 1
        return purged


def run_sweep() -> int:
    """스윕을 자기 세션으로 1회 실행하는 엔트리포인트 (design.md §RetentionScheduler,
    Req 4.1). 스케줄 job 본체이자 테스트·수동/외부 cron 실행 경로(`uv run python -m
    app.trash.retention`)다.

    `s01` 단일 세션 팩토리(`SessionLocal`)로 자기 세션을 열고, 실제 `RetentionSweepService`
    (엔진·리포지토리 조립)로 현재 시각(`datetime.utcnow()`) 기준 스윕을 1회 수행한 뒤
    commit 하고 처리한 묶음 수를 반환한다. `now` 는 배치 실행 시점에 여기서만 산정하며
    서비스에는 주입한다(서비스 서명은 `now` 를 계속 인자로 받는다). 세션 수명(commit·close)은
    엔트리포인트가 소유하고, 만료 판정·상태 전이는 서비스·엔진에 위임한다.

    세션 팩토리는 import 바인딩이 아니라 호출 시점에 `app.common.db.SessionLocal` 을
    참조해(모듈 속성 접근) 테스트에서 테스트 DB 로 재바인딩 가능하게 한다.
    """
    from app.common import db as db_module

    db = db_module.SessionLocal()
    try:
        service = RetentionSweepService(
            engine=DocumentStateEngine(DocumentRepository()),
            repository=TrashRepository(),
        )
        purged = service.sweep_expired_bundles(db, now=datetime.utcnow())
        db.commit()
        return purged
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover - 수동/외부 cron 실행 진입점
    run_sweep()
