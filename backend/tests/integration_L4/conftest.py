"""L4 통합 테스트 하네스 (Task 1.1 / Req 1.1·1.2·1.3·1.4, design §L4TestHarness).

mock 없이 s01 ⊕ s02 ⊕ s03 ⊕ s05 ⊕ s07 ⊕ **s09** ⊕ **s10** 의 실제 구현을 결합한 검증
환경을 제공한다. 핵심 원칙은 **L3 하네스 재사용**(중복 신설 금지)이다: 마이그레이션
(`alembic upgrade head`)·`s01` `create_app()` 부팅·admin 시드·세션 유지 `TestClient` 팩토리·
고유 login_id 생성기·워크스페이스 생성·멤버 추가(role)·role별 세션 클라이언트·문서 트리
생성·부팅 앱과 동일 `SessionLocal`/`get_db` 세션의 `DocumentStateEngine` 접근은 모두 `s08`
`tests/integration_L3` 자산(그리고 그것이 재사용하는 `s06` `tests/integration_L2`·`s04`
`tests/integration_L1`)을 그대로 쓴다. 부팅 앱은 s02·s03·s05·s07·**s09 잠금·버전 라우터 +
s10 휴지통 라우터·스케줄러가 조립된 상태**(`app.main.create_app`)이므로 잠금·저장·취소·
강제해제·버전 목록(카탈로그 행 24~28)·휴지통 목록·복구·완전삭제(행 29~31) 라우트가 노출된다.

pytest 는 fixture 를 정의된 디렉터리 트리에서만 수집하므로, 형제 디렉터리(L3/L2/L1)의
fixture 는 L4 에서 보이도록 **명시적 re-import** 해야 한다(L3 conftest 의 re-import 패턴 답습).
L3 conftest 의 ``__all__`` 이 이미 `harness`(L1)·`ws_scenario`/`WorkspaceScenario`(L2)를 자신의
네임스페이스로 재-export 하므로, 이 모듈은 그 하나의 지점에서 하네스·워크스페이스 시나리오·
문서 트리·엔진 접근 픽스처를 한꺼번에 재-import 한다.

이 모듈이 신규로 추가하는 것은 **잠금 시나리오**·**휴지통 시나리오**·**스윕 접근** 세 픽스처다:

1. ``lock_scenario`` (:class:`LockScenario`): ``ws_scenario`` 위에 **두 번째 editor(B)**를
   생성해 EDITOR 멤버로 추가하고, 기존 editor 를 editor A 로 노출한다. 동일 워크스페이스에
   두 editor(A·B)와 owner/viewer/비멤버/admin 세션을 구성해 후속 스위트(잠금 왕복·타인 차단
   409·게이팅)가 문서당 잠금 최대 1인(INV-9)을 관찰하게 한다.
2. ``trash_scenario`` (:class:`TrashScenario`): ``doc_tree_scenario`` 문서 트리를 실제
   ``DELETE /documents/{id}`` 로 trashed 시켜 서로 다른 ``trashed_at`` 의 **독립 묶음**(손자
   단독 묶음·루트+자식 묶음)을 구성하고, 워크스페이스 ``trash_retention_days`` 를 알려진 값
   으로 설정한다. ``pin_trashed_at``·``set_retention``·``status_of`` 재사용 표면을 노출해
   후속 스위트(보관 스윕 독립성)가 만료 경계를 결정적으로 검증한다.
3. ``sweep_access`` (:class:`SweepAccess`): 부팅 앱과 **동일 세션 팩토리**
   (`harness.session_local`)로 실제 s10 `RetentionSweepService`(+실제 s07 엔진 + s10
   `TrashRepository`)를 조립해, 주입된 ``now`` 로 ``sweep_expired_bundles`` 를 구동하고 전환
   묶음 수를 반환한다(실제 s10·s07 코드 실행, mock 아님).

세션 수명 설계(테스트 시드 조작 vs 스윕 서비스):
    ``harness.session_local`` 은 부팅 앱이 `get_db` override 로 쓰는 **바로 그** 세션 팩토리다.
    ``trashed_at`` 핀 고정·retention 설정은 이 팩토리로 직접 DB 행을 갱신하는 **테스트 시드
    조작**이며, 엔진 삭제 캐스케이드는 `utcnow()` 로 공통 trashed_at 을 부여하므로 만료 경계를
    결정적으로 검증하려면 그 값을 초 단위(마이크로초 0, DATETIME(0) 반올림 회피) 과거값으로
    덮어쓴다. 스윕 서비스는 trashed_at 을 직접 쓰지 않는다(만료 판정만 하고 전이는 엔진 위임).

제약(design §L4TestHarness):
- 어떤 애플리케이션 코드·`config.yml`·L3/L2/L1 하네스 자산도 수정하지 않는다(재사용만). 동일
  하네스를 중복 정의하지 않는다.
- mock·stub 미사용(엔진·스윕 직접 호출은 실제 s07·s10 코드 실행이므로 허용). 설정은 s01
  `Settings` 재사용(additive `trash_sweep_interval_seconds` 포함, L1 하네스 경유).
- DB 미가용·부팅 실패 시 스킵이 아니라 **실패**(L1 `harness` 가 오류를 전파; 여기서
  ``pytest.skip`` 을 쓰지 않는다).
- 공유 `markspace_test` DB 오염 방지를 위해 사용자·문서마다 고유 접미사(uuid4)를 쓴다.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.document.engine import DocumentStateEngine
from app.document.repository import DocumentRepository
from app.models import Document, Workspace
from app.trash.repository import TrashRepository
from app.trash.retention import RetentionSweepService
from tests.integration_L1 import helpers as l1_helpers
from tests.integration_L2 import helpers as l2_helpers
from tests.integration_L3 import helpers as l3_helpers

# L3 conftest 에서 하네스·워크스페이스 시나리오·문서 트리·엔진 접근 픽스처를 한꺼번에 재-import
# 한다(L3 __all__ 이 L1 `harness`·L2 `ws_scenario`/`WorkspaceScenario` 를 이미 재-export 함).
# pytest 는 형제 디렉터리 fixture 를 자동 수집하지 않으므로 명시적 re-import 가 필요하다.
from tests.integration_L3.conftest import (  # noqa: F401 — L3(및 하위) 하네스 픽스처 재사용
    DocumentEngineAccess,
    DocumentTreeScenario,
    WorkspaceScenario,
    doc_tree_scenario,
    engine_access,
    harness,
    ws_scenario,
)

__all__ = [
    # (재사용) L3/L2/L1 하네스 재-export
    "harness",
    "ws_scenario",
    "WorkspaceScenario",
    "doc_tree_scenario",
    "DocumentTreeScenario",
    "engine_access",
    "DocumentEngineAccess",
    # (신규) L4 하네스 확장
    "LockScenario",
    "lock_scenario",
    "TrashScenario",
    "trash_scenario",
    "SweepAccess",
    "sweep_access",
]

# 휴지통 시나리오 기본 보관일(알려진 값 — 만료 산정 근거). 후속 스위트가 재설정 가능.
_DEFAULT_RETENTION_DAYS = 30
# 휴지통 시나리오 고정 기준 시각(마이크로초 0, DATETIME(0) 정합). 스윕 테스트가 이 값을
# ``now`` 로 주입해 묶음별 만료 경계를 결정적으로 검증한다.
_TRASH_REFERENCE = datetime(2026, 7, 17, 0, 0, 0)


# =============================================================================
# (1) 잠금 시나리오 — 두 editor(A·B) + role 세션 (design §L4TestHarness)
# =============================================================================


@dataclass
class LockScenario:
    """구성된 워크스페이스 + **두 editor(A·B)** + role별 세션 번들 (design §L4TestHarness).

    ``ws_scenario`` 가 만든 owner/editor/viewer/비멤버/admin 세션·워크스페이스 위에, 동일
    워크스페이스의 두 번째 EDITOR 멤버(editor B)를 추가한 상태다. 기존 editor 를 editor A 로
    노출한다. 후속 스위트(잠금 왕복·타인 차단 409·강제해제 게이팅)가 문서당 잠금 최대 1인
    (INV-9)과 role별 경계를 이 하나의 셋업 위에서 표현한다.

    필드:
    - ``scenario``: 재사용된 :class:`WorkspaceScenario` (owner/viewer/비멤버/admin·workspace).
    - ``editor_a_client`` / ``editor_b_client``: 동일 워크스페이스의 두 EDITOR 멤버 세션(각자
      독립 세션 쿠키).
    - ``editor_a_user_id`` / ``editor_b_user_id``: 두 editor 의 실제 사용자 id.
    """

    scenario: WorkspaceScenario
    editor_a_client: TestClient
    editor_b_client: TestClient
    editor_a_user_id: int
    editor_b_user_id: int

    @property
    def workspace_id(self) -> int:
        """구성된 워크스페이스 id (편의 접근)."""
        return self.scenario.workspace_id

    @property
    def owner_client(self) -> TestClient:
        return self.scenario.owner_client

    @property
    def viewer_client(self) -> TestClient:
        return self.scenario.viewer_client

    @property
    def nonmember_client(self) -> TestClient:
        return self.scenario.nonmember_client

    @property
    def admin_client(self) -> TestClient:
        return self.scenario.admin_client

    @property
    def owner_user_id(self) -> int:
        return self.scenario.owner_user_id

    @property
    def viewer_user_id(self) -> int:
        return self.scenario.viewer_user_id

    @property
    def nonmember_user_id(self) -> int:
        return self.scenario.nonmember_user_id


@pytest.fixture
def lock_scenario(ws_scenario, harness) -> LockScenario:
    """동일 워크스페이스에 두 editor(A·B)와 owner/viewer/비멤버/admin 세션을 구성한 시나리오.

    구성 절차(모두 실제 라우트·실제 세션, mock 없음):

    1. ``ws_scenario`` 로 owner/editor/viewer/비멤버/admin 세션·워크스페이스를 확보한다
       (기존 editor 가 editor A — 이미 EDITOR 멤버).
    2. admin 경로(L1 `create_user`)로 두 번째 사용자를 생성하고 그 자격으로 로그인해 editor B
       세션을 만든다(고유 login_id 로 공유 DB 충돌 회피).
    3. owner 세션이 ``POST /workspaces/{id}/members`` 로 editor B 를 EDITOR 멤버로 추가한다
       (L2 `add_member` 재사용, owner 게이트 통과).

    ``ws_scenario`` 는 editor 를 하나만 만들므로, 문서당 잠금 최대 1인(INV-9)·타인 차단(409)을
    관찰하려면 같은 워크스페이스의 두 번째 EDITOR 가 필요하다 — 그 최소 증분만 이 픽스처가
    더한다. 반환된 :class:`LockScenario` 로 후속 스위트가 잠금 왕복·게이팅을 관찰한다.
    """
    editor_a_client = ws_scenario.editor_client
    editor_a_user_id = ws_scenario.editor_user_id

    # editor B 신규 생성(admin 경로) + 로그인(독립 세션) + EDITOR 멤버 추가(owner 게이트).
    admin_client = ws_scenario.admin_client
    login_id = l1_helpers.unique_login_id("editor-b")
    editor_b_user_id = l1_helpers.create_user(
        admin_client, login_id, l1_helpers.DEFAULT_PASSWORD, name="에디터B"
    )
    editor_b_client = harness.login(login_id, l1_helpers.DEFAULT_PASSWORD)
    l2_helpers.add_member(
        ws_scenario.owner_client,
        ws_scenario.workspace_id,
        editor_b_user_id,
        "member",
    )

    return LockScenario(
        scenario=ws_scenario,
        editor_a_client=editor_a_client,
        editor_b_client=editor_b_client,
        editor_a_user_id=editor_a_user_id,
        editor_b_user_id=editor_b_user_id,
    )


# =============================================================================
# (2) 휴지통 시나리오 — 독립 묶음 구성 + trashed_at 핀/retention 설정 표면
# =============================================================================


@dataclass
class TrashScenario:
    """문서 트리를 trashed 시켜 구성한 **독립 묶음**(서로 다른 trashed_at) 시나리오 번들.

    ``doc_tree_scenario`` 의 루트→자식→손자 트리에서 손자를 단독 삭제(손자 묶음)한 뒤 루트를
    삭제(루트+자식 묶음)해, 이미 trashed 된 손자를 흡수하지 않는(비흡수) **두 독립 묶음**을
    만든다. 두 삭제가 같은 벽시계 초에 일어나 DATETIME(0) 초 절삭으로 trashed_at 이 충돌하면
    하나의 묶음으로 재구성될 수 있으므로, 픽스처가 서로 다른 초단위 과거값으로 핀 고정해
    **결정적으로** 독립 묶음을 보증한다(손자=기준시각 40일 전(만료 후보)·루트+자식=5일 전
    (미만료)). 워크스페이스 ``trash_retention_days`` 는 알려진 값(:data:`_DEFAULT_RETENTION_DAYS`)
    으로 설정한다.

    후속 스위트(보관 스윕 독립성)가 만료 경계·묶음 독립성을 결정적으로 검증하도록,
    ``pin_trashed_at``·``set_retention``·``status_of`` 재사용 표면과 기준 시각(``reference``)을
    노출한다(모두 부팅 앱과 동일 세션 팩토리로 직접 DB 관찰/시드 — 스윕 서비스는 이들을
    쓰지 않는다).

    필드:
    - ``tree``: 재사용된 :class:`DocumentTreeScenario`(role 세션·workspace·문서 트리).
    - ``session_local``: 부팅 앱과 동일한 세션 팩토리(`harness.session_local`).
    - ``retention_days``: 현재 설정된 보관일(핀 고정·설정 반영).
    - ``reference``: 만료 산정 기준 시각(마이크로초 0). 스윕 테스트가 ``now`` 로 주입한다.
    """

    tree: DocumentTreeScenario
    session_local: sessionmaker
    retention_days: int = _DEFAULT_RETENTION_DAYS
    reference: datetime = field(default=_TRASH_REFERENCE)

    @property
    def scenario(self) -> WorkspaceScenario:
        """재사용된 :class:`WorkspaceScenario`(role 세션 표면, 편의 접근)."""
        return self.tree.scenario

    @property
    def workspace_id(self) -> int:
        return self.tree.workspace_id

    @property
    def editor_client(self) -> TestClient:
        """트리를 만들고 문서를 삭제한 editor 세션(편의 접근)."""
        return self.tree.editor_client

    @property
    def root_id(self) -> int:
        """루트 묶음 루트 문서 id(구성원: 루트+자식, 미만료로 핀)."""
        return self.tree.root_id

    @property
    def child_id(self) -> int:
        return self.tree.child_id

    @property
    def grandchild_id(self) -> int:
        """손자 묶음 루트 문서 id(단독 구성원, 만료 후보로 핀)."""
        return self.tree.grandchild_id

    def set_retention(self, days: int) -> None:
        """워크스페이스 ``trash_retention_days`` 를 직접 DB 갱신으로 설정한다(만료 산정 근거).

        부팅 앱과 동일 세션 팩토리로 s05 설정값을 결정적으로 고정한다(테스트 시드 조작).
        ``retention_days`` 필드에도 반영해 후속 관찰의 단일 출처로 삼는다.
        """
        with self.session_local() as db:
            ws = db.get(Workspace, self.workspace_id)
            assert ws is not None, (
                f"대상 워크스페이스가 있어야 한다: id={self.workspace_id}"
            )
            ws.trash_retention_days = days
            db.commit()
        self.retention_days = days

    def pin_trashed_at(self, document_ids, ts: datetime) -> None:
        """묶음 구성원 전체의 ``trashed_at`` 을 결정적 초단위 과거값으로 핀 고정한다(테스트 시드).

        엔진 ``DELETE`` 캐스케이드는 ``utcnow()`` 로 공통 trashed_at 을 부여하므로 만료 경계를
        결정적으로 검증하려면 그 값을 고정값으로 덮어쓴다. 묶음은 동일 trashed_at 연결로
        재구성되므로 한 묶음의 구성원 전체에 **같은** 값을 부여해 묶음 경계를 유지한다.
        DATETIME(0) 반올림을 피하려 마이크로초 0 값을 쓴다(스윕 서비스는 trashed_at 을 쓰지
        않는다).
        """
        ts = ts.replace(microsecond=0)
        with self.session_local() as db:
            for document_id in document_ids:
                doc = db.get(Document, document_id)
                assert doc is not None, f"핀 대상 문서가 있어야 한다: id={document_id}"
                doc.trashed_at = ts
            db.commit()

    def status_of(self, document_id: int) -> str | None:
        """부팅 앱과 동일 세션으로 문서 행의 ``status`` 를 신규 세션으로 직접 관측한다(없으면 None)."""
        with self.session_local() as db:
            doc = db.get(Document, document_id)
            return None if doc is None else doc.status


@pytest.fixture
def trash_scenario(doc_tree_scenario, harness) -> TrashScenario:
    """문서 트리를 trashed 시켜 서로 다른 trashed_at 의 독립 묶음 2개를 구성한 시나리오.

    구성 절차(모두 실제 라우트·실제 세션·직접 DB 시드, mock 없음):

    1. ``doc_tree_scenario`` 로 루트→자식→손자 트리와 role 세션·워크스페이스를 확보한다.
    2. 워크스페이스 ``trash_retention_days`` 를 알려진 값(:data:`_DEFAULT_RETENTION_DAYS`)으로
       설정한다.
    3. editor 가 손자를 단독 삭제(손자 묶음), 이후 루트를 삭제(루트+자식 묶음)한다 — 삭제
       캐스케이드는 이미 trashed 된 손자를 제외하므로(비흡수) 루트 묶음 구성원은 루트+자식뿐.
    4. 두 삭제가 같은 초에 일어나 trashed_at 이 충돌하면 하나의 묶음으로 재구성될 수 있으므로,
       손자=기준시각 40일 전·루트+자식=5일 전으로 핀 고정해 **결정적으로** 독립 묶음을 보증
       한다(손자 만료 후보·루트 미만료).

    반환된 :class:`TrashScenario` 로 후속 스위트가 휴지통 목록·복구·완전삭제·보관 스윕
    독립성을 관찰한다. ``pin_trashed_at``·``set_retention`` 으로 시나리오별 만료 경계를 재조정
    할 수 있다.
    """
    scenario = TrashScenario(
        tree=doc_tree_scenario, session_local=harness.session_local
    )
    scenario.set_retention(_DEFAULT_RETENTION_DAYS)

    editor = doc_tree_scenario.editor_client
    # 손자 단독 삭제(손자 묶음) → 루트 삭제(루트+자식 묶음). 비흡수로 두 독립 묶음.
    l3_helpers.delete_document(editor, doc_tree_scenario.grandchild_id)
    l3_helpers.delete_document(editor, doc_tree_scenario.root_id)

    # 결정적 독립 묶음 보증(서로 다른 초단위 값 → 묶음 분리·만료 경계 고정).
    scenario.pin_trashed_at(
        [doc_tree_scenario.grandchild_id], _TRASH_REFERENCE - timedelta(days=40)
    )
    scenario.pin_trashed_at(
        [doc_tree_scenario.root_id, doc_tree_scenario.child_id],
        _TRASH_REFERENCE - timedelta(days=5),
    )
    return scenario


# =============================================================================
# (3) 스윕 접근 — 부팅 앱과 동일 세션으로 실제 s10 스윕을 now 주입 구동
# =============================================================================


class SweepAccess:
    """부팅 앱과 동일 세션 팩토리로 실제 s10 `RetentionSweepService` 를 구동하는 접근 핸들.

    부팅 앱이 `get_db` override 로 쓰는 **같은** 세션 팩토리(`harness.session_local`)로
    실제 s07 엔진(`DocumentStateEngine`+`DocumentRepository`)과 s10 `TrashRepository` 를
    조립한 실제 스윕 서비스를 만든다. API 가 커밋한 trashed 행 위에서 주입된 ``now`` 로
    보관 만료 스윕이 동작함을 관찰한다(엔진 `identify_bundles`·`purge_bundle` 위임, INV-12).
    어떤 것도 mock 하지 않는다.

    노출 표면:
    - ``session_local``: 부팅 앱과 동일한 세션 팩토리.
    - ``service``: 주입된 실제 :class:`RetentionSweepService`.
    - :meth:`sweep`: 새 세션을 열어 ``sweep_expired_bundles(db, now)`` 를 구동하고 커밋한 뒤
      전환한 묶음 수를 반환한다(``now`` 주입으로 만료 경계 결정성).
    - :meth:`status_of`: 신규 세션으로 문서 ``status`` 를 직접 관측(스윕 결과 DB 관찰).
    """

    def __init__(self, session_local: sessionmaker) -> None:
        self.session_local = session_local
        self.service = RetentionSweepService(
            engine=DocumentStateEngine(DocumentRepository()),
            repository=TrashRepository(),
        )

    def sweep(self, now: datetime) -> int:
        """새 세션으로 주입된 ``now`` 기준 스윕을 1회 구동하고 전환한 묶음 수를 반환한다.

        부팅 앱과 동일 세션 팩토리를 써서 API 가 커밋한 trashed 행 위에서 실제 스윕이 동작함을
        관찰한다(엔진 `identify_bundles`·`purge_bundle` 만으로 동작). 세션 수명(commit·close)은
        이 핸들이 소유한다.
        """
        with self.session_local() as db:
            purged = self.service.sweep_expired_bundles(db, now)
            db.commit()
        return purged

    def status_of(self, document_id: int) -> str | None:
        """신규 세션으로 문서 행의 ``status`` 를 직접 관측한다(없으면 None)."""
        with self.session_local() as db:
            doc = db.get(Document, document_id)
            return None if doc is None else doc.status


@pytest.fixture
def sweep_access(harness) -> SweepAccess:
    """부팅 앱과 동일 세션 팩토리로 실제 s10 `RetentionSweepService` 를 조립한 스윕 접근 핸들.

    `harness.session_local` 은 앱 `get_db` override 와 **동일한** 세션 팩토리이므로, 여기서
    구동하는 스윕은 API 가 커밋한 trashed 행을 그대로 관찰·전이한다(동일 DB·커밋 경계 정렬).
    실제 s07 엔진 + s10 `TrashRepository` 를 주입하며 어떤 것도 mock 하지 않는다. ``now`` 는
    :meth:`SweepAccess.sweep` 호출 시 주입해 만료 경계를 결정적으로 검증한다.
    """
    return SweepAccess(harness.session_local)
