"""s14 무효화·재발급(INV-8) seam 통합 테스트 (Task 4.2 / design §Testing Strategy
「무효화·재발급(INV-8) seam」, Req 4.4, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6).

마이그레이션된 실제 MySQL 테스트 DB + s14 공유 라우터·무효화 스케줄러가 조립된 부팅 앱
(`app.main.create_app`, task 3.3) 위에서 mock 없이 무효화↔재발급 seam 을 검증한다. 하네스·
워크스페이스 시나리오·문서 트리·엔진 접근·스윕 접근은 `tests/sharing/conftest.py`(L3 체인
재사용 + s14 확장)에서 온다. 상태 전이(문서 trashed/복구)는 s14 를 거치지 않고 s07/s10
`DocumentStateEngine` primitive(`engine_access`)로 직접 수행하고, 게이트(`is_shareable`)는
s05 `PATCH /workspaces/{id}`(owner)로 뒤집는다 — s14 는 그 관측 가능한 결과만 소비한다.

핵심 상호작용(설계상 이중 구조): 공개 렌더/파일 경로는 무효 링크 관측 시 **lazy retire**
(`GET /public/{token}` 이 404 를 내면서 토큰을 교체)를 수행하고, 무효화 반응 조정 **스윕**
(`ShareInvalidationSweep.invalidate_by_observation`)은 접근과 무관하게 관측 기반으로 retire
한다. 그래서 스윕 그 자체를 격리 증명하려면 스윕 실행 전에는 공개 접근을 하지 않는다(lazy
retire 가 먼저 토큰을 교체해 스윕 대상이 사라지지 않도록).

검증 시나리오(design §Testing Strategy 무효화·재발급 seam):

1. **스윕 주도 retire + 재발급(Req 5.1·5.3·5.4·4.4)**: 발급→(공개 접근 없이)문서 trashed→
   스윕이 retire→이전 토큰 404→문서 복구 후에도 이전 토큰 여전히 404(재발급 필요)→재발급으로
   새 토큰 200이고 이전 토큰과 다름(INV-8 crux).
2. **while-invalid 즉시 차단, 스윕 독립(Req 5.1)**: 발급→trashed→스윕 없이 즉시 404(실시간
   게이트가 스윕 주기와 무관하게 차단).
3. **게이트 off seam(Req 5.2·5.4)**: 발급→게이트 off→즉시 404→(스윕/lazy retire 로 retire)→
   게이트 재 on 후에도 이전 토큰 404→재발급으로 새 토큰 200이고 이전 토큰과 다름.
4. **멱등 스윕(Req 5.6)**: 무효 링크 retire 후 두 번째 스윕은 0을 반환하고 오류를 내지 않는다.
5. **관측 전용(Req 5.5)**: 스윕이 문서 상태를 전이하거나 게이트를 설정하지 않음(문서는 여전히
   trashed, 게이트는 불변)을 확인한다.

제약: 애플리케이션 코드·conftest·다른 spec 자산을 수정하지 않는다(통합 테스트만 추가). DB
미가용·부팅 실패는 스킵이 아니라 실패다(하네스가 오류 전파). 모듈 레벨 `run_invalidation_sweep()`
은 비-테스트 DB 에 바인딩되므로 직접 호출하지 않고 `sharing_sweep` 핸들로 스윕을 구동한다.
"""

from app.document.repository import DocumentRepository
from tests.integration_L2 import helpers as l2_helpers


def _enable_gate(scenario) -> None:
    """워크스페이스 `is_shareable` 게이트를 owner 세션으로 켠다(s05 `PATCH /workspaces/{id}`).

    `doc_tree_scenario` 의 워크스페이스는 게이트 OFF 로 시작하므로, 발급/렌더가 가능하려면
    실제 owner 라우트로 게이트를 켜야 한다(s14 는 게이트를 소유하지 않고 관측만 한다).
    """
    l2_helpers.update_settings(
        scenario.owner_client, scenario.workspace_id, is_shareable=True
    )


def _disable_gate(scenario) -> None:
    """워크스페이스 `is_shareable` 게이트를 owner 세션으로 끈다(s05 라우트)."""
    l2_helpers.update_settings(
        scenario.owner_client, scenario.workspace_id, is_shareable=False
    )


def _issue(editor, doc_id: int) -> str:
    """editor 세션으로 발급/재발급을 태우고 활성 링크의 토큰을 반환한다(200 단언).

    발급/재발급은 항상 새 토큰의 활성 링크를 만든다(INV-8). 이 헬퍼는 200·활성·토큰 존재를
    단언하고 토큰 문자열을 돌려준다(재발급 토큰 부등식 단언에 쓰인다).
    """
    resp = editor.post(f"/documents/{doc_id}/share")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_enabled"] is True
    assert body["share_url"] == f"/public/{body['token']}"
    return body["token"]


def _trash(engine_access, doc_id: int) -> None:
    """s07/s10 경로로 문서를 active→trashed 전이한다(엔진 primitive 직접 호출, s14 미경유).

    부팅 앱과 동일 세션 팩토리로 문서를 로드해 `DocumentStateEngine.trash_document` 를
    호출한다(그 시점 active 하위 캐스케이드 포함). `set_status_bulk` 가 엔진 안에서 단일
    commit 하므로 API 가 관측할 status 가 내구 영속화된다.
    """
    with engine_access.session() as db:
        doc = DocumentRepository().get(db, doc_id)
        assert doc is not None, f"문서 {doc_id} 가 존재해야 한다"
        engine_access.engine.trash_document(db, doc)


def _restore(engine_access, root_id: int) -> None:
    """s07/s10 경로로 trashed 묶음을 복구한다(엔진 primitive 직접 호출, s14 미경유).

    `restore_bundle` 은 루트 위치 재배치 + 구성원 status=active 전환을 단일 커밋으로 적용한다.
    복구 후에도 이전(무효화) 토큰이 되살아나지 않음(INV-8)을 관찰하는 준비 단계다.
    """
    with engine_access.session() as db:
        engine_access.engine.restore_bundle(db, root_id)


def _doc_status(harness, doc_id: int) -> str:
    """부팅 앱과 동일 세션 팩토리로 문서 status 를 신선하게 읽는다(관측 전용 단언용).

    `expire_on_commit=False` 세션 팩토리에서 매번 새 세션을 열어 API/엔진이 커밋한 최신
    status 를 stale 없이 관측한다.
    """
    with harness.session_local() as db:
        doc = DocumentRepository().get(db, doc_id)
        assert doc is not None, f"문서 {doc_id} 가 존재해야 한다"
        return doc.status


def _gate(scenario) -> bool:
    """owner 세션으로 `GET /workspaces/{id}` 를 태워 현재 `is_shareable` 게이트 값을 읽는다."""
    resp = scenario.owner_client.get(f"/workspaces/{scenario.workspace_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()["is_shareable"]


# --- 1. 스윕 주도 retire + 재발급(Req 5.1·5.3·5.4·4.4, INV-8) -----------------------


def test_sweep_retire_then_reissue_mints_fresh_token(
    doc_tree_scenario, harness, engine_access, sharing_sweep
):
    """발급→trashed(공개 접근 없이)→스윕 retire→이전 토큰 404(복구 후에도)→재발급 새 토큰 200.

    스윕을 격리 증명한다: 스윕 실행 전에는 공개 접근을 하지 않아 lazy retire 가 먼저 토큰을
    교체하지 못하게 한다. 무효화 반응 조정 스윕이 관측 기반으로 링크를 retire 하고, 문서를
    복구해도 이전 토큰은 영구 소멸(재발급 필요)하며, 재발급 토큰이 이전과 다름(INV-8)을 단언한다.
    """
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id
    anon = harness.new_client()  # 공개 경로는 인증이 없어 로그인하지 않은 클라이언트로 접근.

    # 발급(게이트 on active 문서) → 활성 링크 토큰 T1.
    t1 = _issue(editor, doc_id)

    # s07/s10 경로로 문서를 trashed 로 전이한다(공개 접근은 아직 하지 않음 — 스윕 격리).
    _trash(engine_access, doc_id)

    # 무효화 반응 조정 스윕 실행 → 무효(trashed) 링크를 retire(비활성 + 토큰 교체).
    retired = sharing_sweep.sweep()
    assert retired >= 1, f"스윕이 무효 링크를 최소 1건 retire 해야 한다: {retired}"

    # 링크 retire 됨 → 이전 토큰 T1 은 조회되지 않아 404(교체된 토큰).
    assert anon.get(f"/public/{t1}").status_code == 404

    # 문서 복구 → 그래도 이전 토큰 T1 은 여전히 404(자동 복원 없음, 재발급 필요, Req 5.4·4.4).
    _restore(engine_access, doc_id)
    dead = anon.get(f"/public/{t1}")
    assert dead.status_code == 404, "복구돼도 이전(무효화) 토큰은 되살아나지 않는다(INV-8)"
    assert dead.json()["code"] == "not_found"

    # 재발급(POST) → 새 토큰 T2, 이전과 다르고(INV-8 crux) 200 으로 렌더된다.
    t2 = _issue(editor, doc_id)
    assert t2 != t1, "재발급 토큰은 이전 토큰과 달라야 한다(INV-8)"
    ok = anon.get(f"/public/{t2}")
    assert ok.status_code == 200, ok.text
    assert ok.json()["root"]["id"] == doc_id


# --- 2. while-invalid 즉시 차단, 스윕 독립(Req 5.1) ---------------------------------


def test_while_invalid_block_is_sweep_independent(
    doc_tree_scenario, harness, engine_access
):
    """발급→trashed→스윕 없이 즉시 404(실시간 게이트가 스윕 주기와 무관하게 차단).

    무효화 반응 조정 스윕을 전혀 구동하지 않고, 문서 trashed 직후 곧바로 공개 접근이 404 임을
    단언한다 — while-invalid 차단이 스윕 사이클에 의존하지 않음(실시간 공개 유효성 게이트)을 증명.
    """
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id
    anon = harness.new_client()

    t3 = _issue(editor, doc_id)
    # sanity: 활성 링크는 렌더된다.
    assert anon.get(f"/public/{t3}").status_code == 200

    # s07/s10 경로로 문서를 trashed 로 전이한다.
    _trash(engine_access, doc_id)

    # 스윕을 구동하지 않은 채 즉시 공개 접근 → 404(실시간 게이트, 스윕 독립).
    blocked = anon.get(f"/public/{t3}")
    assert blocked.status_code == 404, "실시간 게이트가 스윕 없이 즉시 차단해야 한다(Req 5.1)"
    assert blocked.json()["code"] == "not_found"


# --- 3. 게이트 off seam(Req 5.2·5.4) -----------------------------------------------


def test_gate_off_seam_requires_reissue(
    doc_tree_scenario, harness, engine_access, sharing_sweep
):
    """발급→게이트 off 즉시 404→retire→게이트 재 on 후에도 이전 토큰 404→재발급 새 토큰 200.

    게이트 off 는 문서 trashed 와 동일하게 링크를 무효화하며(실시간 게이트), 게이트를 다시 켜도
    이전 토큰은 자동 복원되지 않고(재발급 필요, Req 5.4) 재발급 토큰이 이전과 다름(INV-8)을 단언한다.
    """
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id
    anon = harness.new_client()

    t4 = _issue(editor, doc_id)
    assert anon.get(f"/public/{t4}").status_code == 200

    # s05 게이트 off → 즉시 404(실시간 게이트). 이 접근이 lazy retire 로 토큰을 교체한다.
    _disable_gate(scenario)
    off = anon.get(f"/public/{t4}")
    assert off.status_code == 404, "게이트 off 는 즉시 무효(실시간 게이트, Req 5.2)"

    # 무효화 반응 조정 스윕도 구동한다(멱등 — lazy retire 로 이미 비활성이면 무해).
    assert sharing_sweep.sweep() >= 0

    # 게이트 재 on → 그래도 이전 토큰 T4 는 여전히 404(자동 복원 없음, 재발급 필요).
    _enable_gate(scenario)
    dead = anon.get(f"/public/{t4}")
    assert dead.status_code == 404, "게이트 재 on 후에도 이전 토큰은 되살아나지 않는다(INV-8)"

    # 재발급(POST) → 새 토큰 T5, 이전과 다르고 200 으로 렌더된다.
    t5 = _issue(editor, doc_id)
    assert t5 != t4, "재발급 토큰은 이전 토큰과 달라야 한다(INV-8)"
    ok = anon.get(f"/public/{t5}")
    assert ok.status_code == 200, ok.text
    assert ok.json()["root"]["id"] == doc_id


# --- 4. 멱등 스윕(Req 5.6) ---------------------------------------------------------


def test_repeated_sweep_is_idempotent(
    doc_tree_scenario, engine_access, sharing_sweep
):
    """무효 링크 retire 후 두 번째 스윕은 0을 반환하고 오류를 내지 않는다(멱등, Req 5.6).

    스윕 스코프는 항상 `is_enabled=true` 만 대상이므로, 첫 스윕이 무효 링크를 모두 retire(비활성)
    하면 두 번째 스윕은 대상이 없어 0을 반환한다(재무효화·오류 없음).
    """
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id

    _issue(editor, doc_id)
    _trash(engine_access, doc_id)

    first = sharing_sweep.sweep()
    assert first >= 1, f"첫 스윕이 무효 링크를 retire 해야 한다: {first}"

    second = sharing_sweep.sweep()
    assert second == 0, f"이미 무효화된 링크는 재무효화되지 않아야 한다(멱등): {second}"


# --- 5. 관측 전용(Req 5.5) ---------------------------------------------------------


def test_sweep_is_observe_only(
    doc_tree_scenario, engine_access, sharing_sweep, harness
):
    """스윕이 문서 상태를 전이하거나 게이트를 설정하지 않음을 확인한다(관측만, Req 5.5).

    문서는 엔진이 남긴 상태 그대로(여전히 trashed)이고 워크스페이스 게이트도 스윕 전후로 불변
    이어야 한다 — s14 는 status·게이트를 관측만 하고 상태 전이·게이트 설정을 수행하지 않는다.
    """
    scenario = doc_tree_scenario.scenario
    _enable_gate(scenario)
    editor = doc_tree_scenario.editor_client
    doc_id = doc_tree_scenario.root_id

    _issue(editor, doc_id)
    _trash(engine_access, doc_id)

    # 스윕 전 관측: 문서는 trashed, 게이트는 on.
    assert _doc_status(harness, doc_id) == "trashed"
    gate_before = _gate(scenario)
    assert gate_before is True

    retired = sharing_sweep.sweep()
    assert retired >= 1, f"스윕이 무효 링크를 retire 해야 한다: {retired}"

    # 스윕 후: 문서 status·게이트는 스윕이 건드리지 않아 그대로다(관측 전용).
    assert _doc_status(harness, doc_id) == "trashed", (
        "스윕이 문서 상태를 바꾸면 안 된다(관측만, Req 5.5)"
    )
    gate_after = _gate(scenario)
    assert gate_after == gate_before, "스윕이 게이트를 바꾸면 안 된다(관측만, Req 5.5)"
    assert gate_after is True
