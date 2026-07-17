"""보관 만료 자동 영구삭제 스윕 통합 스위트 — s10 `RetentionSweepService` e2e
(Task 4.2 / s10 Req 4.1·4.2·4.4·4.5·4.6·4.7·6.1, INV-12·10, design §Testing Strategy →
Integration Tests(자동 영구삭제 스윕), §RetentionSweepService, §System Flows 보관 만료 자동
영구삭제 스윕).

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s10) 위에서, s07 `DELETE /documents/{id}`
로 문서를 trashed 로 만든 뒤 **실제** `RetentionSweepService`(실제 s07 엔진 + s10
`TrashRepository`)를 `harness.session_local()`(부팅 앱과 동일 세션 팩토리) 위에서 직접 구동해
보관 만료 스윕의 실동작을 mock 없이 관찰한다. 만료 경계를 결정적으로 검증하기 위해 스윕에는
고정 `now` 를 **주입**하고, 각 묶음의 `trashed_at` 은 직접 DB 행 갱신으로 초 단위(마이크로초 0)
과거값에 **핀 고정**한다(테스트 시드 조작이며 스윕 서비스는 trashed_at 을 직접 쓰지 않는다,
DATETIME(0) 반올림 함정 회피). 워크스페이스별 `trash_retention_days` 도 DB 행 갱신으로 명시
설정해 교차 워크스페이스 만료 판정(Req 4.1)을 결정적으로 만든다.

이 스위트는 test-authoring task 로, feature 는 이미 조립·구현되어 있다("역-RED": 새 테스트가
실제 구현 위에서 **통과**하는 것이 검증). product 코드·기존 테스트는 건드리지 않는다.

결정성 근거(공유 `notion_lite_test` DB 에서 전역 반환 카운트 사용): 스윕 반환값은 전 워크스페이스
합산이지만, 주입 `now`(2026-07-17 00:00:00) 기준으로 **만료된 trashed 묶음은 이 테스트가 과거로
핀 고정한 묶음뿐**이다 — 다른 스위트가 남기는 trashed 묶음은 실제 `utcnow`(오늘) 기준 최근
trashed_at + 기본 보관일(30)이라 주입 `now` 로는 만료되지 않고, 이 스위트의 미만료 묶음도 마찬가지다.
각 테스트는 자기 만료 묶음을 스윕으로 deleted(휴지통에서 이탈)시키므로 만료 잔여가 누적되지 않는다.
"""

from datetime import datetime, timedelta
from uuid import uuid4

from app.document.engine import DocumentStateEngine
from app.document.repository import DocumentRepository
from app.models import Document, Workspace
from app.trash.repository import TrashRepository
from app.trash.retention import RetentionSweepService
from tests.integration_L3 import helpers

# 모든 만료 경계를 이 고정 시각에 대해 산정한다(초 단위, 마이크로초 0 — DATETIME(0) 정합).
_NOW = datetime(2026, 7, 17, 0, 0, 0)


def _uniq(prefix: str) -> str:
    """공유 ``notion_lite_test`` DB 에서 충돌하지 않는 고유 이름/제목을 만든다."""
    return f"{prefix}-{uuid4().hex[:12]}"


def _new_workspace(client) -> int:
    """`POST /workspaces` 로 워크스페이스를 만든다(요청자 자동 owner=EDITOR+). id 반환."""
    resp = client.post("/workspaces", json={"name": _uniq("WS")})
    assert resp.status_code == 201, (
        f"워크스페이스 생성 201 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()["id"]


def _set_retention(harness, workspace_id: int, days: int) -> None:
    """워크스페이스 `trash_retention_days` 를 직접 DB 갱신으로 명시 설정한다(만료 산정 근거).

    부팅 앱과 동일 세션 팩토리로 s05 설정값을 결정적으로 고정해 교차 워크스페이스 만료
    판정(Req 4.1)을 알려진 값으로 만든다(테스트 시드 조작).
    """
    with harness.session_local() as db:
        ws = db.get(Workspace, workspace_id)
        assert ws is not None, f"대상 워크스페이스가 있어야 한다: id={workspace_id}"
        ws.trash_retention_days = days
        db.commit()


def _pin_trashed_at(harness, doc_ids, ts: datetime) -> None:
    """묶음 구성원 전체의 `trashed_at` 을 결정적 초단위 과거값으로 핀 고정한다(테스트 시드).

    엔진 `DELETE` 캐스케이드는 `utcnow()` 로 공통 trashed_at 을 부여하므로 만료 경계를
    결정적으로 검증하려면 그 값을 고정값으로 덮어쓴다. 묶음은 동일 trashed_at 연결로
    재구성되므로 한 묶음의 구성원 전체에 **같은** 값을 부여해 묶음 경계를 유지한다. DATETIME(0)
    반올림을 피하려 마이크로초 0 값을 쓴다. 스윕 서비스는 trashed_at 을 쓰지 않는다.
    """
    ts = ts.replace(microsecond=0)
    with harness.session_local() as db:
        for doc_id in doc_ids:
            doc = db.get(Document, doc_id)
            assert doc is not None, f"핀 대상 문서가 있어야 한다: id={doc_id}"
            doc.trashed_at = ts
        db.commit()


def _status_of(harness, document_id: int) -> str | None:
    """부팅 앱과 동일 세션으로 문서 행의 `status` 를 신규 세션으로 직접 관측한다(없으면 None)."""
    with harness.session_local() as db:
        doc = db.get(Document, document_id)
        return None if doc is None else doc.status


def _run_sweep(harness, now: datetime) -> int:
    """실제 s07 엔진 + s10 `TrashRepository` 로 조립한 스윕 서비스를 `harness.session_local()`
    세션 위에서 주입된 `now` 로 1회 구동하고 전환한 묶음 수를 반환한다.

    부팅 앱과 동일 세션 팩토리를 써서 API 가 커밋한 trashed 행 위에서 실제 스윕이 동작함을
    관찰한다(엔진 `identify_bundles`·`purge_bundle` 만으로 동작, Req 6.1·INV-10·12).
    """
    service = RetentionSweepService(
        engine=DocumentStateEngine(DocumentRepository()),
        repository=TrashRepository(),
    )
    with harness.session_local() as db:
        purged = service.sweep_expired_bundles(db, now)
        db.commit()
    return purged


def _bundle_roots(engine_access, workspace_id: int) -> set[int]:
    """엔진 `identify_bundles` 로 워크스페이스의 trashed 묶음 루트 id 집합을 관측한다(스냅샷)."""
    return {
        b.root_document_id
        for b in helpers.identify_bundles(engine_access, workspace_id)
    }


# =============================================================================
# 1) 만료 경계 + 타 워크스페이스 불변 (Req 4.1·4.4, INV-12·10)
# =============================================================================


def test_sweep_purges_expired_across_workspaces_and_keeps_unexpired(
    ws_scenario, engine_access, harness
):
    """주입된 `now` 기준으로 만료 묶음만 deleted 로 전환하고 미만료·타 워크스페이스 묶음은
    각자 보관일로 독립 판정한다(Req 4.1·4.4, INV-12·10).

    WS-A(retention=30):
    - A1(루트+자식, trashed_at=now-40일) → 만료 → 구성원 전체 deleted.
    - 경계(trashed_at=now-30일, 정확히 `trashed_at+retention == now`) → `<=` 경계라 만료 → deleted.
    - A2(trashed_at=now-10일) → 미만료 → trashed 유지.
    WS-B(retention=7):
    - B1(trashed_at=now-40일) → B 의 보관일로 만료 → deleted.

    동일한 삭제 경과(40일)라도 만료 판정은 각 워크스페이스 retention 으로 갈리며(A2 는 유지),
    스윕 반환 카운트는 실제 완전삭제된 묶음 수(A1·경계·B1 = 3)와 일치한다. 만료 묶음은 엔진
    `identify_bundles` 의 trashed 집합에서 이탈하고 미만료는 남는다(엔진 주도 식별·전이 증거).
    """
    owner = ws_scenario.owner_client
    ws_a = ws_scenario.workspace_id
    _set_retention(harness, ws_a, 30)

    # A1: 루트+자식(2 구성원) → 루트 삭제로 하나의 만료 묶음.
    a1_root = helpers.create_document(owner, ws_a, _uniq("A1루트"))
    a1_child = helpers.create_document(
        owner, ws_a, _uniq("A1자식"), parent_id=a1_root["id"]
    )
    helpers.delete_document(owner, a1_root["id"])

    # 경계: 정확히 now 시점 만료(단일 구성원).
    a_boundary = helpers.create_document(owner, ws_a, _uniq("경계"))
    helpers.delete_document(owner, a_boundary["id"])

    # A2: 아직 보관 기간이 남은 묶음(단일 구성원).
    a2 = helpers.create_document(owner, ws_a, _uniq("A2"))
    helpers.delete_document(owner, a2["id"])

    # WS-B: 더 짧은 보관일로 동일 경과에도 만료.
    ws_b = _new_workspace(owner)
    _set_retention(harness, ws_b, 7)
    b1 = helpers.create_document(owner, ws_b, _uniq("B1"))
    helpers.delete_document(owner, b1["id"])

    # 결정적 만료 경계로 핀 고정(묶음별 구성원 전체 동일 값 → 묶음 경계 유지).
    _pin_trashed_at(harness, [a1_root["id"], a1_child["id"]], _NOW - timedelta(days=40))
    _pin_trashed_at(harness, [a_boundary["id"]], _NOW - timedelta(days=30))
    _pin_trashed_at(harness, [a2["id"]], _NOW - timedelta(days=10))
    _pin_trashed_at(harness, [b1["id"]], _NOW - timedelta(days=40))

    # 스윕 전: 엔진이 이들을 trashed 묶음으로 열거한다(엔진 주도 식별).
    roots_a_before = _bundle_roots(engine_access, ws_a)
    assert {a1_root["id"], a_boundary["id"], a2["id"]} <= roots_a_before, (
        "스윕 전 WS-A 의 세 묶음이 trashed 로 열거되어야 한다"
    )
    assert b1["id"] in _bundle_roots(engine_access, ws_b), (
        "스윕 전 WS-B 의 B1 묶음이 trashed 로 열거되어야 한다"
    )

    purged = _run_sweep(harness, _NOW)

    # (반환 정합) 실제 완전삭제된 묶음 수 = A1·경계·B1 = 3(주입 now 기준 유일 만료 묶음).
    assert purged == 3, (
        f"만료·경계·타WS 묶음 3개만 완전삭제되어야 한다(반환값 정합): {purged}"
    )

    # (만료 → deleted, 구성원 전체 전이)
    assert _status_of(harness, a1_root["id"]) == "deleted"
    assert _status_of(harness, a1_child["id"]) == "deleted", (
        "만료 묶음은 구성원 전체가 deleted 로 전이되어야 한다"
    )
    assert _status_of(harness, a_boundary["id"]) == "deleted", (
        "정확히 경계(trashed_at+retention == now)인 묶음은 `<=` 로 만료 처리되어야 한다(Req 4.4)"
    )
    assert _status_of(harness, b1["id"]) == "deleted", (
        "retention=7 인 WS-B 의 40일 경과 묶음은 만료되어야 한다(Req 4.1)"
    )

    # (미만료 유지 — 타 워크스페이스·만료가 A2 기준을 끌고 가지 않음, INV-12)
    assert _status_of(harness, a2["id"]) == "trashed", (
        "보관 기간이 남은 A2 묶음은 유지되어야 한다(Req 4.4, INV-12)"
    )

    # 스윕 후: 만료 묶음은 trashed 집합에서 이탈, 미만료는 남는다(엔진 주도 전이 증거, Req 6.1).
    roots_a_after = _bundle_roots(engine_access, ws_a)
    assert a1_root["id"] not in roots_a_after
    assert a_boundary["id"] not in roots_a_after
    assert a2["id"] in roots_a_after, "미만료 묶음은 trashed 로 남아야 한다"
    assert b1["id"] not in _bundle_roots(engine_access, ws_b)


# =============================================================================
# 2) 묶음 독립 타이머 — 자식/부모 서로 다른 trashed_at (Req 4.2·4.5, INV-12)
# =============================================================================


def test_sweep_independent_per_bundle_timer_child_expires_first(
    doc_tree_scenario, engine_access, harness
):
    """서로 다른 trashed_at 을 가진 자식/부모 묶음이 각자 trashed_at 기준으로 독립 산정되어,
    한 묶음(자식) 처리가 다른 묶음(부모) 만료 기준에 영향을 주지 않는다(Req 4.2·4.5, INV-12).

    깊은 노드(손자)를 먼저 삭제해 손자 단독 묶음(오래됨, 만료)을 만들고, 이후 조상(루트)을
    삭제해 루트+자식 묶음(최근, 미만료)을 만든다 — 이미 trashed 된 손자는 흡수되지 않아
    (비흡수) 두 개의 독립 묶음이 된다. 스윕은 만료된 자식(손자) 묶음만 완전삭제하고 미만료
    부모 묶음은 trashed 로 유지해야 한다(자식이 먼저 만료됨을 허용, Req 4.5).
    """
    editor = doc_tree_scenario.editor_client
    ws_id = doc_tree_scenario.workspace_id
    root_id = doc_tree_scenario.root_id
    child_id = doc_tree_scenario.child_id
    grandchild_id = doc_tree_scenario.grandchild_id
    _set_retention(harness, ws_id, 30)

    # 손자 단독 삭제(자식 묶음) → 이후 루트 삭제(부모 묶음). 삭제 캐스케이드는 이미 trashed 된
    # 손자를 루트 작업에서 제외하므로(비흡수) 루트 작업 구성원은 루트+자식뿐이다. 다만 두 삭제가
    # 같은 벽시계 초 안에 일어나면 DATETIME(0) 초 절삭으로 trashed_at 이 충돌해 하나의 묶음으로
    # 재구성될 수 있다 — 이는 순수 테스트 타이밍 산물이므로, 의도한 "자식은 오래 전·부모는 최근"
    # 현실을 결정적으로 만들기 위해 서로 다른 과거 초단위 값으로 핀 고정한다(그 뒤 묶음 분리 확인).
    helpers.delete_document(editor, grandchild_id)
    helpers.delete_document(editor, root_id)

    # 자식(손자) 묶음만 만료되도록 핀 고정: 손자 오래됨(만료), 루트+자식 최근(미만료).
    _pin_trashed_at(harness, [grandchild_id], _NOW - timedelta(days=40))
    _pin_trashed_at(harness, [root_id, child_id], _NOW - timedelta(days=5))

    # 스윕 전 서로 다른 trashed_at 으로 두 개의 **독립** 묶음임을 엔진 식별로 확인(비흡수, INV-12).
    bundles = {
        b.root_document_id: b
        for b in helpers.identify_bundles(engine_access, ws_id)
    }
    assert grandchild_id in bundles and root_id in bundles, (
        "손자 묶음과 루트 묶음이 서로 다른 두 묶음으로 식별되어야 한다(비흡수, INV-12)"
    )
    assert bundles[grandchild_id].member_ids == {grandchild_id}, (
        "손자 묶음의 구성원은 손자 단독이어야 한다"
    )
    assert bundles[root_id].member_ids == {root_id, child_id}, (
        "루트 묶음의 구성원은 루트+자식이어야 한다(이미 trashed 된 손자 비흡수)"
    )

    purged = _run_sweep(harness, _NOW)

    assert purged == 1, "만료된 자식(손자) 묶음 1개만 완전삭제되어야 한다"
    assert _status_of(harness, grandchild_id) == "deleted", (
        "오래된 자식 묶음은 자기 trashed_at 기준으로 만료되어야 한다(Req 4.2·4.5)"
    )
    assert _status_of(harness, root_id) == "trashed", (
        "미만료 부모 묶음은 자식 만료에 끌려가지 않고 유지되어야 한다(INV-12)"
    )
    assert _status_of(harness, child_id) == "trashed", (
        "부모 묶음 구성원(자식)도 자식 묶음 만료에 영향받지 않아야 한다"
    )

    # 스윕 후: 자식 묶음은 trashed 집합에서 이탈, 부모 묶음은 남는다(독립 타이머 증거).
    roots_after = _bundle_roots(engine_access, ws_id)
    assert grandchild_id not in roots_after
    assert root_id in roots_after


# =============================================================================
# 3) 멱등 + 이미 deleted/복구 건너뜀 (Req 4.6·4.7)
# =============================================================================


def test_sweep_is_idempotent_and_skips_deleted_and_restored(
    ws_scenario, harness
):
    """반복 실행이 멱등하고, 이미 deleted 되었거나 복구된 묶음을 만나도 오류 없이 건너뛴다
    (Req 4.6·4.7).

    만료 묶음 X 와 미만료 묶음 Y 를 만든 뒤:
    1. 첫 스윕은 X 만 완전삭제(1)하고 Y 는 유지한다.
    2. **같은 now** 로 재실행하면 이미 deleted 인 X 는 `identify_bundles`(trashed 만 열거)에
       없어 건너뛰어지고, 재전이 없이 0 을 반환한다(멱등, Req 4.7).
    3. 미만료 묶음 Y 를 복구(active)한 뒤 스윕하면 오류 없이 0 을 반환하고 복구된 Y 는
       영향받지 않는다(복구된 묶음 건너뜀, Req 4.6).
    """
    owner = ws_scenario.owner_client
    ws_id = ws_scenario.workspace_id
    _set_retention(harness, ws_id, 30)

    x = helpers.create_document(owner, ws_id, _uniq("만료X"))
    helpers.delete_document(owner, x["id"])
    y = helpers.create_document(owner, ws_id, _uniq("미만료Y"))
    helpers.delete_document(owner, y["id"])

    _pin_trashed_at(harness, [x["id"]], _NOW - timedelta(days=40))
    _pin_trashed_at(harness, [y["id"]], _NOW - timedelta(days=10))

    # (1) 첫 스윕: 만료 X 만 완전삭제.
    first = _run_sweep(harness, _NOW)
    assert first == 1, "첫 실행은 만료 묶음 X 1개를 완전삭제한다"
    assert _status_of(harness, x["id"]) == "deleted"
    assert _status_of(harness, y["id"]) == "trashed"

    # (2) 같은 now 재실행: 이미 deleted 인 X 는 건너뛰어지고 재전이 없이 no-op(0).
    second = _run_sweep(harness, _NOW)
    assert second == 0, "이미 deleted 인 묶음은 열거되지 않아 재실행은 no-op(0, 멱등)이어야 한다"
    assert _status_of(harness, x["id"]) == "deleted", (
        "이미 완전삭제된 묶음은 반복 실행에도 중복 전이되지 않고 deleted 종착으로 유지"
    )
    assert _status_of(harness, y["id"]) == "trashed"

    # (3) 미만료 Y 를 복구(active)한 뒤 스윕: 오류 없이 0, 복구된 Y 는 영향 없음.
    restore_resp = owner.post(f"/trash/{y['id']}/restore")
    assert restore_resp.status_code == 204, (
        f"미만료 묶음 복구는 204 여야 한다: {restore_resp.status_code} {restore_resp.text}"
    )
    assert _status_of(harness, y["id"]) == "active", "복구 후 Y 는 active 로 돌아와야 한다"

    third = _run_sweep(harness, _NOW)
    assert third == 0, "복구되어 trashed 가 아닌 묶음은 스윕이 건너뛰어 no-op(0)이어야 한다(Req 4.6)"
    assert _status_of(harness, y["id"]) == "active", (
        "복구된(active) 묶음은 스윕에 영향받지 않아야 한다"
    )
