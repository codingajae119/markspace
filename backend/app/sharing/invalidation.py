"""무효화 반응 조정 로직 — `ShareInvalidationSweep`
(design.md §Components and Interfaces #ShareInvalidationSweep, Feature/Service·Batch;
§System Flows 「무효화 반응 조정 스윕」).

문서가 휴지통/삭제로 가거나 워크스페이스 게이트가 꺼지면 그 문서의 공유 링크를 **관측 기반**으로
영구 무효화하는 멱등 스윕 로직이다. s14 는 상태 전이·게이트 설정을 소유하지 않고, 하위 계층
(`s07`/`s10` 상태 전이·`s05` 게이트)이 만든 `document.status`·`workspace.is_shareable` 라는 관측
가능한 결과만 스캔해 판정한다(Req 5.5·7.7). 무효화는 물리 삭제 없이 `retire`(is_enabled=false +
토큰 교체)로만 표현하며(INV-4·INV-8), 이미 비활성 링크는 스코프 질의에서 제외되어 멱등하다
(Req 5.6). retire 가 토큰을 교체하므로 이후 문서 복구·게이트 재활성에도 이전 토큰은 소멸해 재발급
(POST)으로만 재공유할 수 있다(Req 5.4).

경계(design.md §Dependency Direction): `ShareLinkRepository` 만 생성자 주입하고 DB 세션은 메서드
인자로 전달받는다. `Document`/`Workspace` 모델을 직접 import 하지 않고(관측은 리포지토리의 스코프
질의에 위임), 상태/게이트를 직접 갱신하지 않으며(관측만), 무효화 스코프 질의를 재구현하지 않는다.
`run_invalidation_sweep` 엔트리포인트·스케줄러 어댑터는 별도 task 소유이며 여기서 정의하지 않는다.
"""

import logging

from sqlalchemy.orm import Session

from app.sharing.repository import ShareLinkRepository

__all__ = ["ShareInvalidationSweep", "run_invalidation_sweep"]

logger = logging.getLogger(__name__)


class ShareInvalidationSweep:
    """문서 status·워크스페이스 게이트를 관측해 활성 링크를 retire 로 영구 무효화하는 멱등 스윕(Req 5).

    `ShareLinkRepository`(무효화 스코프 질의·retire)를 생성자 주입하고 DB 세션은 메서드 인자로
    전달받는다. 상태 전이·게이트 설정은 하지 않고 하위 계층 결과 상태만 관측하며, 물리 삭제 없이
    retire(비활성 + 토큰 교체)만 수행한다(INV-4·INV-8). 링크 단위 예외를 격리해 한 링크의 실패가
    전체 스윕을 중단시키지 않는다.
    """

    def __init__(self, *, repository: ShareLinkRepository | None = None) -> None:
        self._repository = repository or ShareLinkRepository()

    def invalidate_by_observation(self, db: Session) -> int:
        """무효 조건에 해당하는 활성 링크를 retire 하고 retire 건수를 반환한다
        (design.md §System Flows 무효화 반응 조정 스윕, Req 5.1~5.6·7.7, INV-4·INV-8).

        절차(flowchart):
        1. `list_enabled_invalidatable` 로 `is_enabled=true` 이면서 소속 문서 status 가 trashed/
           deleted 이거나 소속 워크스페이스 게이트(`is_shareable=false`)인 링크만 열거한다(무효화
           스코프). 이미 비활성 링크는 스코프에서 제외되어 멱등하다(Req 5.6). trashed/deleted·
           게이트 off 판정은 s07/s10·s05 가 만든 status·게이트 관측이며 여기서 전이/설정하지
           않는다(Req 5.5·7.7). 스코프 질의는 리포지토리 것을 그대로 소비하며 재필터하지 않는다.
        2. 각 링크에 대해 `retire`(is_enabled=false + 토큰 교체)로 영구 무효화한다(물리 삭제 없음,
           Req 5.3·INV-4·INV-8). retire 가 토큰을 교체하므로 이후 복구·게이트 재활성에도 이전
           토큰은 되살아나지 않고 재발급이 필요하다(Req 5.4).
        3. 성공한 retire 수를 세어 반환한다.

        예외 격리(Batch Recovery·Req 5.6 견고성): 개별 링크의 retire 실패를 try/except 로 격리해
        그 링크만 건너뛰고 로그로 남긴 뒤 스윕을 계속한다 — 한 링크의 실패가 전체 스윕을 중단시키지
        않는다. 조용히 삼키지 않으며(`logger.exception`), 세션 오염을 막기 위해 실패 시 롤백한 뒤
        다음 링크로 진행한다. 상태 전이·게이트 설정·물리 삭제는 하지 않는다(관측 + retire 만).
        """
        retired = 0
        links = self._repository.list_enabled_invalidatable(db)
        for link in links:
            try:
                # 물리 삭제 없이 비활성 + 토큰 교체로 영구 무효화(INV-4·INV-8, Req 5.3).
                self._repository.retire(db, link)
            except Exception:
                # 링크 단위 예외 격리: 실패를 로그로 남기고 계속. 조용히 삼키지 않는다.
                # 세션 오염 방지를 위해 롤백 후 다음 링크로 진행한다.
                logger.exception(
                    "무효화 반응 조정 스윕: 링크 id=%s retire 실패, 건너뛰고 계속 진행",
                    link.id,
                )
                db.rollback()
                continue
            retired += 1
        return retired


def run_invalidation_sweep() -> int:
    """무효화 스윕을 자기 세션으로 1회 실행하는 엔트리포인트 (design.md §ShareInvalidationScheduler,
    Req 5.1). 스케줄 job 본체이자 테스트·수동/외부 cron 실행 경로(`uv run python -m
    app.sharing.invalidation`)다.

    `s01` 단일 세션 팩토리(`SessionLocal`)로 자기 세션을 열고, 실제 `ShareInvalidationSweep`
    (기본 협력자 조립)로 무효화 스윕을 1회 수행한 뒤 commit 하고 retire 한 링크 수를 반환한다.
    세션 수명(commit·close)은 엔트리포인트가 소유하고, 무효화 판정·retire 는 서비스에 위임한다.

    세션 팩토리는 import 바인딩이 아니라 호출 시점에 `app.common.db.SessionLocal` 을
    참조해(모듈 속성 접근) 테스트에서 테스트 DB 로 재바인딩 가능하게 한다.
    """
    from app.common import db as db_module

    db = db_module.SessionLocal()
    try:
        service = ShareInvalidationSweep()
        retired = service.invalidate_by_observation(db)
        db.commit()
        return retired
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover - 수동/외부 cron 실행 진입점
    run_invalidation_sweep()
