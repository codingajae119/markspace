"""잠금·삭제 독립 / 멱등·충돌 / 버전 무한 보관 / 카탈로그·마이그레이션 정합 통합 스위트 —
s09 잠금/버전 불변식 e2e (Task 4.2 / s09 Req 3.2·4.3·4.4·5.2·5.3·5.4·6.1·6.2·6.3·6.4·7.2·7.4·7.5,
design §Testing Strategy → Integration Tests(잠금·삭제 독립 §4.3 / 카탈로그·마이그레이션 정합) +
Contract Consistency Tests, §Boundary Commitments(Out of Boundary), §Data Models(append-only,
no migration)).

Task 4.1(`test_lock_version_roundtrip.py`)의 왕복·게이팅·취소/강제 시나리오와 **중복되지 않는**
보완 스위트로, 다음 네 영역을 실 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕**s09**) 위에서 mock 없이
검증한다:

1. **잠금·삭제 독립(§4.3, Req 6.1·6.2·6.3·6.4)** — editor 가 잠근 문서를 s07
   `DocumentStateEngine.trash_document`(s09 아님)으로 trashed 전이시켜도 잠금 필드가 유지되고,
   잠금·저장·취소가 status 와 무관하게 계속 동작하며, s09 가 어떤 상태 전이도 수행하지 않음
   (저장/취소 후에도 status 는 여전히 trashed)을 확인한다.
2. **멱등/충돌(Req 1.3·3.2·4.3·2.5·3.3)** — 동일 보유자 재잠금 멱등(잠금 불변)·미잠금 취소/강제
   해제 멱등(no-op)·타인 잠금 시 시작·저장·취소 409(버전 미생성).
3. **버전 무한 보관(Req 5.2·5.3·5.4)** — 다회 저장이 버전을 누적(최신순 메타데이터 전용)하고
   기존 버전을 삭제·덮어쓰지 않으며, rollback·과거 본문 조회 라우트가 존재하지 않음.
4. **카탈로그·마이그레이션 정합(Req 7.1·7.2·7.4·7.5)** — 부팅 앱이 카탈로그 행 24~28 을
   노출하고, s09 가 새 마이그레이션을 추가하지 않으며, s01 `document`·`document_version` 스키마만
   사용(새 테이블 없음)함.

이 스위트는 test-authoring task 로 feature 는 이미 조립·구현되어 있다("역-RED": 새 테스트가 실제
구현 위에서 **통과**하는 것이 검증). product 코드는 건드리지 않는다. 잠금·삭제 독립이 깨지면
단언을 약화시키지 않고 실제 회귀(s09/s07 버그)를 그대로 표면화한다(BLOCKED 라우팅).
"""

import re
from datetime import datetime
from pathlib import Path

from app.main import app as booted_app
from app.models import Base, Document
from tests.integration_L1 import helpers as l1_helpers

# 카탈로그 행 24~28 (path param 은 라우터 정의상 `{id}`).
CATALOG_PATHS = {
    "/documents/{id}/lock": "post",
    "/documents/{id}/save": "post",
    "/documents/{id}/cancel": "post",
    "/documents/{id}/force-unlock": "post",
    "/documents/{id}/versions": "get",
}

# s01 이 소유·확정한 7개 테이블(마이그레이션 0001). s09 는 여기에 아무 테이블도 더하지 않는다.
S01_TABLES = {
    "user",
    "workspace",
    "workspace_member",
    "document",
    "document_version",
    "attachment",
    "share_link",
}

# s01 `document_version` 컬럼(본문 포함 — 저장 스냅샷 저장소). 응답 스키마와 달리 테이블은 content 를 담는다.
DOCUMENT_VERSION_COLUMNS = {"id", "document_id", "content", "created_by", "created_at"}


def _provision_editor(scenario, harness, *, prefix: str):
    """admin 이 사용자를 만들고 owner 가 editor 로 멤버 추가한 뒤 그 자격으로 로그인한다.

    타인-잠금 충돌 관측용 두 번째 editor(B)를 실제 라우트로 provision 하는 setup 헬퍼다
    (roundtrip 4.1 `_provision_member` 의 editor 특화 재현). (user_id, 인증 client) 반환.
    """
    login_id = l1_helpers.unique_login_id(prefix)
    user_id = l1_helpers.create_user(
        scenario.admin_client, login_id, l1_helpers.DEFAULT_PASSWORD, name=prefix
    )
    resp = scenario.owner_client.post(
        f"/workspaces/{scenario.workspace_id}/members",
        json={"user_id": user_id, "role": "editor"},
    )
    assert resp.status_code == 201, (
        f"editor 멤버 추가 201 이어야 한다: {resp.status_code} {resp.text}"
    )
    client = harness.login(login_id, l1_helpers.DEFAULT_PASSWORD)
    return user_id, client


def _trash_via_s07(engine_access, document_id: int) -> None:
    """s07 `DocumentStateEngine.trash_document` 로 문서를 active→trashed 전이시킨다(s09 아님).

    부팅 앱과 **동일 세션 팩토리**에서 문서를 로드해 실제 엔진 primitive 를 호출한다
    (`set_status_bulk` 가 단일 커밋). 이후 API 요청(새 세션)이 trashed 행을 신선 관찰한다.
    잠금·버전 동작이 상태 전이와 무관함을 관찰하기 위한 셋업으로, s09 코드를 전혀 태우지 않는다.
    """
    with engine_access.session() as db:
        document = db.get(Document, document_id)
        assert document is not None, f"trash 대상 문서를 찾을 수 없다: id={document_id}"
        assert document.status == "active", (
            f"trash_document 는 active 문서만 받는다(현재 status={document.status})"
        )
        engine_access.engine.trash_document(db, document)


def _load_document(engine_access, document_id: int) -> Document:
    """API 가 커밋한 최신 행을 새 세션으로 신선 로드한다(잠금·status 관찰용).

    세션이 닫히기 전에 필요한 스칼라를 읽도록 호출자가 with 없이 즉시 필드를 읽는 대신, 여기서는
    `expire_on_commit=False` 세션에서 로드 직후 필요한 스칼라만 접근하도록 얇게 감싼다 — 반환된
    객체의 status·lock_user_id 는 로드 시점 값으로 이미 채워져 있어 detached 여도 안전하다.
    """
    with engine_access.session() as db:
        document = db.get(Document, document_id)
        assert document is not None, f"문서를 찾을 수 없다: id={document_id}"
        # 세션이 살아 있는 동안 스칼라를 강제 로드(이후 detached 접근 안전).
        _ = (document.status, document.lock_user_id, document.lock_acquired_at)
        return document


def _versions(client, document_id: int) -> dict:
    """`GET /documents/{id}/versions` Page dict(`{items, total}`)를 반환한다(200 단언)."""
    resp = client.get(f"/documents/{document_id}/versions")
    assert resp.status_code == 200, (
        f"버전 목록 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


# =============================================================================
# 1) 잠금·삭제 독립 (§4.3) — 핵심 — Req 6.1·6.2·6.3·6.4, 3.2
# =============================================================================


def test_lock_survives_trash_and_save_is_status_independent(
    doc_tree_scenario, harness, engine_access
):
    """editor A 잠금 → s07 trash → 잠금 유지(B 409·row lock_user_id==A) → A 저장 성공(버전 생성·
    잠금 해제) → status 는 여전히 trashed(s09 무전이).

    핵심(§4.3): 잠금 필드는 s07 상태 전이(trashed)에도 그대로 유지되고(Req 6.2), 잠금·저장 동작은
    문서 status 와 독립적으로 계속 동작하며(Req 6.1), s09 는 어떤 상태 전이도 수행하지 않는다
    (저장 후에도 status==trashed, Req 6.3). 잠금 판정 근거는 `lock_user_id` 단일 컬럼(Req 6.4).
    """
    scenario = doc_tree_scenario.scenario
    doc_id = doc_tree_scenario.root_id
    editor_a = doc_tree_scenario.editor_client
    editor_a_id = scenario.editor_user_id

    editor_b_id, editor_b = _provision_editor(scenario, harness, prefix="indepEdB")
    assert editor_b_id != editor_a_id, "두 editor 는 서로 다른 사용자여야 한다"

    # (1) A 가 잠금 획득(active 상태).
    lock_a = editor_a.post(f"/documents/{doc_id}/lock")
    assert lock_a.status_code == 200, (
        f"A 잠금 획득 200 이어야 한다: {lock_a.status_code} {lock_a.text}"
    )
    assert lock_a.json()["lock_user_id"] == editor_a_id, "잠금 보유자는 A"

    # (2) s07 엔진으로 trashed 전이(s09 아님).
    _trash_via_s07(engine_access, doc_id)

    # (3) 잠금이 trash 전이에서 살아남는다: row 의 status=trashed 이지만 lock_user_id 는 여전히 A(Req 6.2).
    after_trash = _load_document(engine_access, doc_id)
    assert after_trash.status == "trashed", "s07 trash 로 status 는 trashed 여야 한다"
    assert after_trash.lock_user_id == editor_a_id, (
        "trash 전이에도 잠금 필드가 유지되어야 한다(잠금·삭제 독립, Req 6.2)"
    )

    # (4) 잠금이 여전히 유효함을 API 로도 관측: 다른 editor B 의 잠금 시도는 409(INV-9 유지, status 무관).
    assert editor_b.post(f"/documents/{doc_id}/lock").status_code == 409, (
        "trashed 문서라도 A 의 잠금이 유지되므로 B 잠금은 409 여야 한다(Req 6.1·6.2)"
    )

    # (5) 저장이 status 와 독립적으로 동작: 보유자 A 가 trashed 문서에 저장 → 200(버전 생성·잠금 해제).
    before = _versions(editor_a, doc_id)["total"]
    save_a = editor_a.post(f"/documents/{doc_id}/save", json={"content": "# on-trashed"})
    assert save_a.status_code == 200, (
        f"trashed 문서에 대한 보유자 저장은 200 이어야 한다(status 독립, Req 6.1): "
        f"{save_a.status_code} {save_a.text}"
    )
    version = save_a.json()
    assert version["document_id"] == doc_id, "생성 버전은 대상 문서 소속"
    assert version["created_by"] == editor_a_id, "저장자는 A"
    assert "content" not in version, "버전 응답은 본문을 노출하지 않는다(메타데이터 전용)"
    assert _versions(editor_a, doc_id)["total"] == before + 1, (
        "trashed 문서 저장도 새 버전을 만든다(버전 생성 status 독립)"
    )

    # (6) s09 는 상태 전이를 수행하지 않았다: 저장 후에도 status 는 여전히 trashed(Req 6.3),
    #     잠금은 저장으로 해제(lock_user_id=NULL) — s09 는 잠금 필드/버전만 다룰 뿐 status 를 되돌리지 않는다.
    after_save = _load_document(engine_access, doc_id)
    assert after_save.status == "trashed", (
        "s09 저장은 status 를 바꾸지 않는다 — 여전히 trashed 여야 한다(Req 6.3, 상태 전이 미수행)"
    )
    assert after_save.lock_user_id is None, (
        "저장은 잠금을 해제한다(lock_user_id=NULL) — 잠금 필드만 조작"
    )


def test_cancel_on_trashed_document_does_not_transition_status(
    doc_tree_scenario, engine_access
):
    """editor A 잠금 → s07 trash → A 취소 204 → status 는 여전히 trashed·버전 미생성(§4.3, Req 6.3·3.2).

    취소도 status 와 독립이다: trashed 문서에서 취소가 잠금만 풀고(204) 어떤 버전도 만들지 않으며,
    s09 는 status 를 되돌리지 않는다(여전히 trashed). 잠금·삭제 독립의 취소 흐름 확인.
    """
    doc_id = doc_tree_scenario.child_id
    editor_a = doc_tree_scenario.editor_client

    assert editor_a.post(f"/documents/{doc_id}/lock").status_code == 200, "A 잠금 획득 200"
    _trash_via_s07(engine_access, doc_id)

    before = _versions(editor_a, doc_id)["total"]
    assert editor_a.post(f"/documents/{doc_id}/cancel").status_code == 204, (
        "trashed 문서에 대한 보유자 취소는 204 여야 한다(status 독립, Req 6.1)"
    )
    assert _versions(editor_a, doc_id)["total"] == before, "취소는 버전을 만들지 않는다(3.2·3.4)"

    after = _load_document(engine_access, doc_id)
    assert after.status == "trashed", (
        "s09 취소는 status 를 바꾸지 않는다 — 여전히 trashed(Req 6.3, 상태 전이 미수행)"
    )
    assert after.lock_user_id is None, "취소는 잠금만 해제(lock_user_id=NULL)"


# =============================================================================
# 2) 멱등 / 충돌 — Req 1.3, 3.2, 4.3, 2.5, 3.3
# =============================================================================


def test_same_holder_relock_is_idempotent(doc_tree_scenario, engine_access):
    """동일 보유자 재잠금은 멱등 성공(200)이며 잠금이 불변(보유자·획득 시각 동일)이다(Req 1.3).

    editor A 가 잠근 뒤 다시 잠금을 요청해도 기존 잠금을 유지한 채 200 을 반환한다. `lock_acquired_at`
    은 MySQL DATETIME(초 정밀도, 삽입 시 **반올림**)이라 첫 잠금 응답은 in-memory 마이크로초 값이지만
    DB 확정값은 반올림된다 — 이 둘을 직접 비교하면 소수부 ≥0.5 일 때 1초 어긋나 flaky 하다. 따라서
    첫 잠금이 DB 에 남긴 반올림 값을 신선 재로드(DB-반올림)한 뒤, 재잠금 응답(역시 DB 재로드)이 그
    값과 **정확히 일치**함을 단언한다(DB-vs-DB, 둘 다 반올림). 재잠금이 획득 시각을 뒤로 bump/재기록
    했다면 이 동등성은 깨진다. 3회차 재잠금이 2회차와 정확히 동일함으로 반복 재잠금의 무-write 를
    재확인한다.
    """
    doc_id = doc_tree_scenario.grandchild_id
    editor_a = doc_tree_scenario.editor_client
    editor_a_id = doc_tree_scenario.scenario.editor_user_id

    first = editor_a.post(f"/documents/{doc_id}/lock")
    assert first.status_code == 200, f"첫 잠금 200: {first.status_code} {first.text}"

    # 첫 잠금이 DB 에 확정한 lock_acquired_at 을 신선 세션으로 재로드해 DB-반올림 기준값을 얻는다.
    persisted = _load_document(engine_access, doc_id)
    assert persisted.lock_user_id == editor_a_id, "첫 잠금 후 DB 상 보유자는 A"
    db_acquired_at = persisted.lock_acquired_at
    assert db_acquired_at is not None, "첫 잠금은 lock_acquired_at 을 영속화한다"

    second = editor_a.post(f"/documents/{doc_id}/lock")
    assert second.status_code == 200, (
        f"동일 보유자 재잠금은 멱등 200 이어야 한다(1.3): {second.status_code} {second.text}"
    )
    second_body = second.json()

    assert second_body["lock_user_id"] == editor_a_id, "재잠금 후에도 보유자는 A(불변)"
    assert second_body["document_id"] == doc_id, "재잠금 응답 document_id 는 대상 문서"
    # DB-vs-DB 비교: 재잠금 응답의 lock_acquired_at(get_for_update 재로드값)이 첫 잠금이 DB 에 남긴
    # 반올림 값과 정확히 일치해야 한다 — 둘 다 DATETIME(0) 반올림이라 절삭 없이 동등, 재잠금이 획득
    # 시각을 뒤로 bump/재기록했다면 깨진다(재기록 없음, 1.3).
    assert datetime.fromisoformat(second_body["lock_acquired_at"]) == db_acquired_at, (
        "멱등 재잠금은 기존 잠금을 유지한다 — lock_acquired_at 이 첫 잠금의 DB 확정값과 동일해야 한다"
        f"(재기록 없음, 1.3): 응답 {second_body['lock_acquired_at']} vs DB {db_acquired_at.isoformat()}"
    )
    # 3회차 재잠금도 동일 값(둘 다 DB 재로드 반올림) — 반복 재잠금이 write 하지 않음을 재확인.
    third = editor_a.post(f"/documents/{doc_id}/lock")
    assert third.status_code == 200, "3회차 재잠금도 멱등 200"
    assert third.json()["lock_acquired_at"] == second_body["lock_acquired_at"], (
        "반복 재잠금은 잠금을 write 하지 않는다 — 획득 시각이 안정적으로 불변(1.3·1.4)"
    )


def test_unlocked_cancel_and_force_unlock_are_idempotent_noops(doc_tree_scenario):
    """미잠금 문서의 취소(editor 204)·강제해제(owner 204)는 멱등 no-op 이며 버전을 만들지 않는다
    (Req 3.2·4.3).

    잠금이 걸려있지 않은 문서에 대해 취소·강제해제가 오류가 아니라 성공(204)으로 처리되고, 어떤
    `document_version` 도 생성하지 않는다(버전 개수 불변).
    """
    scenario = doc_tree_scenario.scenario
    ws_id = doc_tree_scenario.workspace_id
    editor = doc_tree_scenario.editor_client
    owner = scenario.owner_client

    # 미잠금 신규 문서(잠금 없음 확인용).
    doc_id = editor.post(
        f"/workspaces/{ws_id}/documents", json={"title": "멱등-미잠금"}
    ).json()["id"]

    before = _versions(editor, doc_id)["total"]
    assert before == 0, "신규 문서는 버전이 없어야 한다"

    # 미잠금 취소 → 멱등 204(no-op).
    assert editor.post(f"/documents/{doc_id}/cancel").status_code == 204, (
        "미잠금 문서 취소는 멱등 204(no-op)여야 한다(3.2)"
    )
    # 미잠금 강제해제(owner) → 멱등 204(no-op).
    assert owner.post(f"/documents/{doc_id}/force-unlock").status_code == 204, (
        "미잠금 문서 강제해제는 멱등 204(no-op)여야 한다(4.3)"
    )

    assert _versions(editor, doc_id)["total"] == before, (
        "멱등 취소·강제해제는 어떤 버전도 만들지 않는다(no-op)"
    )


def test_other_holder_conflict_blocks_start_save_cancel(doc_tree_scenario, harness):
    """editor A 잠금 → editor B 의 시작·저장·취소는 모두 409 이며 어떤 버전도 만들지 않는다
    (Req 2.5·3.3, INV-9).

    타인(B)이 잠금을 시도(409)·저장(409, 버전 미생성)·취소(409)하는 세 충돌 경로를 한 번에 관측한다.
    저장 충돌이 버전을 만들지 않음을 버전 개수 불변으로 확인한다.
    """
    scenario = doc_tree_scenario.scenario
    doc_id = doc_tree_scenario.root_id
    editor_a = doc_tree_scenario.editor_client
    editor_a_id = scenario.editor_user_id

    editor_b_id, editor_b = _provision_editor(scenario, harness, prefix="conflEdB")
    assert editor_b_id != editor_a_id, "두 editor 는 서로 다른 사용자여야 한다"

    assert editor_a.post(f"/documents/{doc_id}/lock").status_code == 200, "A 잠금 획득 200"
    before = _versions(editor_a, doc_id)["total"]

    # B 의 세 변경 연산은 A 잠금 충돌로 모두 409.
    assert editor_b.post(f"/documents/{doc_id}/lock").status_code == 409, (
        "타인 잠금 문서 편집 시작은 409(INV-9)"
    )
    save_b = editor_b.post(f"/documents/{doc_id}/save", json={"content": "B네요"})
    assert save_b.status_code == 409, (
        f"보유자 아닌 저장은 409 여야 한다(2.5): {save_b.status_code} {save_b.text}"
    )
    assert editor_b.post(f"/documents/{doc_id}/cancel").status_code == 409, (
        "타인 잠금 문서 취소는 409(3.3)"
    )

    # 저장 충돌은 어떤 버전도 만들지 않았다(버전 개수 불변, 2.5).
    assert _versions(editor_a, doc_id)["total"] == before, (
        "보유자 아닌 저장(409)은 어떤 버전도 만들지 않는다(2.5)"
    )
    # A 의 잠금은 B 의 시도들에 의해 훼손되지 않았다(여전히 A 가 보유).
    assert editor_a.post(f"/documents/{doc_id}/lock").status_code == 200, (
        "B 의 충돌 시도 뒤에도 A 는 여전히 보유자(멱등 재잠금 200)"
    )


# =============================================================================
# 3) 버전 무한 보관 — Req 5.2, 5.3, 5.4
# =============================================================================


def test_multiple_saves_accumulate_metadata_only_latest_first(doc_tree_scenario):
    """다회 저장이 버전을 누적하고(최신순 메타데이터 전용) 기존 버전을 삭제·덮어쓰지 않는다
    (Req 5.2·5.4).

    저장은 잠금을 해제하므로 매 저장마다 재잠금이 필요하다(lock→save→lock→save…). N회 저장 후
    목록의 `total`==N, 각 버전 id 보존(무한 보관), 최신순(`created_at DESC, id DESC`) 정렬, 각
    항목은 id/document_id/created_by/created_at 메타데이터만(본문 없음)임을 확인한다.
    """
    ws_id = doc_tree_scenario.workspace_id
    editor = doc_tree_scenario.editor_client
    editor_id = doc_tree_scenario.scenario.editor_user_id

    # 깨끗한 버전 카운트를 위해 신규 문서를 쓴다.
    doc_id = editor.post(
        f"/workspaces/{ws_id}/documents", json={"title": "버전보관"}
    ).json()["id"]

    n = 3
    saved_ids: list[int] = []
    for i in range(n):
        assert editor.post(f"/documents/{doc_id}/lock").status_code == 200, (
            f"{i}회차 재잠금 200(저장이 잠금을 해제하므로 재잠금 필요)"
        )
        save = editor.post(f"/documents/{doc_id}/save", json={"content": f"버전 {i}"})
        assert save.status_code == 200, f"{i}회차 저장 200: {save.status_code} {save.text}"
        saved_ids.append(save.json()["id"])

    assert len(set(saved_ids)) == n, "각 저장은 서로 다른 새 버전 id 를 만든다(덮어쓰기 없음)"

    page = _versions(editor, doc_id)
    assert page["total"] == n, f"저장 {n}회 후 total 은 {n} 이어야 한다(무한 보관, 5.2)"

    listed_ids = [item["id"] for item in page["items"]]
    # 기존 버전 미삭제: 저장한 모든 id 가 목록에 남아있다(5.2).
    assert set(saved_ids).issubset(set(listed_ids)), (
        "저장한 모든 버전 id 가 목록에 남아 있어야 한다(기존 버전 미삭제, 5.2)"
    )
    # 최신 저장 순: id 오름차순 저장이므로 목록은 id 내림차순(latest-first, 5.4).
    assert listed_ids == sorted(saved_ids, reverse=True), (
        "버전 목록은 최신 저장 순(id 내림차순)이어야 한다(5.4)"
    )

    # 메타데이터 전용: 각 항목은 4개 메타데이터만 담고 본문을 노출하지 않는다(5.3·5.4).
    for item in page["items"]:
        assert {"id", "document_id", "created_by", "created_at"} <= set(item.keys()), (
            "각 버전 항목은 id/document_id/created_by/created_at 메타데이터를 담아야 한다(5.4)"
        )
        assert "content" not in item and "body" not in item, (
            "버전 목록 항목은 본문(content/body)을 노출하지 않는다(메타데이터 전용, 5.3)"
        )
        assert item["document_id"] == doc_id, "각 버전은 대상 문서 소속"
        assert item["created_by"] == editor_id, "각 버전 저장자는 editor"


def test_no_rollback_or_past_version_body_route_exists():
    """API 표면에 rollback/restore 라우트나 과거 버전 본문 조회(`/versions/{version_id}`)가 없다
    (Req 5.3, 메타데이터 전용·rollback 미도입).

    부팅 앱 OpenAPI 경로에서 (a) `/versions/{...}` 형태의 개별 버전 본문 경로가 없고, (b)
    rollback/restore 를 뜻하는 경로가 없음을 확인한다 — s09 는 목록(메타데이터) 열람만 노출한다.
    """
    paths = booted_app.openapi()["paths"]

    # (a) `/documents/{id}/versions/{version_id}` 같은 개별 버전(본문) 경로 부재.
    version_item_paths = [p for p in paths if re.search(r"/versions/\{[^}]+\}", p)]
    assert version_item_paths == [], (
        f"개별 버전 본문/복원 경로가 있으면 안 된다(rollback·과거 본문 미제공, 5.3): {version_item_paths}"
    )

    # (b) rollback/restore 를 뜻하는 경로 부재(버전 복원 라우트 없음).
    restore_paths = [
        p for p in paths if "rollback" in p.lower() or "restore" in p.lower()
    ]
    assert restore_paths == [], (
        f"rollback/restore 라우트가 있으면 안 된다(복원 기능 미도입, 5.3): {restore_paths}"
    )

    # s09 가 노출하는 유일한 버전 경로는 목록(`/documents/{id}/versions`) GET 뿐이다.
    assert "/documents/{id}/versions" in paths, "버전 목록 경로는 노출되어야 한다"
    assert "get" in paths["/documents/{id}/versions"], "버전 경로는 GET(목록)만 노출한다"


# =============================================================================
# 4) 카탈로그 · 마이그레이션 정합 — Req 7.1, 7.2, 7.4, 7.5
# =============================================================================


def test_catalog_rows_24_28_exposed_with_expected_methods():
    """부팅 앱이 카탈로그 행 24~28(lock/save/cancel/force-unlock/versions)을 정확한 메서드로 노출한다
    (Req 7.1·7.6).

    lazy 라우터(`_IncludedRouter`) 때문에 `app.routes` 가 아니라 `app.openapi()["paths"]` 로
    확인한다. 5개 경로가 각각 post/post/post/post/get 으로 존재해야 한다.
    """
    paths = booted_app.openapi()["paths"]
    for path, method in CATALOG_PATHS.items():
        assert path in paths, f"카탈로그 경로가 노출되어야 한다: {path} (Req 7.1·7.6)"
        assert method in paths[path], (
            f"경로 {path} 는 {method.upper()} 메서드로 노출되어야 한다: 실제 {sorted(paths[path])}"
        )


def test_s09_added_no_new_migration():
    """s09 는 새 마이그레이션을 추가하지 않았다 — `migrations/versions/` 는 기존 0001 초기 스키마뿐이다
    (Req 7.2).

    테스트 파일 위치에서 리포 레이아웃으로 유도한 `backend/migrations/versions/` 를 열거해(하드코딩
    절대경로 회피), 마이그레이션 파일이 `0001_initial_schema.py` 하나뿐이고 lock/version 관련
    마이그레이션이 없음을 확인한다.
    """
    # parents[0]=integration_L3, [1]=tests, [2]=backend.
    versions_dir = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    assert versions_dir.is_dir(), f"migrations/versions 디렉터리가 있어야 한다: {versions_dir}"

    migration_files = sorted(
        p.name for p in versions_dir.glob("*.py") if p.name != "__init__.py"
    )
    assert migration_files == ["0001_initial_schema.py"], (
        f"s09 는 새 마이그레이션을 추가하지 않아야 한다 — 0001 초기 스키마뿐이어야 한다(7.2): "
        f"{migration_files}"
    )
    # lock/version 특화 마이그레이션 부재(추가 안전망).
    assert not any(
        "lock" in name or "version" in name for name in migration_files
    ), f"s09 lock/version 마이그레이션이 있으면 안 된다(7.2): {migration_files}"


def test_only_s01_document_and_document_version_schemas_used():
    """s09 는 s01 `document`·`document_version` 스키마만 쓰고 새 테이블을 도입하지 않았다(Req 7.2).

    SQLAlchemy `Base.metadata.tables` 를 반사해 s01 확정 7개 테이블만 존재하고(새 `lock_version`
    류 테이블 없음), `document_version` 테이블이 기대 컬럼(id/document_id/content/created_by/
    created_at)을 그대로 가짐을 확인한다.
    """
    tables = set(Base.metadata.tables.keys())
    assert tables == S01_TABLES, (
        f"s01 확정 7개 테이블만 존재해야 한다(s09 새 테이블 없음, 7.2): "
        f"예상 {S01_TABLES}, 실제 {tables}"
    )
    assert "lock_version" not in tables, "s09 는 lock_version 전용 테이블을 도입하지 않는다"

    dv_columns = set(Base.metadata.tables["document_version"].columns.keys())
    assert dv_columns == DOCUMENT_VERSION_COLUMNS, (
        f"document_version 컬럼은 s01 스키마 그대로여야 한다: "
        f"예상 {DOCUMENT_VERSION_COLUMNS}, 실제 {dv_columns}"
    )
