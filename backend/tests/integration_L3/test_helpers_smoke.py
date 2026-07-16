"""Task 1.2 관찰 가능 완료 스모크 — 문서·엔진 헬퍼가 실제 라우트·실제 엔진을 구동함을 검증.

이 스모크는 mock 없이 부팅된 결합 런타임(마이그레이션 DB + `app.main.create_app` + 실제
멤버십/문서 데이터 + 실제 `DocumentStateEngine`) 위에서 helpers 래퍼를 태운다:

1. editor 세션으로 :func:`create_document` 래퍼가 루트 + 두 하위 문서를 실제
   ``POST /workspaces/{id}/documents`` 로 생성(201)한다.
2. :func:`move_document` 래퍼가 실제 ``POST /documents/{id}/move`` 로 childB 를 childA 밑으로
   재부모화한다(200, 응답의 parent_id 반영 확인).
3. :func:`delete_document` 래퍼가 실제 ``DELETE /documents/{id}`` 로 루트를 삭제 → 엔진
   `trash_document` 캐스케이드가 그 시점 active 하위(root·childA·childB)를 trashed 로 전환한다.
4. :func:`get_bundle` 엔진 primitive 래퍼가 루트 묶음을 재구성해 구성원 스냅샷을 반환하고,
   구성원 집합이 {root, childA, childB} 임을 단언한다(detached-safe 스냅샷 비교).

이는 래퍼가 실제 라우트 + 실제 엔진을 구동함을(trivial pass 가 아님을) 관찰한다: 생성·이동은
API 커밋을, 삭제는 엔진 캐스케이드를, get_bundle 은 커밋된 trashed 행의 묶음 재구성을 관찰한다.
"""

from tests.integration_L3 import helpers as h


def _title(prefix: str) -> str:
    """공유 테스트 DB 충돌 회피용 고유 제목(L1 unique_login_id 관용 재사용)."""
    return h.l1_helpers.unique_login_id(prefix)


def test_document_and_engine_helpers_drive_real_runtime(ws_scenario, engine_access):
    """editor 가 문서 트리를 만들고 이동·삭제한 뒤 get_bundle 이 묶음 구성원을 반환한다."""
    editor = ws_scenario.editor_client
    ws_id = ws_scenario.workspace_id

    # 1. 실제 라우트로 루트 + 두 하위 문서 생성(setup 래퍼가 201 단언).
    root = h.create_document(editor, ws_id, _title("루트"))
    child_a = h.create_document(editor, ws_id, _title("자식A"), parent_id=root["id"])
    child_b = h.create_document(editor, ws_id, _title("자식B"), parent_id=root["id"])

    # 2. 실제 이동 라우트로 childB 를 childA 밑으로 재부모화(setup 래퍼가 200 단언).
    moved = h.move_document(editor, child_b["id"], new_parent_id=child_a["id"])
    assert moved["parent_id"] == child_a["id"], "이동 후 parent_id 가 childA 여야 한다"

    # 3. 실제 삭제 라우트로 루트 삭제 → 엔진 캐스케이드가 root·childA·childB 를 trashed 로.
    h.delete_document(editor, root["id"])

    # 4. 엔진 primitive 래퍼로 루트 묶음 재구성(detached-safe 스냅샷).
    bundle = h.get_bundle(engine_access, root["id"])

    expected = {root["id"], child_a["id"], child_b["id"]}
    assert bundle.root_document_id == root["id"]
    assert bundle.member_ids == expected, (
        f"묶음 구성원은 root·childA·childB 여야 한다: {bundle.member_ids} != {expected}"
    )
    assert bundle.trashed_at is not None, "삭제된 묶음의 trashed_at 은 채워져 있어야 한다"
    assert all(m.status == "trashed" for m in bundle.members), (
        "캐스케이드 후 모든 구성원 status 는 trashed 여야 한다"
    )
    # 모든 구성원이 공통 trashed_at 을 공유한다(단일 삭제 캐스케이드).
    assert all(m.trashed_at == bundle.trashed_at for m in bundle.members)
