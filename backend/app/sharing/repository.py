"""공유 링크 데이터 접근 계층 — `ShareLinkRepository`
(design.md §Components and Interfaces #ShareLinkRepository, Feature/Data).

share_link r/w 와 토큰/문서 조회·무효화 스코프 질의·토큰 생성·retire 의 단일 데이터 접근점이다.
s01 share_link·document·workspace 모델과 `get_db`/`SessionLocal` 세션을 사용한다. share_link 는
물리 삭제하지 않으며(INV-4), 무효화는 `retire`(비활성 + 토큰 교체)로만 표현한다. 문서당 링크 행은
최대 1개이며, 발급/재발급(`upsert_reissue`)은 그 행을 upsert 하되 **항상 새 토큰 + is_enabled=True**
로 만든다(재발급 통일, INV-8: 이전 무효화 토큰을 되살리지 않음).

계약 주의(design.md §DocumentRepository/AttachmentRepository 리포지토리 정합): 세션(`db`)은
메서드마다 인자로 전달받는다(생성자 주입 아님). 쓰기 메서드(`upsert_reissue`·`set_enabled`·
`retire`)는 commit 후 refresh 하여 별도 세션 재조회가 변경을 관찰하도록 내구 영속화한다
(`SessionLocal` 은 `expire_on_commit=False`). 무엇을 언제 무효화할지·발급 게이트 판정은
`ShareInvalidationSweep`·`ShareLinkService` 의 책임이며 여기서는 질의·쓰기만 담당한다(Boundary).
**상태 전이·게이트 설정은 하지 않는다(관측만).** 무효화 스코프는 항상 `is_enabled == True` 만
대상으로 하여 멱등하다(이미 비활성 링크 제외).

경계: s01(`app.models.ShareLink`·`Document`·`Workspace`, sqlalchemy, stdlib)와 `app.config.
get_settings`(토큰 바이트 수 설정)만 import 하며 다른 feature 도메인(document/attachment/workspace
service·repository)을 import 하지 않는다. share_link 는 INV-4 대상이므로 어떤 메서드도 물리
DELETE 를 발행하지 않는다(retire 로 비활성 + 토큰 교체만).
"""

import secrets
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.models import Document, ShareLink, Workspace

__all__ = ["ShareLinkRepository"]

# 무효화 스코프 대상 문서 상태(s01 document.status ENUM). active 는 건강 상태이므로 제외한다.
_INVALIDATABLE_STATUSES = ("trashed", "deleted")

# 신규 토큰 생성 시 UNIQUE 충돌(천문학적 희박) 재시도 상한. 초과 시 예외로 드러낸다.
_TOKEN_MAX_ATTEMPTS = 8


class ShareLinkRepository:
    """share_link r/w 와 토큰/문서 조회·무효화 스코프·토큰 생성·retire 의 단일 데이터 접근점
    (Req 1.1, 2.1, 2.4, 2.5, 4.1, 5.1, 5.3, 5.6, 7.5).

    세션은 메서드별 인자로 전달받는다. 쓰기 메서드는 commit·refresh 로 영속화한다. share_link 는
    INV-4 대상이므로 물리 삭제 없이 retire(비활성 + 토큰 교체)만 수행한다. 상태 전이·게이트 설정은
    하지 않는다(관측만).
    """

    def get_by_document(self, db: Session, document_id: int) -> ShareLink | None:
        """문서 id 로 그 문서의 공유 링크(최대 1개)를 로드한다. 없으면 None(Req 2.1·2.5).

        문서당 share_link 행은 최대 1개라는 규약(발급/재발급이 upsert)에 따라 단건을 반환한다.
        발급/토글 서비스가 기존 링크 존재 여부를 판정하는 진입점이다.
        """
        return db.scalar(
            select(ShareLink).where(ShareLink.document_id == document_id)
        )

    def get_by_token(self, db: Session, token: str) -> ShareLink | None:
        """공개 접근 토큰으로 링크를 로드한다. 없으면 None(Req 2.1).

        `token` 은 UNIQUE 이므로 단건이다. 공개 렌더·파일 서빙이 토큰으로 링크를 찾는 진입점이며,
        retire 로 교체된 이전 토큰은 여기서 조회되지 않아 영구 무효화가 관측된다(INV-8).
        """
        return db.scalar(select(ShareLink).where(ShareLink.token == token))

    def upsert_reissue(self, db: Session, document_id: int) -> ShareLink:
        """문서의 링크를 발급/재발급한다: 행 없으면 insert, 있으면 갱신하되 항상 새 토큰 + 활성(Req 1.1·2.1·2.4).

        재발급 통일 원칙(INV-8)의 구현 지점이다. 기존 행이 있으면 **새 토큰 + is_enabled=True** 로
        갱신하고 `created_at` 은 유지한다(재발급이 발급 시각을 되살리지 않음). 없으면 새 행을 삽입
        한다(`created_at` 명시 설정 — share_link 모델에 created_at 서버 기본값 없음). 어떤 경로든
        이전(무효화) 토큰을 되살리지 않고 항상 새 토큰을 만든다(§4.5). 게이트·문서 active 검사는
        서비스의 책임이며 리포지토리는 요청된 문서의 행을 upsert 만 한다. commit·refresh 로 영속화.
        """
        link = self.get_by_document(db, document_id)
        new_token = self._generate_unique_token(db)
        if link is not None:
            link.token = new_token
            link.is_enabled = True
        else:
            link = ShareLink(
                document_id=document_id,
                token=new_token,
                is_enabled=True,
                created_at=datetime.utcnow(),
            )
            db.add(link)
        db.commit()
        db.refresh(link)
        return link

    def set_enabled(
        self, db: Session, link: ShareLink, *, enabled: bool
    ) -> ShareLink:
        """링크의 `is_enabled` 만 전환하고 **토큰을 유지**한다(토글, Req 4.1).

        재발급 통일 원칙의 유일한 상태 기반 예외인 토글 지점이다. 새 토큰을 만들지 않고
        `is_enabled` 만 뒤집으므로 같은 URL 로 on/off 전환이 가능하다. 활성화 가능 여부(게이트
        on·문서 active) 판정은 서비스의 책임이며 여기서는 전달된 값으로 상태만 전환한다.
        commit·refresh 로 영속화한다.
        """
        link.is_enabled = enabled
        db.commit()
        db.refresh(link)
        return link

    def retire(self, db: Session, link: ShareLink) -> ShareLink:
        """링크를 `is_enabled=False` 로 비활성화하고 토큰을 교체한다(물리 삭제 없음, Req 5.3·INV-8).

        무효화 조정(스윕/lazy)의 영속화 지점이다. `is_enabled=False` 로 비활성화하고 **새 토큰으로
        교체**해 이전 토큰을 영구 무효화한다(복구·게이트 재활성 후에도 이전 URL 이 되살아나지 않음,
        재발급 필수). 물리 삭제는 하지 않으며 상태 전이·게이트 설정도 하지 않는다(관측 기반 반응만).
        무엇을 retire 할지 판정은 `ShareInvalidationSweep`·공개 게이트의 책임이다. commit·refresh 로
        영속화한다.
        """
        link.is_enabled = False
        link.token = self._generate_unique_token(db)
        db.commit()
        db.refresh(link)
        return link

    def list_enabled_invalidatable(self, db: Session) -> list[ShareLink]:
        """무효화 스코프: 활성이면서 (문서 trashed/deleted 또는 게이트 off)인 링크를 열거한다(Req 5.1·5.6·7.5).

        무효화 조정 스윕이 그대로 소비하는 관측 질의다. `is_enabled == True` 이면서 소속
        `document.status` 가 trashed/deleted 이거나 소속 `workspace.is_shareable == False` 인 링크만
        반환한다. 이미 비활성(`is_enabled=False`) 링크는 필터에서 제외되어 멱등하다(재적용 무해,
        Req 5.6). 문서 status·게이트 값을 여기서 쓰지 않고 s07/s05 가 만든 상태를 관측만 한다.
        `id` 오름차순으로 결정적 순서를 보장한다.
        """
        return list(
            db.scalars(
                select(ShareLink)
                .join(Document, ShareLink.document_id == Document.id)
                .join(Workspace, Document.workspace_id == Workspace.id)
                .where(
                    ShareLink.is_enabled.is_(True),
                    (
                        Document.status.in_(_INVALIDATABLE_STATUSES)
                        | Workspace.is_shareable.is_(False)
                    ),
                )
                .order_by(ShareLink.id)
            )
        )

    def _generate_unique_token(self, db: Session) -> str:
        """추측 불가한 새 토큰을 생성한다(`token VARCHAR(64)` 한도 내, Req 2.1·2.4).

        `secrets.token_urlsafe(share_token_bytes)` 로 URL-safe 토큰을 만든다(기본 32바이트 →
        약 43자, VARCHAR(64) 안전 적재). 설정은 호출 시점에 `get_settings()` 로 읽어 테스트가
        monkeypatch 할 수 있게 한다(s12 패턴). UNIQUE 충돌은 천문학적으로 희박하나, 방어적으로
        이미 존재하는 토큰이면 재생성하며 상한(`_TOKEN_MAX_ATTEMPTS`) 초과 시 예외로 드러낸다.
        """
        nbytes = config.get_settings().share_token_bytes
        for _ in range(_TOKEN_MAX_ATTEMPTS):
            token = secrets.token_urlsafe(nbytes)
            if self.get_by_token(db, token) is None:
                return token
        raise RuntimeError("고유 공유 토큰 생성에 반복 실패했습니다(예상 밖 충돌)")
