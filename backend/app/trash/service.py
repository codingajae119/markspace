"""휴지통 유스케이스 오케스트레이션 — `TrashService`
(design.md §Components and Interfaces #TrashService, Feature/Service).

휴지통 묶음 목록 투영·복구·완전삭제를 s07 `DocumentStateEngine` primitive 위임으로
오케스트레이션하는 얇은 서비스다. 상태 전이·묶음 규칙(무엇이 묶음인지·복구 위치·완전삭제
원자성, INV-10·11·12)은 엔진이 단일 구현으로 소유하며, 이 서비스는 그 규칙을 재구현하지
않고 primitive 를 호출·투영만 한다(Req 6.1). status/trashed_at 을 직접 갱신하지 않는다.

**목록 투영**(`list_trash`, task 2.1)에 더해 **복구**(`restore`)·**완전삭제**(`purge`,
task 2.2)를 엔진 primitive(`restore_bundle`·`purge_bundle`) 위임으로 제공한다.

경계(design.md §Dependency Direction): 엔진·리포지토리는 생성자 주입하고 DB 세션은
메서드별 인자로 전달받는다(`app/document/service.py` 의 저장소/서비스 주입 규약과 정합).
s07 `DocumentStateEngine`·s10 `TrashRepository`·s10 `TrashSchemas`·s01 `Page` 만 소비하며
라우터·s12/s14 도메인을 import 하지 않는다. 상태 전이·묶음 식별은 엔진에 위임한다.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.document.engine import DocumentStateEngine
from app.schemas.base import Page
from app.trash.repository import TrashRepository
from app.trash.schemas import TrashBundleRead

__all__ = ["TrashService"]


class TrashService:
    """휴지통 목록 투영·복구·완전삭제 오케스트레이션(엔진 위임, Req 1.1~1.6, 2·3).

    엔진(`identify_bundles`·후속 `restore_bundle`·`purge_bundle`)과 리포지토리
    (`get_retention_days`)를 생성자 주입하고 DB 세션은 메서드별 인자로 전달받는다.
    상태 전이·묶음 규칙은 엔진만 수행하며 이 서비스는 위임·투영만 한다(INV-10·11·12 보장은
    엔진 소관). `list_trash`(목록 투영)·`restore`(복구)·`purge`(완전삭제)를 소유한다.
    """

    def __init__(
        self, engine: DocumentStateEngine, repository: TrashRepository
    ) -> None:
        self._engine = engine
        self._repository = repository

    def list_trash(
        self, db: Session, workspace_id: int, limit: int, offset: int
    ) -> Page[TrashBundleRead]:
        """워크스페이스 휴지통의 trashed 묶음을 표시 스키마로 투영해 반환한다
        (design.md §System Flows 휴지통 목록 조회 행 29, Req 1.1~1.6·6.2).

        엔진 `identify_bundles` 로 그 워크스페이스의 trashed 묶음 **전체**를 엔진 식별
        결과로 얻는다 — 무엇이 하나의 묶음인지 재판정하지 않는다(Req 1.2). trashed 묶음만
        반환되므로 이미 deleted(완전삭제)된 문서는 노출되지 않는다(Req 1.5). 본인 삭제분
        여부와 무관하게 워크스페이스 전체 묶음을 노출하며(Req 1.6), 권한 게이트(editor
        이상)는 라우터가 담당한다.

        각 묶음의 보관 만료 예정 시각은 그 묶음의 공통 `trashed_at` 에 워크스페이스
        `trash_retention_days`(리포지토리 조회, s05 설정값)를 더한 값으로 **묶음별 독립**
        산정한다(Req 1.4). 서로 다른 시점에 삭제된 묶음은 각자의 만료 예정을 갖는다(Req 1.1).
        투영 자체는 `TrashBundleRead.from_bundle` 이 수행한다(루트 제목·구성원 요약 포함,
        Req 1.3).

        `identify_bundles` 는 limit/offset 을 받지 않으므로(전체 열거) 투영 결과를
        메모리에서 슬라이스한다. `total` 은 슬라이스와 무관하게 전체 묶음 수이며 페이지
        항목은 `items[offset:offset+limit]` 이다(s01 `Page` 규약, Req 6.2).

        상태 전이·묶음 규칙을 직접 쓰지 않는 순수 읽기/투영이다 — status/trashed_at 을
        갱신하지 않고 물리 삭제도 하지 않는다.
        """
        retention_days = self._repository.get_retention_days(db, workspace_id)
        bundles = self._engine.identify_bundles(db, workspace_id)
        projected = [
            TrashBundleRead.from_bundle(
                bundle,
                expires_at=bundle.trashed_at + timedelta(days=retention_days),
            )
            for bundle in bundles
        ]
        return Page[TrashBundleRead](
            items=projected[offset : offset + limit],
            total=len(projected),
        )

    def restore(self, db: Session, bundle_id: int) -> None:
        """휴지통 묶음을 복구해 묶음 전체를 active 로 되돌린다 — 엔진 복구 primitive 위임
        (design.md §System Flows 묶음 복구 행 30, Req 2.1~2.4).

        엔진 `restore_bundle(db, bundle_id)` 을 묶음 루트(`bundle_id` = 루트 문서 id)에
        그대로 호출한다(Req 2.1). 복구 위치(부모 밑/root)·정렬 순서 복원·자동 재중첩 여부는
        엔진이 단일 구현으로 결정하므로 여기서 재구현하지 않고 위임한다(Req 2.2). 엔진이
        `get_bundle` 로 구성원을 확정하며 요청된 묶음의 trashed 서브트리만 훑으므로 다른
        독립 묶음은 함께 되살아나지 않는다(Req 2.4).

        유효하지 않은 묶음 루트(문서 미존재·비trashed·비루트 구성원)면 엔진이
        `DomainError(NOT_FOUND, http_status=404)` 를 던지며, 이 서비스는 그 예외를 삼키지
        않고 그대로 전파한다(Req 2.3). 상태 전이(status/trashed_at)는 엔진만 수행하며 이
        서비스는 직접 갱신하지 않고 물리 삭제도 하지 않는다(Req 6.1). 첨부 보관 이동·공유
        무효화는 소유하지 않는다(Req 3.7 범위 밖). 라우터가 성공을 204 로 매핑하도록
        `None` 을 반환한다.
        """
        self._engine.restore_bundle(db, bundle_id)

    def purge(self, db: Session, bundle_id: int) -> None:
        """휴지통 묶음을 즉시 완전삭제해 묶음 전체를 deleted(종착)로 전환한다 — 엔진
        완전삭제 primitive 위임(design.md §System Flows 완전삭제 행 31, Req 3.1~3.3·3.5·3.7).

        엔진 `purge_bundle(db, bundle_id)` 을 묶음 루트에 그대로 호출해 물리 삭제 없이 즉시
        deleted 로 종착 전환한다(Req 3.1·3.3). 엔진 `get_bundle` 이 동일 trashed_at 연결
        서브트리로 범위를 한정하므로 요청된 묶음에만 적용되고 다른 독립 묶음의 상태·보관
        타이머에는 영향이 없다(Req 3.2).

        유효하지 않은 묶음 루트면 엔진이 `DomainError(NOT_FOUND, http_status=404)` 를
        던지며 이 서비스는 그대로 전파한다(Req 3.5). 완전삭제를 문서 상태 전이에 한정하고
        첨부 파일 보관 이동·공유 링크 무효화는 소유하지 않는다(Req 3.7). 상태 전이는 엔진만
        수행하며 이 서비스는 status/trashed_at 을 직접 갱신하지 않는다(Req 6.1). 라우터가
        성공을 204 로 매핑하도록 `None` 을 반환한다.
        """
        self._engine.purge_bundle(db, bundle_id)
