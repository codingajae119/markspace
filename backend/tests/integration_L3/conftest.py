"""L3 통합 테스트 하네스 (Task 1.1 / Req 1.1·1.2·1.3·1.4, design §L3TestHarness).

mock 없이 s01 ⊕ s02 ⊕ s03 ⊕ s05 ⊕ **s07** 의 실제 구현을 결합한 검증 환경을 제공한다.
핵심 원칙은 **L2 하네스 재사용**(중복 신설 금지)이다: 마이그레이션(`alembic upgrade head`)·
`s01` `create_app()` 부팅·admin 시드·세션 유지 `TestClient` 팩토리·고유 login_id 생성기·
워크스페이스 생성·멤버 추가(role)·role별 세션 클라이언트는 모두 `s06` `tests/integration_L2`
자산(그리고 그것이 재사용하는 `s04` `tests/integration_L1`)을 그대로 쓴다. 부팅 앱은
s02·s03·s05·**s07 문서 라우터가 조립된 상태**(`app.main.create_app`)이므로 문서 CRUD·이동·
삭제 라우트(s01 카탈로그 행 18~23)가 노출된다.

이 모듈이 신규로 추가하는 것은 **문서 트리 셋업 픽스처**와 **엔진 접근 픽스처** 둘뿐이다:

1. ``harness`` 를 L1 conftest 에서, ``ws_scenario``·``WorkspaceScenario`` 를 L2 conftest 에서
   재-import 하여 L3 스위트에서도 보이게 한다(pytest 는 fixture 를 정의된 디렉터리 트리에서만
   수집하므로, 상위 트리가 아닌 형제 디렉터리의 fixture 는 명시적 re-import 가 필요하다).
2. ``doc_tree_scenario`` : ``ws_scenario`` 위에서 editor 가 문서 트리(루트→자식→손자)를 실제
   라우트(`POST /workspaces/{id}/documents`)로 생성한 **구성된 시나리오**를 반환한다. 후속
   스위트(2.x)가 계층·이동·삭제 캐스케이드를 관찰하는 공용 셋업이다.
3. ``engine_access`` : 부팅 앱과 **동일한 세션 팩토리**(`harness.session_local`)로 `s07`
   `DocumentStateEngine`(+`DocumentRepository`)을 인스턴스화해, API 경유 상태 변경을 엔진
   primitive 로 관찰(복구·완전삭제·묶음 열거 직접 호출)할 수 있게 한다.

세션 수명 설계(설계 노트, 관측 누락 방지):
    ``harness.session_local`` 은 부팅 앱이 `get_db` override 로 쓰는 **바로 그** 세션 팩토리이며
    `expire_on_commit=False` 로 구성돼 있다. repository 쓰기 메서드가 커밋으로 내구 영속화하므로,
    이 팩토리에서 **매 엔진 호출마다 새 세션**을 열면 그 세션은 API 가 커밋한 최신 행을 신선하게
    관찰한다(오래된 identity-map 재사용으로 인한 stale 읽기 회피). 그래서 :class:`DocumentEngineAccess`
    는 (a) 호출마다 새 세션을 열고 종료 시 닫는 컨텍스트 매니저(:meth:`~DocumentEngineAccess.session`)와
    (b) 관찰 편의를 위해 새 세션을 스스로 열어 primitive 를 호출하는 :meth:`~DocumentEngineAccess.identify_bundles`
    를 제공한다. `Document` 객체를 인자로 받는 primitive(`active_descendants`·`trash_document`)나
    문서를 로드해 함께 조작해야 하는 시나리오는 :meth:`~DocumentEngineAccess.session` 안에서 문서를
    로드한 뒤 ``engine`` 을 직접 호출한다(같은 세션 일관성). 나머지 primitive 호출 래퍼는 helpers
    (task 1.2)가 이 접근 객체 위에 얹는다.

제약(design §L3TestHarness):
- 어떤 애플리케이션 코드·L2/L1 하네스 자산도 수정하지 않는다(재사용만). 동일 하네스를 중복
  정의하지 않는다.
- mock·stub 미사용(엔진 직접 호출은 실제 s07 코드 실행이므로 허용). 설정은 s01 `Settings`
  재사용(L1 하네스 경유).
- DB 미가용 시 스킵이 아니라 **실패**(L1 `harness` 가 연결 오류를 전파; 여기서 ``pytest.skip``
  을 쓰지 않는다).
- 공유 `notion_lite_test` DB 오염 방지를 위해 문서 제목마다 고유 접미사(uuid4)를 쓴다.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.document.engine import Bundle, DocumentStateEngine
from app.document.repository import DocumentRepository
from tests.integration_L1.conftest import harness  # noqa: F401 — L1 하네스 fixture 재사용
from tests.integration_L2.conftest import (  # noqa: F401 — L2 워크스페이스 시나리오 재사용
    WorkspaceScenario,
    ws_scenario,
)

__all__ = [
    "harness",
    "ws_scenario",
    "WorkspaceScenario",
    "doc_tree_scenario",
    "DocumentTreeScenario",
    "engine_access",
    "DocumentEngineAccess",
]


def _unique_title(prefix: str) -> str:
    """공유 ``notion_lite_test`` DB 에서 충돌하지 않는 고유 문서 제목을 만든다."""
    return f"{prefix}-{uuid4().hex[:12]}"


def _make_doc(client, workspace_id: int, title: str, parent_id: int | None = None) -> dict:
    """editor 세션으로 ``POST /workspaces/{id}/documents`` 를 태워 문서를 만든다.

    SETUP 헬퍼 — 201 을 단언하고 파싱된 ``DocumentRead`` dict 를 반환한다. 하네스 셋업 전용
    (음성 경로 관찰은 후속 스위트/helpers 의 attempt 래퍼가 담당).
    """
    body: dict[str, object] = {"title": title}
    if parent_id is not None:
        body["parent_id"] = parent_id
    resp = client.post(f"/workspaces/{workspace_id}/documents", json=body)
    assert resp.status_code == 201, (
        f"문서 생성 201 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


@dataclass
class DocumentTreeScenario:
    """구성된 워크스페이스 + role별 세션 + 문서 트리(루트→자식→손자) 번들 (design §L3TestHarness).

    ``ws_scenario`` 가 만든 role별 세션·워크스페이스 위에서 editor 가 3단계 문서 트리를 실제
    라우트로 생성한 상태다. 후속 스위트(2.x)가 계층·이동·삭제 캐스케이드·묶음 재구성을 이
    하나의 셋업 위에서 표현한다.

    필드:
    - ``scenario``: 재사용된 :class:`WorkspaceScenario` (role별 클라이언트·user_id·admin 등).
    - ``root`` / ``child`` / ``grandchild``: 각 문서의 파싱된 ``DocumentRead`` dict
      (root ← child ← grandchild 계층; 모두 editor 가 생성, status=active).
    """

    scenario: WorkspaceScenario
    root: dict
    child: dict
    grandchild: dict

    @property
    def workspace_id(self) -> int:
        """구성된 워크스페이스 id (편의 접근)."""
        return self.scenario.workspace_id

    @property
    def editor_client(self):
        """트리를 생성한 editor 세션 클라이언트 (편의 접근)."""
        return self.scenario.editor_client

    @property
    def root_id(self) -> int:
        return self.root["id"]

    @property
    def child_id(self) -> int:
        return self.child["id"]

    @property
    def grandchild_id(self) -> int:
        return self.grandchild["id"]


@pytest.fixture
def doc_tree_scenario(ws_scenario) -> DocumentTreeScenario:
    """editor 가 루트→자식→손자 3단계 문서 트리를 실제 라우트로 생성한 시나리오.

    구성 절차(모두 실제 라우트·실제 세션, mock 없음):

    1. ``ws_scenario`` 로 role별 세션·워크스페이스를 확보(editor 는 EDITOR 멤버).
    2. editor 가 루트 문서를 생성(parent 없음, 201).
    3. editor 가 루트 밑에 자식 문서를 생성(`parent_id=root`, 201).
    4. editor 가 자식 밑에 손자 문서를 생성(`parent_id=child`, 201).

    고유 제목(uuid4)으로 공유 테스트 DB 충돌을 피한다. 반환된 :class:`DocumentTreeScenario`
    로 후속 스위트가 계층·이동·삭제 캐스케이드를 관찰한다.
    """
    editor = ws_scenario.editor_client
    ws_id = ws_scenario.workspace_id

    root = _make_doc(editor, ws_id, _unique_title("루트"))
    child = _make_doc(editor, ws_id, _unique_title("자식"), parent_id=root["id"])
    grandchild = _make_doc(
        editor, ws_id, _unique_title("손자"), parent_id=child["id"]
    )

    return DocumentTreeScenario(
        scenario=ws_scenario,
        root=root,
        child=child,
        grandchild=grandchild,
    )


class DocumentEngineAccess:
    """부팅 앱과 동일 DB 를 보는 `s07` `DocumentStateEngine` 접근 핸들 (design §L3TestHarness).

    부팅 앱이 `get_db` override 로 쓰는 **같은** 세션 팩토리(`harness.session_local`)로
    엔진을 인스턴스화하므로, API 경유 커밋을 엔진 primitive 로 관찰할 수 있다(복구·완전삭제·
    묶음 열거의 라우터 밖 재사용 경계 선검증). 오래된 identity-map 재사용으로 인한 stale 읽기를
    피하려 **호출마다 새 세션**을 여는 접근을 취한다(모듈 docstring 세션 수명 설계 참조).

    노출 표면:
    - ``engine``: 주입된 :class:`DocumentStateEngine` (모든 primitive 는 `db: Session` 을 첫
      인자로 받는다).
    - ``session_local``: 부팅 앱과 동일한 세션 팩토리(`harness.session_local`).
    - :meth:`session`: 호출마다 새 세션을 열고 종료 시 닫는 컨텍스트 매니저(같은 세션 안에서
      문서 로드 + primitive 호출이 필요한 시나리오용).
    - :meth:`identify_bundles`: 새 세션을 스스로 열어 ``engine.identify_bundles`` 를 호출하고
      결과(`list[Bundle]`)를 반환하는 관찰 편의(task 1.1 관찰 가능 완료 기준).
    """

    def __init__(self, engine: DocumentStateEngine, session_local: sessionmaker) -> None:
        self.engine = engine
        self.session_local = session_local

    @contextmanager
    def session(self) -> Iterator[Session]:
        """호출마다 새 세션을 열고 종료 시 닫는다(API 커밋 후 신선 관찰 보장)."""
        db = self.session_local()
        try:
            yield db
        finally:
            db.close()

    def identify_bundles(self, workspace_id: int) -> list[Bundle]:
        """새 세션으로 ``engine.identify_bundles(db, workspace_id)`` 를 호출해 결과를 반환한다.

        휴지통에 아무것도 없으면 빈 리스트다(그 자체로 정상) — 핵심은 primitive 가 동일 DB
        위에서 오류 없이 호출 가능하다는 관찰이다(라우터 밖 재사용 경계).
        """
        with self.session() as db:
            return self.engine.identify_bundles(db, workspace_id)


@pytest.fixture
def engine_access(harness) -> DocumentEngineAccess:
    """부팅 앱과 동일 세션 팩토리로 `s07` `DocumentStateEngine` 을 인스턴스화한 접근 핸들.

    `harness.session_local` 은 앱 `get_db` override 와 **동일한** 세션 팩토리이므로, 여기서
    만든 엔진은 API 가 커밋한 행을 그대로 관찰한다(동일 DB·커밋 경계 정렬). `DocumentRepository`
    를 주입한 실제 s07 엔진을 쓰며 어떤 것도 mock 하지 않는다.
    """
    engine = DocumentStateEngine(DocumentRepository())
    return DocumentEngineAccess(engine=engine, session_local=harness.session_local)
