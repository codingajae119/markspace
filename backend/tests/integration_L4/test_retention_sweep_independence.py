"""묶음 보관 타이머 독립성 통합 스위트 — s10 `RetentionSweepService` e2e (INV-12)
(Task 2.5 / Req 6.1·6.2·6.3·6.4·6.5·6.6, design §RetentionSweepIndependenceSuite,
§System Flows 묶음 보관 타이머 자동 영구삭제).

마이그레이션된 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10) 위에서, s07 `DELETE /documents/{id}`
로 문서를 trashed 로 만든 뒤 **실제** `RetentionSweepService`(실제 s07 엔진 + s10
`TrashRepository`)를 부팅 앱과 동일 세션 팩토리(`harness.session_local`) 위에서 구동해 보관
만료 스윕의 실동작을 mock 없이 관찰한다. 만료 경계를 결정적으로 검증하기 위해 스윕에는 고정
`now` 를 **주입**하고(스케줄러 job 대기·실시간 sleep 금지), 각 묶음의 `trashed_at` 은 직접 DB
행 갱신으로 초 단위(마이크로초 0, DATETIME(0) 반올림 함정 회피) 과거값에 **핀 고정**한다(테스트
시드 조작 — 스윕 서비스는 trashed_at 을 직접 쓰지 않는다). 워크스페이스별 `trash_retention_days`
도 직접 DB 갱신으로 명시 설정해 워크스페이스 스코프 만료 판정(Req 6.5)을 결정적으로 만든다.

이 스위트는 test-authoring task 로, feature 는 이미 조립·구현되어 있다("역-RED": 새 테스트가
실제 구현 위에서 **통과**하는 것이 검증). product 코드·기존 테스트·conftest·helpers·하네스는
건드리지 않고 재사용만 한다(L4 `sweep_access`·`trash_scenario`·`ws_scenario`·`engine_access`·
`harness` 픽스처, L4 `helpers.run_sweep`, 재-export 된 L3 문서·엔진 헬퍼).

결정성 근거(함수 스코프 하네스): L4 `harness` 는 매 테스트마다 전 테이블 drop → `alembic
upgrade head` → admin 재시드 → 앱 재부팅한다. 따라서 한 테스트 안에서는 그 테스트가 만든
trashed 묶음만 존재하므로 전역 스윕 반환 카운트(예: `purged == 2`)가 **정확히** 결정적이다.
L3 보관 스윕 템플릿의 정확-카운트 스타일을 L4 픽스처 위에서 그대로 따른다.
"""

from datetime import datetime, timedelta
from uuid import uuid4

from app.models import Document, Workspace
from tests.integration_L4 import helpers

# 모든 만료 경계를 이 고정 시각에 대해 산정한다(초 단위, 마이크로초 0 — DATETIME(0) 정합).
# L4 `trash_scenario.reference`(_TRASH_REFERENCE)와 동일 값으로, `now` 로 주입한다.
_NOW = datetime(2026, 7, 17, 0, 0, 0)


def _uniq(prefix: str) -> str:
    """공유 ``markspace_test`` DB 에서 충돌하지 않는 고유 이름/제목을 만든다."""
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

    부팅 앱과 동일 세션 팩토리로 s05 설정값을 결정적으로 고정해 워크스페이스 스코프 만료
    판정(Req 6.5)을 알려진 값으로 만든다(테스트 시드 조작). L4 `trash_scenario` 가 자기
    워크스페이스에 노출하는 `set_retention` 과 같은 직접-DB 관용을, 임의로 만든 워크스페이스에도
    적용하기 위한 로컬 헬퍼다(L3 스윕 템플릿 답습).
    """
    with harness.session_local() as db:
        ws = db.get(Workspace, workspace_id)
        assert ws is not None, f"대상 워크스페이스가 있어야 한다: id={workspace_id}"
        ws.trash_retention_days = days
        db.commit()


def _pin_trashed_at(harness, document_ids, ts: datetime) -> None:
    """묶음 구성원 전체의 `trashed_at` 을 결정적 초단위 과거값으로 핀 고정한다(테스트 시드).

    엔진 `DELETE` 캐스케이드는 `utcnow()` 로 공통 trashed_at 을 부여하므로 만료 경계를
    결정적으로 검증하려면 그 값을 고정값으로 덮어쓴다. 묶음은 동일 trashed_at 연결로
    재구성되므로 한 묶음의 구성원 전체에 **같은** 값을 부여해 묶음 경계를 유지한다. DATETIME(0)
    반올림을 피하려 마이크로초 0 값을 쓴다. 스윕 서비스는 trashed_at 을 쓰지 않는다.
    """
    ts = ts.replace(microsecond=0)
    with harness.session_local() as db:
        for document_id in document_ids:
            doc = db.get(Document, document_id)
            assert doc is not None, f"핀 대상 문서가 있어야 한다: id={document_id}"
            doc.trashed_at = ts
        db.commit()


def _trashed_at_of(harness, document_id: int) -> datetime | None:
    """부팅 앱과 동일 세션으로 문서 행의 `trashed_at` 을 신규 세션으로 직접 관측한다(없으면 None).

    스윕(완전삭제)이 `trashed_at` 을 물리 삭제·초기화하지 않고 보존함(INV-4)을 관찰하는 데 쓴다.
    """
    with harness.session_local() as db:
        doc = db.get(Document, document_id)
        return None if doc is None else doc.trashed_at


def _bundle_roots(engine_access, workspace_id: int) -> set[int]:
    """엔진 `identify_bundles` 로 워크스페이스의 trashed 묶음 루트 id 집합을 관측한다(스냅샷).

    스윕이 묶음 경계를 재구성하지 않고 엔진 `identify_bundles` 에 의존함을, 그리고 만료 묶음이
    스윕 후 trashed 집합에서 이탈함을 관찰하는 데 쓴다(엔진 위임 증거, Req 6.6).
    """
    return {
        b.root_document_id
        for b in helpers.l3_helpers.identify_bundles(engine_access, workspace_id)
    }


# =============================================================================
# 1) 만료 경계 — 만료분만 deleted·미만료 불변 (Req 6.1)
# =============================================================================


def test_sweep_purges_only_expired_including_boundary(
    ws_scenario, engine_access, sweep_access, harness
):
    """주입된 `now` 기준으로 만료 묶음만 구성원 `deleted` 로 전환하고 미만료 묶음은 status·
    trashed_at 을 그대로 유지한다. 정확히 경계(`trashed_at + retention == now`)인 묶음은 `<=`
    경계라 만료로 처리된다(Req 6.1).

    WS(retention=30):
    - EXP(루트+자식, trashed_at=now-40일) → 만료 → 구성원 전체 deleted.
    - BND(trashed_at=now-30일, 정확히 `trashed_at+retention == now`) → `<=` 경계라 만료 → deleted.
    - UNEXP(trashed_at=now-10일) → 미만료 → trashed·trashed_at 유지.

    스윕 반환 카운트는 실제 완전삭제된 묶음 수(EXP·BND = 2)와 정확히 일치한다(함수 스코프
    하네스라 이 테스트의 만료 묶음만 존재).
    """
    owner = ws_scenario.owner_client
    ws_id = ws_scenario.workspace_id
    _set_retention(harness, ws_id, 30)

    # EXP: 루트+자식(2 구성원) → 루트 삭제로 하나의 만료 묶음.
    exp_root = helpers.l3_helpers.create_document(owner, ws_id, _uniq("EXP루트"))
    exp_child = helpers.l3_helpers.create_document(
        owner, ws_id, _uniq("EXP자식"), parent_id=exp_root["id"]
    )
    helpers.l3_helpers.delete_document(owner, exp_root["id"])

    # BND: 정확히 now 시점 만료(단일 구성원).
    bnd = helpers.l3_helpers.create_document(owner, ws_id, _uniq("경계"))
    helpers.l3_helpers.delete_document(owner, bnd["id"])

    # UNEXP: 아직 보관 기간이 남은 묶음(단일 구성원).
    unexp = helpers.l3_helpers.create_document(owner, ws_id, _uniq("미만료"))
    helpers.l3_helpers.delete_document(owner, unexp["id"])

    # 결정적 만료 경계로 핀 고정(묶음별 구성원 전체 동일 값 → 묶음 경계 유지).
    _pin_trashed_at(harness, [exp_root["id"], exp_child["id"]], _NOW - timedelta(days=40))
    _pin_trashed_at(harness, [bnd["id"]], _NOW - timedelta(days=30))
    _pin_trashed_at(harness, [unexp["id"]], _NOW - timedelta(days=10))
    unexp_trashed_at_before = _trashed_at_of(harness, unexp["id"])

    # 스윕 전: 엔진이 세 묶음을 trashed 로 열거한다(엔진 주도 식별).
    assert {exp_root["id"], bnd["id"], unexp["id"]} <= _bundle_roots(engine_access, ws_id), (
        "스윕 전 세 묶음이 모두 trashed 로 열거되어야 한다"
    )

    purged = helpers.run_sweep(sweep_access, _NOW)

    # (반환 정합) 실제 완전삭제된 묶음 수 = EXP·BND = 2(주입 now 기준 유일 만료 묶음).
    assert purged == 2, (
        f"만료·경계 묶음 2개만 완전삭제되어야 한다(반환값 정합): {purged}"
    )

    # (만료 → deleted, 구성원 전체 전이)
    assert sweep_access.status_of(exp_root["id"]) == "deleted"
    assert sweep_access.status_of(exp_child["id"]) == "deleted", (
        "만료 묶음은 구성원 전체가 deleted 로 전이되어야 한다"
    )
    assert sweep_access.status_of(bnd["id"]) == "deleted", (
        "정확히 경계(trashed_at+retention == now)인 묶음은 `<=` 로 만료 처리되어야 한다(Req 6.1)"
    )

    # (미만료 유지 — status·trashed_at 불변)
    assert sweep_access.status_of(unexp["id"]) == "trashed", (
        "보관 기간이 남은 묶음은 유지되어야 한다(Req 6.1)"
    )
    assert _trashed_at_of(harness, unexp["id"]) == unexp_trashed_at_before, (
        "미만료 묶음의 trashed_at 은 스윕에 의해 변경되지 않아야 한다(Req 6.1)"
    )


# =============================================================================
# 2) 묶음별 독립 타이머 — 만료 처리 타 묶음 무영향 (Req 6.2, INV-12)
# =============================================================================


def test_expired_purge_does_not_affect_unexpired_bundle(
    ws_scenario, engine_access, sweep_access, harness
):
    """만료 묶음의 영구삭제가 다른(미만료) 묶음의 구성원·`trashed_at`·보관 기준에 아무 영향을
    주지 않는다(묶음별 독립 타이머, Req 6.2·INV-12).

    한 워크스페이스에 만료 묶음 X(루트+자식, now-40일)와 미만료 묶음 Y(now-10일)를 두고,
    스윕 후 Y 구성원의 status·trashed_at 이 스윕 전과 정확히 동일하며 워크스페이스 보관일도
    변하지 않음을 관찰한다. 공유/집계 컷오프가 없어 X 처리가 Y 기준을 끌고 가지 않는다.
    """
    owner = ws_scenario.owner_client
    ws_id = ws_scenario.workspace_id
    _set_retention(harness, ws_id, 30)

    x_root = helpers.l3_helpers.create_document(owner, ws_id, _uniq("X루트"))
    x_child = helpers.l3_helpers.create_document(
        owner, ws_id, _uniq("X자식"), parent_id=x_root["id"]
    )
    helpers.l3_helpers.delete_document(owner, x_root["id"])

    y = helpers.l3_helpers.create_document(owner, ws_id, _uniq("Y"))
    helpers.l3_helpers.delete_document(owner, y["id"])

    _pin_trashed_at(harness, [x_root["id"], x_child["id"]], _NOW - timedelta(days=40))
    _pin_trashed_at(harness, [y["id"]], _NOW - timedelta(days=10))

    # 스윕 전 미만료 Y 의 관측 기준을 포착(status·trashed_at·워크스페이스 retention).
    y_status_before = sweep_access.status_of(y["id"])
    y_trashed_at_before = _trashed_at_of(harness, y["id"])

    purged = helpers.run_sweep(sweep_access, _NOW)

    assert purged == 1, f"만료 묶음 X 1개만 완전삭제되어야 한다: {purged}"
    assert sweep_access.status_of(x_root["id"]) == "deleted"
    assert sweep_access.status_of(x_child["id"]) == "deleted"

    # (독립 타이머) 미만료 Y 는 status·trashed_at 이 스윕 전과 정확히 동일해야 한다.
    assert sweep_access.status_of(y["id"]) == y_status_before == "trashed", (
        "만료 묶음 처리가 미만료 묶음 구성원 status 에 영향을 주면 안 된다(INV-12)"
    )
    assert _trashed_at_of(harness, y["id"]) == y_trashed_at_before, (
        "만료 묶음 처리가 미만료 묶음 trashed_at 에 영향을 주면 안 된다(INV-12)"
    )
    # (보관 기준 불변) 워크스페이스 retention 이 변하지 않았음을 재관찰로 확인.
    with harness.session_local() as db:
        assert db.get(Workspace, ws_id).trash_retention_days == 30, (
            "만료 묶음 처리가 워크스페이스 보관 기준을 바꾸면 안 된다(INV-12)"
        )
    # 미만료 Y 는 여전히 trashed 묶음으로 열거된다.
    assert y["id"] in _bundle_roots(engine_access, ws_id)


# =============================================================================
# 3) 자식 선만료 수용 — 자식 묶음이 부모보다 먼저 독립 만료 (Req 6.3, 6.4.1, INV-12)
# =============================================================================


def test_child_bundle_expires_before_parent_bundle(
    trash_scenario, engine_access, sweep_access
):
    """서로 다른 trashed_at 을 가진 자식(손자) 묶음과 부모(루트+자식) 묶음이 각자 trashed_at
    기준으로 독립 산정되어, 자식 묶음이 부모 묶음보다 먼저 만료되어 독립 영구삭제되는 케이스가
    허용된다(Req 6.3·6.4.1, INV-12).

    `trash_scenario` 는 손자를 먼저 단독 삭제(손자 묶음, now-40일=만료)한 뒤 루트를 삭제
    (루트+자식 묶음, now-5일=미만료)해 비흡수로 두 독립 묶음을 구성한다(retention=30). 주입된
    `now`(=`trash_scenario.reference`)로 스윕하면 오래된 자식(손자) 묶음만 완전삭제되고 최근
    부모 묶음은 자식 만료에 끌려가지 않고 trashed 로 유지된다.
    """
    ws_id = trash_scenario.workspace_id
    root_id = trash_scenario.root_id
    child_id = trash_scenario.child_id
    grandchild_id = trash_scenario.grandchild_id
    now = trash_scenario.reference

    # 스윕 전: 서로 다른 trashed_at 으로 두 개의 **독립** 묶음임을 엔진 식별로 확인(비흡수, INV-12).
    bundles = {
        b.root_document_id: b
        for b in helpers.l3_helpers.identify_bundles(engine_access, ws_id)
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

    purged = helpers.run_sweep(sweep_access, now)

    assert purged == 1, "만료된 자식(손자) 묶음 1개만 완전삭제되어야 한다"
    assert sweep_access.status_of(grandchild_id) == "deleted", (
        "오래된 자식 묶음은 자기 trashed_at 기준으로 먼저 만료되어야 한다(Req 6.3·6.4.1)"
    )
    assert sweep_access.status_of(root_id) == "trashed", (
        "미만료 부모 묶음은 자식 만료에 끌려가지 않고 유지되어야 한다(INV-12)"
    )
    assert sweep_access.status_of(child_id) == "trashed", (
        "부모 묶음 구성원(자식)도 자식 묶음 만료에 영향받지 않아야 한다"
    )

    # 스윕 후: 자식 묶음은 trashed 집합에서 이탈, 부모 묶음은 남는다(독립 타이머 증거).
    roots_after = _bundle_roots(engine_access, ws_id)
    assert grandchild_id not in roots_after
    assert root_id in roots_after


# =============================================================================
# 4) 멱등 — 이미 deleted/복구된 묶음 포함 반복 실행 (Req 6.4)
# =============================================================================


def test_sweep_is_idempotent_and_skips_deleted_and_restored(
    ws_scenario, sweep_access, harness
):
    """이미 deleted 되었거나 복구된 묶음을 포함해 스윕을 반복 실행해도 이미 처리된 묶음은
    오류 없이 건너뛰어지고, 중복 전이나 예외 전파가 없다(멱등, Req 6.4).

    만료 묶음 X 와 미만료 묶음 Y 를 만든 뒤:
    1. 첫 스윕은 X 만 완전삭제(1)하고 Y 는 유지한다.
    2. **같은 now** 로 재실행하면 이미 deleted 인 X 는 `identify_bundles`(trashed 만 열거)에
       없어 건너뛰어지고, 재전이 없이 0 을 반환한다(멱등).
    3. 미만료 묶음 Y 를 복구(active)한 뒤 스윕하면 오류 없이 0 을 반환하고 복구된 Y 는
       영향받지 않는다(복구된 묶음 건너뜀).
    """
    owner = ws_scenario.owner_client
    ws_id = ws_scenario.workspace_id
    _set_retention(harness, ws_id, 30)

    x = helpers.l3_helpers.create_document(owner, ws_id, _uniq("만료X"))
    helpers.l3_helpers.delete_document(owner, x["id"])
    y = helpers.l3_helpers.create_document(owner, ws_id, _uniq("미만료Y"))
    helpers.l3_helpers.delete_document(owner, y["id"])

    _pin_trashed_at(harness, [x["id"]], _NOW - timedelta(days=40))
    _pin_trashed_at(harness, [y["id"]], _NOW - timedelta(days=10))

    # (1) 첫 스윕: 만료 X 만 완전삭제.
    first = helpers.run_sweep(sweep_access, _NOW)
    assert first == 1, "첫 실행은 만료 묶음 X 1개를 완전삭제한다"
    assert sweep_access.status_of(x["id"]) == "deleted"
    assert sweep_access.status_of(y["id"]) == "trashed"

    # (2) 같은 now 재실행: 이미 deleted 인 X 는 건너뛰어지고 재전이 없이 no-op(0).
    second = helpers.run_sweep(sweep_access, _NOW)
    assert second == 0, "이미 deleted 인 묶음은 열거되지 않아 재실행은 no-op(0, 멱등)이어야 한다"
    assert sweep_access.status_of(x["id"]) == "deleted", (
        "이미 완전삭제된 묶음은 반복 실행에도 중복 전이되지 않고 deleted 종착으로 유지"
    )
    assert sweep_access.status_of(y["id"]) == "trashed"

    # (3) 미만료 Y 를 복구(active)한 뒤 스윕: 오류 없이 0, 복구된 Y 는 영향 없음.
    helpers.restore_bundle_via_api(owner, y["id"])
    assert sweep_access.status_of(y["id"]) == "active", "복구 후 Y 는 active 로 돌아와야 한다"

    third = helpers.run_sweep(sweep_access, _NOW)
    assert third == 0, "복구되어 trashed 가 아닌 묶음은 스윕이 건너뛰어 no-op(0)이어야 한다(Req 6.4)"
    assert sweep_access.status_of(y["id"]) == "active", (
        "복구된(active) 묶음은 스윕에 영향받지 않아야 한다"
    )


# =============================================================================
# 5) 워크스페이스 스코프 독립 — 각 retention 이 자기 WS 에만 적용 (Req 6.5)
# =============================================================================


def test_retention_is_scoped_per_workspace(
    ws_scenario, engine_access, sweep_access, harness
):
    """여러 워크스페이스에서 각 `trash_retention_days` 가 자기 워크스페이스 묶음 만료에만
    적용되고 다른 워크스페이스의 미만료 묶음은 불변임을 확인한다(워크스페이스 스코프 독립, Req 6.5).

    WS-A(retention=30)와 WS-B(retention=7)에 **동일 경과(now-10일)** 묶음을 하나씩 둔다:
    - A 묶음: 10일 < 30일 → 미만료 → trashed 유지.
    - B 묶음: 10일 >= 7일 → 만료 → deleted.

    같은 삭제 경과라도 만료 판정이 각 워크스페이스 retention 으로 갈리며(A 는 유지, B 는 만료),
    스윕 반환 카운트는 실제 완전삭제된 묶음 수(B = 1)와 정확히 일치한다.
    """
    owner = ws_scenario.owner_client
    ws_a = ws_scenario.workspace_id
    _set_retention(harness, ws_a, 30)

    ws_b = _new_workspace(owner)  # 요청자(owner)가 자동 owner 인 별도 워크스페이스.
    _set_retention(harness, ws_b, 7)

    a = helpers.l3_helpers.create_document(owner, ws_a, _uniq("A"))
    helpers.l3_helpers.delete_document(owner, a["id"])
    b = helpers.l3_helpers.create_document(owner, ws_b, _uniq("B"))
    helpers.l3_helpers.delete_document(owner, b["id"])

    # 동일 경과(10일)로 핀 고정 — 만료 판정 차이는 오직 워크스페이스 retention 에서 온다.
    _pin_trashed_at(harness, [a["id"]], _NOW - timedelta(days=10))
    _pin_trashed_at(harness, [b["id"]], _NOW - timedelta(days=10))
    a_trashed_at_before = _trashed_at_of(harness, a["id"])

    purged = helpers.run_sweep(sweep_access, _NOW)

    # (반환 정합) B(retention=7)만 만료 → 완전삭제 1건.
    assert purged == 1, f"짧은 보관일 WS-B 의 묶음 1개만 완전삭제되어야 한다: {purged}"
    assert sweep_access.status_of(b["id"]) == "deleted", (
        "retention=7 인 WS-B 의 10일 경과 묶음은 자기 워크스페이스 보관일로 만료되어야 한다(Req 6.5)"
    )

    # (스코프 독립) 같은 경과라도 WS-A(retention=30) 묶음은 자기 보관일로 미만료 → 불변.
    assert sweep_access.status_of(a["id"]) == "trashed", (
        "WS-B 의 짧은 보관일이 WS-A 묶음 만료에 적용되면 안 된다(워크스페이스 스코프 독립, Req 6.5)"
    )
    assert _trashed_at_of(harness, a["id"]) == a_trashed_at_before, (
        "타 워크스페이스 만료 처리가 WS-A 미만료 묶음 trashed_at 을 바꾸면 안 된다"
    )
    assert a["id"] in _bundle_roots(engine_access, ws_a), (
        "미만료 WS-A 묶음은 trashed 로 남아야 한다"
    )
    assert b["id"] not in _bundle_roots(engine_access, ws_b), (
        "만료된 WS-B 묶음은 trashed 집합에서 이탈해야 한다"
    )


# =============================================================================
# 6) 실제 purge DB 관찰 — status=deleted·물리 삭제 부재·엔진 위임 (Req 6.6)
# =============================================================================


def test_sweep_deletes_via_engine_without_physical_delete(
    ws_scenario, engine_access, sweep_access, harness
):
    """스윕이 만료 묶음을 실제로 `deleted` 로 전환한 결과를 DB 관찰(구성원 `status=deleted`·물리
    삭제 부재)로 확인하고, 스윕이 묶음 경계를 재구성하지 않고 엔진 `identify_bundles`·
    `purge_bundle` 에만 의존함을 확인한다(Req 6.6, INV-12·엔진 위임).

    만료 묶음(루트+자식, now-40일)을 두고:
    - 스윕 전: 엔진 `identify_bundles` 가 이 묶음을 루트로 열거한다(스윕은 경계를 재구성하지
      않고 엔진 식별에 의존).
    - 스윕 후: 구성원 전체가 `status=deleted` 로 전환되되 문서 행은 그대로 존재하고(물리 삭제
      부재, INV-4) `trashed_at` 이 보존되며, 그 루트는 엔진 trashed 집합에서 이탈한다(엔진
      `purge_bundle` 위임 결과).
    """
    owner = ws_scenario.owner_client
    ws_id = ws_scenario.workspace_id
    _set_retention(harness, ws_id, 30)

    root = helpers.l3_helpers.create_document(owner, ws_id, _uniq("루트"))
    child = helpers.l3_helpers.create_document(
        owner, ws_id, _uniq("자식"), parent_id=root["id"]
    )
    helpers.l3_helpers.delete_document(owner, root["id"])
    _pin_trashed_at(harness, [root["id"], child["id"]], _NOW - timedelta(days=40))
    root_trashed_at_before = _trashed_at_of(harness, root["id"])
    child_trashed_at_before = _trashed_at_of(harness, child["id"])

    # 스윕 전: 엔진 identify_bundles 가 이 묶음을 루트로 열거(스윕은 경계 재구성 없이 엔진 의존).
    bundles_before = {
        b.root_document_id: b
        for b in helpers.l3_helpers.identify_bundles(engine_access, ws_id)
    }
    assert root["id"] in bundles_before, (
        "스윕 전 만료 묶음이 엔진 identify_bundles 로 열거되어야 한다(엔진 위임 근거)"
    )
    assert bundles_before[root["id"]].member_ids == {root["id"], child["id"]}, (
        "묶음 경계(루트+자식)는 엔진이 정하며 스윕이 재구성하지 않는다"
    )

    purged = helpers.run_sweep(sweep_access, _NOW)

    assert purged == 1, f"만료 묶음 1개가 완전삭제되어야 한다: {purged}"

    # (실제 deleted 전환, 구성원 전체) — 엔진 purge_bundle 위임 결과.
    assert sweep_access.status_of(root["id"]) == "deleted"
    assert sweep_access.status_of(child["id"]) == "deleted", (
        "만료 묶음은 구성원 전체가 원자적으로 deleted 로 전환되어야 한다(엔진 purge_bundle 위임)"
    )

    # (물리 삭제 부재, INV-4) — 문서 행이 그대로 존재하고 trashed_at 이 보존된다.
    assert _trashed_at_of(harness, root["id"]) == root_trashed_at_before, (
        "완전삭제는 status 전환일 뿐 물리 삭제·trashed_at 초기화가 아니어야 한다(INV-4)"
    )
    assert _trashed_at_of(harness, child["id"]) == child_trashed_at_before, (
        "구성원 행이 물리 삭제되지 않고 trashed_at 이 보존되어야 한다(INV-4)"
    )

    # (엔진 위임) 완전삭제된 묶음 루트는 엔진 trashed 집합에서 이탈한다(스윕이 엔진에만 의존).
    assert root["id"] not in _bundle_roots(engine_access, ws_id), (
        "deleted 로 전환된 묶음 루트는 엔진 trashed 집합에서 이탈해야 한다(엔진 위임 결과)"
    )
