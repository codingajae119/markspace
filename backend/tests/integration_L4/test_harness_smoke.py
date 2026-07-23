"""L4 하네스 스모크 — Task 1.1 관찰 가능 완료 기준 (Req 1.1·1.2·1.3·1.4, design §L4TestHarness).

이 스위트는 태스크 1.1 하네스가 실제로 결합 환경을 제공하는지 mock 없이 확인한다("역-RED":
새 테스트가 실제 구현 위에서 **통과**하는 것이 검증). 검증 대상은 conftest 신규 픽스처
셋(``lock_scenario``·``trash_scenario``·``sweep_access``)이며, 각 픽스처가 부팅 앱(s09 잠금·
버전 라우터 + s10 휴지통 라우터가 조립된 상태)·마이그레이션 DB·실제 엔진/스윕과 결합됨을
관찰한다. 관찰 가능 완료 기준(tasks.md 1.1):

1. editor A 가 ``POST /documents/{id}/lock`` 에서 200 을 받는다(두 editor·role 세션 구성 증거).
2. ``GET /workspaces/{id}/trash`` 가 구성된 독립 묶음(들)을 반환한다.
3. 스윕 픽스처가 ``sweep_expired_bundles(db, now)`` 호출에서 결과(전환 묶음 수)를 반환한다.

L3(및 그것이 재사용하는 L2/L1) 하네스를 재사용하며 애플리케이션 코드·하위 하네스는 만지지
않는다. mock·stub·pytest.skip 미사용.
"""

from tests.integration_L3 import helpers as l3_helpers


def _uniq(prefix: str) -> str:
    """공유 ``markspace_test`` DB 에서 충돌하지 않는 고유 제목을 만든다."""
    return l3_helpers.l1_helpers.unique_login_id(prefix)


# =============================================================================
# 1) 두 editor(A·B) + role 세션 구성 — 서로 구별되는 인증 세션 제공 (Req 1.1·1.4)
# =============================================================================


def test_lock_scenario_provides_two_editors_and_role_sessions(lock_scenario):
    """``lock_scenario`` 가 동일 워크스페이스에 두 editor(A·B)와 owner/viewer/비멤버/admin
    세션을 **서로 구별되는 인증 세션**으로 제공한다(design §L4TestHarness, 두 editor 구성).

    editor A·B 는 서로 다른 사용자이며(고유 user_id), 둘 다 이 워크스페이스의 EDITOR 멤버라
    ``GET /workspaces/{id}`` 조회(VIEWER+)에 성공한다. owner/viewer/admin/비멤버 클라이언트도
    함께 노출되어 후속 스위트(잠금 게이팅·독립·엣지)가 role별 경계를 관찰할 수 있다.
    """
    ws_id = lock_scenario.workspace_id

    # editor A·B 는 서로 다른 사용자(고유 user_id) — 두 editor 구성의 핵심.
    assert lock_scenario.editor_a_user_id != lock_scenario.editor_b_user_id, (
        "editor A·B 는 서로 다른 사용자여야 한다(문서당 잠금 최대 1인 검증의 전제)"
    )

    # 두 editor 모두 이 워크스페이스 멤버라 조회(VIEWER+)에 성공한다(독립 인증 세션 증거).
    for client, label in (
        (lock_scenario.editor_a_client, "editor A"),
        (lock_scenario.editor_b_client, "editor B"),
    ):
        resp = client.get(f"/workspaces/{ws_id}")
        assert resp.status_code == 200, (
            f"{label} 는 EDITOR 멤버로 워크스페이스 조회 200 이어야 한다: "
            f"{resp.status_code} {resp.text}"
        )

    # role 세션 표면이 모두 노출된다(후속 스위트의 게이팅 관찰 전제).
    assert lock_scenario.owner_client is not None
    assert lock_scenario.viewer_client is not None
    assert lock_scenario.nonmember_client is not None
    assert lock_scenario.admin_client is not None


# =============================================================================
# 2) editor A 잠금 200 — s09 잠금 라우터 결합 (Req 1.1, 관찰 가능 완료 ①)
# =============================================================================


def test_editor_a_can_lock_document(lock_scenario):
    """editor A 가 문서를 만들고 ``POST /documents/{id}/lock`` 에서 200 을 받는다
    (s09 잠금 라우터가 부팅 앱에 조립되고 s07 문서→WS 어댑터로 게이팅됨을 관찰).

    응답 본문은 s01 ``DocumentLockRead`` 규약(``document_id``·``lock_user_id``·
    ``lock_acquired_at``)을 따르고 잠금 보유자가 editor A 임을 확인한다.
    """
    editor_a = lock_scenario.editor_a_client
    ws_id = lock_scenario.workspace_id

    doc = l3_helpers.create_document(editor_a, ws_id, _uniq("잠금대상"))

    resp = editor_a.post(f"/documents/{doc['id']}/lock")
    assert resp.status_code == 200, (
        f"editor A 의 잠금 시작은 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    body = resp.json()
    assert body["document_id"] == doc["id"]
    assert body["lock_user_id"] == lock_scenario.editor_a_user_id, (
        "잠금 보유자는 요청한 editor A 여야 한다(INV-9 단일 보유자)"
    )
    assert "lock_acquired_at" in body


# =============================================================================
# 3) 휴지통 목록 반환 — s10 휴지통 라우터 결합 (Req 1.1, 관찰 가능 완료 ②)
# =============================================================================


def test_trash_scenario_lists_independent_bundles(trash_scenario):
    """``trash_scenario`` 가 서로 다른 ``trashed_at`` 의 **독립 묶음**을 구성하고
    ``GET /workspaces/{id}/trash`` 가 그 묶음들을 ``Page[TrashBundleRead]`` 로 반환한다
    (s10 휴지통 목록 라우터 결합, editor+ 열람).

    손자 단독 삭제(손자 묶음)와 이후 루트 삭제(루트+자식 묶음)로 비흡수 독립 묶음 2개가
    구성되며, 목록에 두 묶음 루트가 모두 등장하고 각 묶음이 ``expires_at``(= trashed_at +
    retention)을 포함한다.
    """
    editor = trash_scenario.editor_client
    ws_id = trash_scenario.workspace_id

    resp = editor.get(f"/workspaces/{ws_id}/trash")
    assert resp.status_code == 200, (
        f"editor 의 휴지통 목록 조회는 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    page = resp.json()
    bundle_ids = {item["bundle_id"] for item in page["items"]}
    assert {trash_scenario.grandchild_id, trash_scenario.root_id} <= bundle_ids, (
        "구성된 두 독립 묶음(손자 묶음·루트 묶음)이 휴지통 목록에 모두 등장해야 한다: "
        f"{bundle_ids}"
    )
    # 각 묶음은 만료 예정 파생값을 포함한다(s10 expires_at 산정 결합).
    for item in page["items"]:
        assert "expires_at" in item and "trashed_at" in item


# =============================================================================
# 4) 스윕 접근 픽스처 — sweep_expired_bundles(db, now) 결과 반환 (관찰 가능 완료 ③)
# =============================================================================


def test_sweep_access_returns_result_from_injected_now(trash_scenario, sweep_access):
    """스윕 픽스처가 부팅 앱과 동일 세션으로 **주입된 now** 기준 실제
    ``RetentionSweepService.sweep_expired_bundles(db, now)`` 를 구동해 전환 묶음 수를 반환한다
    (실제 s10 스윕 + s07 엔진 결합, mock 아님).

    ``trash_scenario`` 는 손자 묶음을 기준시각 40일 전(만료)·루트 묶음을 5일 전(미만료)로
    핀 고정하고 retention=30 이므로, 기준시각을 now 로 주입하면 만료된 손자 묶음 1개만
    deleted 로 전환된다. 반환값이 int 이고 만료 묶음만 실제 완전삭제됨을 DB 로 관찰한다.
    """
    now = trash_scenario.reference

    purged = sweep_access.sweep(now)

    assert isinstance(purged, int), "스윕은 전환한 묶음 수(int)를 반환해야 한다"
    assert purged == 1, (
        f"기준시각 기준 만료된 손자 묶음 1개만 완전삭제되어야 한다: {purged}"
    )
    assert sweep_access.status_of(trash_scenario.grandchild_id) == "deleted", (
        "만료된 손자 묶음은 deleted 로 전환되어야 한다(주입 now 만료 경계)"
    )
    assert sweep_access.status_of(trash_scenario.root_id) == "trashed", (
        "미만료 루트 묶음은 자식 묶음 만료에 끌려가지 않고 trashed 로 유지되어야 한다(INV-12)"
    )
