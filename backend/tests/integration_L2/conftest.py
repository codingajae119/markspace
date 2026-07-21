"""L2 통합 테스트 하네스 (Task 1.1 / Req 1.1·1.2·1.3·1.4, design §L2TestHarness).

mock 없이 s01 ⊕ s02 ⊕ s03 ⊕ **s05** 의 실제 구현을 결합한 검증 환경을 제공한다. 핵심
원칙은 **L1 하네스 재사용**(중복 신설 금지)이다: 마이그레이션(`alembic upgrade head`)·
`s01` `create_app()` 부팅·admin 시드·세션 유지 `TestClient` 팩토리·고유 login_id 생성기는
모두 `s04` `tests/integration_L1` 자산을 그대로 쓴다. 부팅 앱은 s02·s03·**s05 라우터가
조립된 상태**(`app.main.create_app`)이므로 워크스페이스·소유권 라우트가 노출된다.

이 모듈이 신규로 추가하는 것은 **워크스페이스·role 시나리오 픽스처**뿐이다:

- ``harness`` 를 L1 conftest 에서 재-import 하여 L2 스위트에서도 보이게 한다(pytest 는
  fixture 를 정의된 디렉터리 트리에서만 수집하므로, 상위 트리가 아닌 형제 디렉터리의
  fixture 는 명시적 re-import 가 필요하다).
- ``ws_scenario`` : admin 으로 owner/editor/viewer/비멤버 사용자를 각각 생성하고 각자
  세션을 유지하는 role별 클라이언트를 만든 뒤, owner 가 워크스페이스를 생성하고 **editor 를
  member 로 멤버 추가**한 **구성된 시나리오**를 반환한다. 후속 스위트(2.2~2.6)가 role별 실제
  세션으로 게이트 통과·거부·admin bypass 를 관찰하는 공용 셋업이다.

## s26 2단계 모델 + 읽기 전역 개방 반영 (field 명칭은 하위 스위트 호환 위해 보존)
- ``editor_client``/``editor_user_id`` = **member** 멤버(role="member"). 편집 허용, 관리 거부.
  (구 editor 는 member 로 이관 — 편집 권한 유지.)
- ``viewer_client``/``viewer_user_id`` = **비멤버 활성 사용자**(워크스페이스에 추가하지 않음).
  구 viewer 역할은 삭제됐고, "읽을 수 있으나 편집 불가"는 이제 비멤버 활성 사용자가 표현한다:
  읽기는 전역 개방(200)이고 편집은 멤버십 요구(403)이므로, 구 viewer 의 읽기-200·편집-403 단언이
  비멤버로도 그대로 성립한다. field 명칭은 하위 스위트 호환 위해 ``viewer_*`` 로 보존한다.
- ``nonmember_client``/``nonmember_user_id`` = 비멤버 활성 사용자(동일 부류 — 읽기 개방·편집 거부).

제약(design §L2TestHarness):
- 어떤 애플리케이션 코드·L1 자산도 수정하지 않는다(재사용만).
- mock·stub 미사용. 설정은 s01 `Settings` 재사용(L1 하네스 경유).
- DB 미가용 시 스킵이 아니라 **실패**(L1 `harness` 가 연결 오류를 전파; 여기서
  ``pytest.skip`` 을 쓰지 않는다).
- 공유 `notion_lite_test` DB 오염 방지를 위해 사용자마다 고유 login_id 를 쓴다.
"""

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from tests.integration_L1 import helpers
from tests.integration_L1.conftest import harness  # noqa: F401 — L1 하네스 fixture 재사용

__all__ = ["harness", "ws_scenario", "WorkspaceScenario"]


@dataclass
class WorkspaceScenario:
    """구성된 워크스페이스 + role별 세션 클라이언트 번들 (design §L2TestHarness).

    후속 스위트(2.2~2.6)가 role 위계·admin override·소유권 변경 시나리오를 이 하나의
    셋업 위에서 표현한다. 각 ``*_client`` 는 자신의 세션 쿠키를 유지하는 독립
    :class:`TestClient` 이고, 각 ``*_user_id`` 는 s03 `POST /admin/users` 로 생성된 실제
    사용자 id 다.

    필드:
    - ``workspace_id``: owner 가 ``POST /workspaces`` 로 생성한 워크스페이스 id(owner 자동
      등록). editor·viewer 가 지정 role 로 멤버 추가된 상태.
    - ``owner_client``: owner 멤버, ``editor_client``: member 멤버(편집 허용).
    - ``viewer_client``: 비멤버 활성 사용자(읽기 개방·편집 거부 — 구 viewer 역할 대체).
    - ``nonmember_client``: 생성·로그인되었으나 이 워크스페이스 멤버가 아닌 사용자.
    - ``admin_client``: 시드 admin 의 인증 클라이언트(멤버 아님 — admin bypass 관찰용).
    - ``owner_user_id`` / ``editor_user_id`` / ``viewer_user_id`` / ``nonmember_user_id``:
      각 사용자 id(멤버십/소유권/계정상태 시나리오에서 대상 지정에 사용).
    """

    workspace_id: int
    owner_client: TestClient
    editor_client: TestClient
    viewer_client: TestClient
    nonmember_client: TestClient
    admin_client: TestClient
    owner_user_id: int
    editor_user_id: int
    viewer_user_id: int
    nonmember_user_id: int


def _create_and_login(harness, admin: TestClient, prefix: str, name: str):
    """비-admin 사용자를 생성하고(admin 경로) 그 자격으로 로그인해 (user_id, client) 반환.

    setup 헬퍼 — L1 `helpers.create_user`(201 단언) 와 `harness.login`(200 단언) 를
    재사용한다. 고유 login_id 로 공유 테스트 DB 충돌을 피한다. 반환하는 클라이언트는
    자신의 세션 쿠키를 유지한다.
    """
    login_id = helpers.unique_login_id(prefix)
    user_id = helpers.create_user(
        admin, login_id, helpers.DEFAULT_PASSWORD, name=name
    )
    client = harness.login(login_id, helpers.DEFAULT_PASSWORD)
    return user_id, client


@pytest.fixture
def ws_scenario(harness) -> WorkspaceScenario:
    """admin 이 여러 사용자를 만들고 owner 가 워크스페이스를 role별로 구성한 시나리오.

    구성 절차(모두 실제 라우트·실제 세션, mock 없음):

    1. admin 세션 확보(``harness.login_admin``).
    2. owner/editor/viewer/비멤버 사용자를 각각 생성·로그인(role별 독립 세션 클라이언트).
    3. owner 가 ``POST /workspaces`` 로 워크스페이스 생성(요청자 자동 owner 등록, 201).
    4. owner 가 ``POST /workspaces/{id}/members`` 로 **editor 를 member 로 추가**(201).

    viewer·비멤버는 생성·로그인만 하고 멤버로 추가하지 않는다(s26 2단계 모델: 구 viewer 역할이
    삭제되어, "읽기 가능·편집 불가"는 비멤버 활성 사용자가 표현한다 — 읽기 전역 개방·편집 멤버십
    요구). admin 은 이 워크스페이스의 멤버가 아니다(admin bypass 관찰용). 반환된
    :class:`WorkspaceScenario` 로 후속 스위트가 role별 게이트를 관찰한다.
    """
    admin_client = harness.login_admin()

    owner_user_id, owner_client = _create_and_login(
        harness, admin_client, "owner", "오너"
    )
    editor_user_id, editor_client = _create_and_login(
        harness, admin_client, "editor", "에디터"
    )
    viewer_user_id, viewer_client = _create_and_login(
        harness, admin_client, "viewer", "뷰어"
    )
    nonmember_user_id, nonmember_client = _create_and_login(
        harness, admin_client, "nonmember", "비멤버"
    )

    # owner 가 워크스페이스를 생성한다(요청자가 owner 멤버로 자동 등록됨).
    create_resp = owner_client.post("/workspaces", json={"name": "L2 시나리오 워크스페이스"})
    assert create_resp.status_code == 201, (
        f"워크스페이스 생성 201 이어야 한다: {create_resp.status_code} {create_resp.text}"
    )
    workspace_id = create_resp.json()["id"]

    # owner 가 editor 를 member 로 멤버 추가한다(owner 게이트 통과). viewer·비멤버는 추가하지
    # 않는다(비멤버 활성 사용자로 읽기 개방·편집 거부를 표현).
    member_resp = owner_client.post(
        f"/workspaces/{workspace_id}/members",
        json={"user_id": editor_user_id, "role": "member"},
    )
    assert member_resp.status_code == 201, (
        f"member 멤버 추가 201 이어야 한다: "
        f"{member_resp.status_code} {member_resp.text}"
    )

    return WorkspaceScenario(
        workspace_id=workspace_id,
        owner_client=owner_client,
        editor_client=editor_client,
        viewer_client=viewer_client,
        nonmember_client=nonmember_client,
        admin_client=admin_client,
        owner_user_id=owner_user_id,
        editor_user_id=editor_user_id,
        viewer_user_id=viewer_user_id,
        nonmember_user_id=nonmember_user_id,
    )
