"""L6 통합 테스트 하네스 (Task 1.1 / Req 1.1·1.2·1.3·1.4·1.6, design §L6TestHarness).

mock 없이 s01 ⊕ s02 ⊕ s03 ⊕ s05 ⊕ s07 ⊕ s09 ⊕ s10 ⊕ s12 ⊕ **s14** 의 실제 구현을 결합한
전체 시스템 최종 검증 환경을 제공한다. 핵심 원칙은 **L5 하네스 재사용·확장**(중복 신설 금지)이다:
마이그레이션(`alembic upgrade head`)·`s01` `create_app()` 부팅·admin 시드·세션 유지 `TestClient`
팩토리·고유 login_id 생성기·워크스페이스 생성·멤버 추가(role)·role별 세션 클라이언트·문서 트리
생성·부팅 앱과 동일 `SessionLocal`/`get_db` 세션의 `DocumentStateEngine` 접근·두 editor(A·B)
세션·휴지통 삭제/복구·`now` 주입 `RetentionSweepService`·s12 아카이브 스윕·첨부 업로드/서빙·
파일시스템 관찰은 모두 `s13` `tests/integration_L5` 자산(그리고 그것이 재사용하는 `s11`
`tests/integration_L4`·`s08` `L3`·`s06` `L2`·`s04` `L1`)을 그대로 쓴다. 부팅 앱은
s02·s03·s05·s07·s09·s10·s12·**s14 공유 라우터 + 무효화 스케줄러가 조립된 상태**
(`app.main.create_app`/lifespan)이므로 공유 발급·토글·공개 렌더·링크 경유 파일 라우트(s01
카탈로그 행 34~37)와 lifespan 무효화 스케줄러 훅이 결합되어 있다.

pytest 는 fixture 를 정의된 디렉터리 트리에서만 수집하므로, 형제 디렉터리(L5/L4/L3/L2/L1)의
fixture 는 L6 에서 보이도록 **명시적 re-import** 해야 한다(L5 conftest 의 re-import 패턴 답습).
L5 conftest 의 ``__all__`` 이 이미 `harness`(L1)·`ws_scenario`/`WorkspaceScenario`(L2)·문서 트리·
엔진 접근(L3)·`lock_scenario`/`trash_scenario`/`sweep_access`(L4)·`tmp_attachment_roots`/
`archival_sweep`(L5)를 자신의 네임스페이스로 재-export 하므로, 이 모듈은 그 한 지점에서 하네스
계보 전체와 첨부·스윕 확장 픽스처를 한꺼번에 재-import 한다.

이 모듈이 신규로 추가하는 것은 s14 공유 통합 전용 세 픽스처다:

1. ``share_scenario`` (:class:`ShareScenario`): 게이트 on 워크스페이스의 active 문서에 editor 가
   링크를 발급(`POST /documents/{id}/share`)한 셋업 + **비인증 공개 클라이언트**(``public_client``)
   번들. `doc_tree_scenario`(role별 세션·문서 트리) 위에서 owner 가 `is_shareable=true` 게이트를
   열고(L5 `l2_helpers.update_settings` 재사용) editor 가 링크를 발급한다. 인증 세션과 익명 공개
   클라이언트는 독립 쿠키 자로 분리한다.
2. ``invalidation_sweep`` (:class:`ShareInvalidationSweepAccess`): 부팅 앱과 **동일 세션 팩토리**
   (`harness.session_local`)로 실제 s14 `ShareInvalidationSweep` 을 조립해 관측 기반 무효화 스윕을
   구동하고 retire 건수를 반환한다(L5 `ArchivalSweepAccess` 의 s14 무효화 아날로그). **무효화 스윕
   세션 바인딩 함정**(Implementation Notes) 회피: `run_invalidation_sweep()` 은 호출 시점에
   `app.common.db.SessionLocal`(개발 DB 에 묶임)로 자기 세션을 열므로 그대로 호출하면 테스트 DB 가
   아니라 개발 DB 를 친다. 따라서 L5 `ArchivalSweepAccess` 패턴대로 `harness.session_local` 세션에서
   `ShareInvalidationSweep().invalidate_by_observation(db)` 를 직접 호출하고 commit 한다(부팅 앱과
   동일 세션 팩토리·커밋 경계 정렬).
3. ``share_link_observation`` (:class:`ShareLinkObservation`): 부팅 앱과 동일 세션 팩토리로
   `share_link.token`·`is_enabled` 를 문서/토큰 기준으로 읽어 retire(토큰 교체 + 비활성)·재발급
   (새 토큰)을 관찰하고, retire 후에도 행이 물리 삭제되지 않고 남아 있음(INV-4)을 확인한다.
   질의는 s14 `ShareLinkRepository` 를 그대로 소비한다(재구현 아님).

제약(design §L6TestHarness):
- 어떤 애플리케이션 코드·`config.yml`·L5/L4/L3/L2/L1 하네스 자산도 수정하지 않는다(재사용만).
  동일 하네스를 중복 정의하지 않는다.
- mock·stub 미사용(무효화 스윕 직접 호출은 실제 s14 코드 실행이므로 허용). 설정은 s01 `Settings`
  재사용(공유 additive `share_token_bytes`·`share_invalidation_sweep_interval_seconds` 포함).
- DB·부팅 실패 시 스킵이 아니라 **실패**(L1 `harness` 가 오류를 전파; 여기서 ``pytest.skip`` 미사용).
- 공유 `markspace_test` DB 오염 방지를 위해 사용자·문서·토큰마다 고유 접미사(uuid4, 하위 하네스)를 쓴다.
"""

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.models import ShareLink
from app.sharing.invalidation import ShareInvalidationSweep
from app.sharing.repository import ShareLinkRepository

# L5 helpers 는 L4/L3/L2/L1 helpers 를 재-export 하므로 게이트 토글(`l2_helpers.update_settings`)
# 등 하위 헬퍼에 한 지점에서 도달한다. 공유 발급 래퍼는 task 1.2 소유이므로 하네스에서는 실제
# 공유 라우트를 직접 호출한다(래퍼 중복 선점 금지).
from tests.integration_L5 import helpers as l5_helpers

# L5 conftest 에서 하네스(L1)·워크스페이스 시나리오(L2)·문서 트리·엔진 접근(L3)·L4 확장
# (lock/trash/sweep)·L5 확장(첨부 저장 루트·아카이브 스윕)을 한꺼번에 재-import 한다. L5 conftest 의
# ``__all__`` 이 하위 계보 재-export 를 자신의 네임스페이스로 이미 노출하므로, 이 하나의 지점에서
# 하네스 계보 전체와 첨부·스윕 확장 픽스처를 함께 가져올 수 있다. pytest 는 형제 디렉터리 fixture 를
# 자동 수집하지 않으므로 명시적 re-import 가 필요하다.
from tests.integration_L5.conftest import (  # noqa: F401 — L1~L5 하네스 픽스처 재사용
    ArchivalSweepAccess,
    AttachmentStorageRoots,
    DocumentEngineAccess,
    DocumentTreeScenario,
    LockScenario,
    SweepAccess,
    TrashScenario,
    WorkspaceScenario,
    archival_sweep,
    doc_tree_scenario,
    engine_access,
    harness,
    lock_scenario,
    sweep_access,
    tmp_attachment_roots,
    trash_scenario,
    ws_scenario,
)

__all__ = [
    # (재사용) L5/L4/L3/L2/L1 하네스 재-export
    "harness",
    "ws_scenario",
    "WorkspaceScenario",
    "doc_tree_scenario",
    "DocumentTreeScenario",
    "engine_access",
    "DocumentEngineAccess",
    "lock_scenario",
    "LockScenario",
    "trash_scenario",
    "TrashScenario",
    "sweep_access",
    "SweepAccess",
    "tmp_attachment_roots",
    "AttachmentStorageRoots",
    "archival_sweep",
    "ArchivalSweepAccess",
    # (신규) s14 공유 통합 하네스 확장
    "ShareScenario",
    "share_scenario",
    "ShareInvalidationSweepAccess",
    "invalidation_sweep",
    "ShareLinkObservation",
    "share_link_observation",
]


# =============================================================================
# (1) 공유 시나리오 — 게이트 on active 문서에 발급된 링크 + 익명 공개 클라이언트
# =============================================================================


@dataclass
class ShareScenario:
    """게이트 on 워크스페이스의 active 문서에 editor 가 발급한 공유 링크 + 익명 공개 클라이언트 번들.

    `doc_tree_scenario`(role별 세션·문서 트리) 위에서 owner 가 `is_shareable=true` 게이트를 열고
    editor 가 루트 문서에 링크를 발급한 상태다. 인증 세션(owner/editor/viewer/비멤버/admin)과
    **독립된** 익명 공개 클라이언트(``public_client``)를 함께 노출해 후속 스위트(2.x)가 공유 발급·
    토글·공개 렌더·링크 경유 파일·무효화 재발급을 이 하나의 셋업 위에서 표현한다.

    필드:
    - ``doc_tree``: 재사용된 :class:`DocumentTreeScenario`(root/child/grandchild·role별 세션).
    - ``harness``: 재사용된 L1 하네스(세션 팩토리·클라이언트 팩토리·세션 쿠키 이름 접근).
    - ``share_link``: editor 발급 응답 `ShareLinkRead` dict(id·created_at·updated_at=None·
      document_id·token·is_enabled·share_url).
    - ``public_client``: 인증 세션과 독립된 익명(비인증) :class:`TestClient` 쿠키 자.
    """

    doc_tree: DocumentTreeScenario
    harness: object
    share_link: dict
    public_client: TestClient

    # --- 공유 링크 편의 접근 --------------------------------------------------
    @property
    def workspace_id(self) -> int:
        """게이트 on 워크스페이스 id."""
        return self.doc_tree.workspace_id

    @property
    def document_id(self) -> int:
        """링크가 발급된 공유 문서(루트) id."""
        return self.doc_tree.root_id

    @property
    def root_id(self) -> int:
        return self.doc_tree.root_id

    @property
    def child_id(self) -> int:
        return self.doc_tree.child_id

    @property
    def grandchild_id(self) -> int:
        return self.doc_tree.grandchild_id

    @property
    def token(self) -> str:
        """현재 발급 응답의 공개 접근 토큰."""
        return self.share_link["token"]

    # --- role별 인증 세션 클라이언트(재사용 워크스페이스 시나리오 경유) ----------
    @property
    def owner_client(self) -> TestClient:
        return self.doc_tree.scenario.owner_client

    @property
    def editor_client(self) -> TestClient:
        return self.doc_tree.scenario.editor_client

    @property
    def viewer_client(self) -> TestClient:
        return self.doc_tree.scenario.viewer_client

    @property
    def nonmember_client(self) -> TestClient:
        return self.doc_tree.scenario.nonmember_client

    @property
    def admin_client(self) -> TestClient:
        return self.doc_tree.scenario.admin_client


@pytest.fixture
def share_scenario(harness, doc_tree_scenario) -> ShareScenario:
    """게이트 on active 문서에 editor 가 링크를 발급한 공유 시나리오 + 익명 공개 클라이언트.

    구성 절차(모두 실제 라우트·실제 세션, mock 없음):

    1. `doc_tree_scenario` 로 role별 세션·문서 트리(root←child←grandchild, active)를 확보한다.
    2. owner 가 워크스페이스 `is_shareable` 게이트를 true 로 연다(L5 `l2_helpers.update_settings`
       재사용 = PATCH /workspaces/{id}; s05 실제 라우트, 신규 라우트 불필요).
    3. editor 가 active 루트 문서에 `POST /documents/{id}/share` 로 링크를 발급한다(계약상 **200**
       `ShareLinkRead`, upsert 통일이라 201 아님; 활성 토큰).
    4. 인증 세션과 **독립된** 익명 공개 클라이언트(`harness.new_client()`, 별도 쿠키 자)를 만든다.

    ``ws_scenario`` 는 워크스페이스를 `is_shareable` 기본 false(s01 기본)로 만드므로 이 픽스처가
    게이트를 명시적으로 연다. 반환된 :class:`ShareScenario` 로 후속 스위트가 발급·토글·공개 렌더·
    링크 경유 파일·무효화 재발급을 관찰한다.
    """
    ws_id = doc_tree_scenario.workspace_id
    owner = doc_tree_scenario.scenario.owner_client
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id

    # (2) 게이트 on — owner 경로 s05 설정 라우트 재사용(L5 → L2 헬퍼).
    l5_helpers.l2_helpers.update_settings(owner, ws_id, is_shareable=True)

    # (3) editor 발급 — 계약상 200 ShareLinkRead(활성 토큰).
    resp = editor.post(f"/documents/{doc_id}/share")
    assert resp.status_code == 200, (
        f"게이트 on active 문서 공유 발급은 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    share_link = resp.json()

    # (4) 인증 세션과 독립된 익명 공개 클라이언트(별도 쿠키 자).
    public_client = harness.new_client()

    return ShareScenario(
        doc_tree=doc_tree_scenario,
        harness=harness,
        share_link=share_link,
        public_client=public_client,
    )


# =============================================================================
# (2) 무효화 스윕 접근 — 부팅 앱과 동일 세션으로 실제 s14 관측 기반 무효화 스윕 구동
# =============================================================================


class ShareInvalidationSweepAccess:
    """부팅 앱과 동일 세션 팩토리로 실제 s14 `ShareInvalidationSweep` 을 구동하는 접근 핸들.

    부팅 앱이 `get_db` override 로 쓰는 **같은** 세션 팩토리(`harness.session_local`)로 실제 무효화
    스윕을 조립한다. API 가 커밋한 문서 status·게이트·share_link 행 위에서 관측 기반 무효화(retire=
    비활성 + 토큰 교체)를 실행함을 관찰한다. 어떤 것도 mock 하지 않는다 — L5 `ArchivalSweepAccess`
    (s12 아카이브 스윕)의 s14 무효화 아날로그다.

    **무효화 스윕 세션 바인딩 함정 회피(Implementation Notes)**: L1 하네스는 `get_db` 의존성만
    override 하고 모듈 전역 `app.common.db.SessionLocal`(개발 DB 에 묶임)은 재바인딩하지 않는다.
    `run_invalidation_sweep()` 은 호출 시점에 그 전역으로 **자기 세션**을 열어 개발 DB 를 치므로,
    이 핸들은 `run_invalidation_sweep()` 를 쓰지 않고 `harness.session_local` 세션에서
    `ShareInvalidationSweep().invalidate_by_observation(db)` 를 직접 호출하고 commit 한다(부팅 앱과
    동일 세션 팩토리·커밋 경계 정렬).

    노출 표면:
    - ``session_local``: 부팅 앱과 동일한 세션 팩토리.
    - ``service``: 주입된 실제 :class:`ShareInvalidationSweep`.
    - :meth:`sweep`: 새 세션을 열어 `invalidate_by_observation(db)` 를 구동하고 commit 한 뒤 retire
      건수를 반환.
    """

    def __init__(self, session_local: sessionmaker) -> None:
        self.session_local = session_local
        self.service = ShareInvalidationSweep()

    def sweep(self) -> int:
        """새 세션으로 관측 기반 무효화 스윕을 1회 구동하고 retire 건수를 반환한다.

        무효화는 관측 기반이므로 ``now`` 주입이 아니라 호출 시점의 실제 문서 status·게이트 상태를
        관측한다(design §L6TestHarness). 부팅 앱과 동일 세션 팩토리를 써서 API 가 커밋한 행 위에서
        실제 스윕이 동작함을 관찰한다. 세션 수명(commit·close)은 이 핸들이 소유한다. 무효 조건이
        없으면 0 을, 무효 조건 활성 링크가 있으면 retire 한 건수를 반환한다(멱등: 이미 비활성 링크는
        스코프에서 제외).

        **스코프 주의(공개 게이트 lazy retire 와의 상호작용)**: `list_enabled_invalidatable` 은
        `is_enabled=True` 링크만 대상으로 하므로, 무효 문서에 공개 접근(`_resolve_valid_link`)이
        먼저 일어나 그 링크가 lazy retire(비활성 + 토큰 교체) 되었다면 이 스윕은 그 링크를 스코프에서
        제외한다(이중 처리 방지·멱등, Req 5.2·5.6). 즉 「스윕 retire 건수 > 0」은 **아직 공개 접근이
        무효화하지 않은** 활성 링크가 있을 때만 관측된다.
        """
        with self.session_local() as db:
            retired = self.service.invalidate_by_observation(db)
            db.commit()
        return retired


@pytest.fixture
def invalidation_sweep(harness) -> ShareInvalidationSweepAccess:
    """부팅 앱과 동일 세션 팩토리로 실제 s14 `ShareInvalidationSweep` 을 조립한 무효화 스윕 접근 핸들.

    `harness.session_local` 은 앱 `get_db` override 와 **동일한** 세션 팩토리이므로, 여기서 구동하는
    스윕은 API 가 커밋한 문서 status·게이트·share_link 행을 그대로 관측·retire 한다(동일 DB·커밋
    경계 정렬). 실제 s14 코드를 실행하며 어떤 것도 mock 하지 않는다(Req 1.6). `run_invalidation_sweep`
    직접 호출 대신 이 핸들을 쓰는 이유는 세션 바인딩 함정(모듈 docstring 참조) 때문이다.
    """
    return ShareInvalidationSweepAccess(harness.session_local)


# =============================================================================
# (3) share_link 관찰 — 부팅 앱과 동일 세션으로 token·is_enabled·물리 삭제 부재 관찰
# =============================================================================


class ShareLinkObservation:
    """부팅 앱과 동일 세션 팩토리로 `share_link` 행을 문서/토큰 기준으로 관측하는 핸들(INV-4·INV-8).

    `share_link.token`·`is_enabled` 를 DB 에서 직접 읽어 retire(토큰 교체 + 비활성)·재발급(새 토큰)을
    관찰하고, retire 후에도 행이 물리 삭제되지 않고 남아 있음(INV-4)을 확인한다. 질의는 s14
    `ShareLinkRepository`(`get_by_document`·`get_by_token`)를 그대로 소비한다(재구현 아님).
    `AttachmentRead` 처럼 응답이 노출하지 않는 내부 상태를 DB 로 관측하는 L5 `attachment_*` 관찰
    래퍼의 s14 아날로그다.

    노출 표면:
    - ``session_local``: 부팅 앱과 동일한 세션 팩토리.
    - :meth:`by_document` / :meth:`by_token`: 새 세션으로 링크 행(ORM)을 로드(미존재 None).
    - :meth:`token_of` / :meth:`is_enabled_of`: 문서 기준 token·is_enabled 값 관측(미존재 None).
    - :meth:`row_exists`: 문서 기준 행이 (retire 후에도) 물리적으로 남아 있는지 관측(INV-4).
    """

    def __init__(self, session_local: sessionmaker) -> None:
        self.session_local = session_local
        self._repo = ShareLinkRepository()

    def by_document(self, document_id: int) -> ShareLink | None:
        """문서 id 로 share_link 행(ORM)을 새 세션으로 로드한다(최대 1개, 미존재 None).

        호출마다 새 세션을 열어 API 가 커밋한 최신 행(retire·재발급 반영)을 관측한다(L5
        `attachment_file_path` 관찰 패턴과 정합).
        """
        with self.session_local() as db:
            return self._repo.get_by_document(db, document_id)

    def by_token(self, token: str) -> ShareLink | None:
        """공개 토큰으로 share_link 행(ORM)을 새 세션으로 로드한다(retire 로 교체된 이전 토큰은 미조회)."""
        with self.session_local() as db:
            return self._repo.get_by_token(db, token)

    def token_of(self, document_id: int) -> str | None:
        """문서의 현재 링크 토큰을 관측한다(미존재 None). retire 는 이 값을 교체한다(INV-8)."""
        link = self.by_document(document_id)
        return None if link is None else link.token

    def is_enabled_of(self, document_id: int) -> bool | None:
        """문서의 현재 링크 `is_enabled` 를 관측한다(미존재 None). retire 는 False 로 만든다."""
        link = self.by_document(document_id)
        return None if link is None else link.is_enabled

    def row_exists(self, document_id: int) -> bool:
        """문서의 share_link 행이 물리적으로 존재하는지 관측한다(retire 후에도 True, INV-4 물리 삭제 부재)."""
        return self.by_document(document_id) is not None


@pytest.fixture
def share_link_observation(harness) -> ShareLinkObservation:
    """부팅 앱과 동일 세션 팩토리로 share_link 행을 관측하는 핸들(token·is_enabled·물리 삭제 부재).

    `harness.session_local` 로 API 가 커밋한 share_link 행을 신규 세션으로 읽어 retire(토큰 교체 +
    비활성)·재발급(새 토큰)을 결정적으로 관찰한다(design §L6TestHarness 위험 완화: 토큰 값 DB 비교).
    s14 `ShareLinkRepository` 질의를 소비할 뿐 어떤 것도 mock 하지 않는다.
    """
    return ShareLinkObservation(harness.session_local)
