"""공유 발급·토글·공개 렌더·동적 하위 흐름 스위트 (Task 2.2 / Req 3.1, 3.2, 3.3, 3.4, 3.5,
design §ShareLifecycleFlowSuite · §System Flows(공유 발급 → 공개 렌더 → 동적 하위)).

실제 결합된 런타임(마이그레이션 DB + 부팅 앱(s01⊕s02⊕s03⊕s05⊕s07⊕s09⊕s10⊕s12⊕**s14**) +
role별 실 세션 + 익명 공개 클라이언트)에서 **이번 계층(공유)이 처음 결합하는 발급·토글·공개
렌더·동적 하위 흐름**을 mock 없이 e2e 로 관찰한다. 판정은 s05 실제 멤버십(`workspace_member`)
위에서, 게이트는 s05 `is_shareable` 위에서, 공개 렌더는 s07 안전 HTML·`active_descendants`
위에서 성립한다. 대조 기준은 s14 design 이 아니라 s01 단일 소스(카탈로그 행 34~37·에러 코드
카탈로그·`ShareLinkRead`·`PublicDocumentRead` 최소 노출·불변식 INV-1·2·3)다.

다섯 개의 단언 그룹(task 2.2):

- **Group 1 — 발급·게이트(3.1 / 7.1·7.2·7.3)**: 게이트 on·문서 active 면 editor 발급 200
  `ShareLinkRead`(활성 토큰); 게이트 off 면 발급 409(conflict); 게이트 off 상태에서 비활성
  링크의 활성화 토글 409(conflict, 재발급 통일의 유일한 상태 기반 예외의 게이팅).
- **Group 2 — 공개 읽기전용 렌더(3.2 / 7.4)**: 익명 `GET /public/{token}` → 200
  `PublicDocumentRead{root}`; root 는 s07 안전 HTML `content_html` 을 가지며, 트리 노드는
  id/title/content_html/children 만 노출(내부 필드 은닉). 공개 라우트는 GET 전용이라 변경
  동작이 없다(구조적 읽기 전용 — 상태 변화 없음).
- **Group 3 — 동적 active 하위(3.3 / 7.5·7.6)**: 공유 문서에 새 active 하위를 추가하면
  같은 토큰의 재요청 트리에 그 id 가 동적으로 포함되고(접근 시점 산정), 그 하위를 trashed 로
  전이시키면 재요청 트리에서 제외된다(active_descendants 는 trashed 서브트리 제외). 토큰 불변.
- **Group 4 — 토글 off/on 동일 토큰(3.4 / 7.7)**: editor 가 off 토글 → 동일 토큰 공개 404 →
  on 토글 → 동일 토큰 공개 200. off→on 을 관통해 토큰 문자열이 **동일**함을 응답·DB(`token_of`)
  양쪽으로 확인(토글은 토큰을 유지하는 재발급 통일의 유일한 상태 기반 예외).
- **Group 5 — 게이팅(3.5 / INV-1·2·3)**: 발급/토글은 `require_ws_role(EDITOR)`(문서→WS 어댑터)
  게이팅 — viewer 403(INV-2)·비멤버 403(INV-1)·미인증 401·미존재 문서/링크 404, admin 은
  비멤버 WS 에서도 발급/토글 200(INV-3 bypass). 판정은 s05 실 멤버십 세션 위에서.

`share_scenario`(게이트 on·발급된 링크·익명 공개 클라이언트)·`doc_tree_scenario`(게이트 기본
off·active 트리)·`share_link_observation`(DB 토큰 관측) 픽스처가 제공하는 실 결합 환경 위에서만
동작하며 mock/stub/fake 를 쓰지 않는다. 문서 생성/삭제·게이트 토글은 실제 s07·s10·s05 라우트를
탄다(L5 → L3/L2 헬퍼 재사용). 실 행위가 계약과 다르면 단언을 약화시키지 않고 그대로 실패시킨다.

재검증 트리거(design §Revalidation Triggers): `s01`(계약)·`s02`·`s03`·`s05`·`s07`·`s09`·`s10`·
`s12`·`s14` 중 하나라도 수정되면 이 체크포인트를 누적 집합 기준으로 재실행한다(`s01` 수정 시
모든 체크포인트).
"""

import uuid

from app.models import WorkspaceMember
from tests.integration_L6 import helpers

# s01 §Base Schemas — 공개 렌더 노드가 노출해야 하는 최소 필드(내부 필드 은닉 대조).
PUBLIC_NODE_FIELDS = {"id", "title", "content_html", "children"}

# 공개 노드가 **노출하지 않아야** 하는 내부 필드(최소 노출 판정 표본).
PUBLIC_NODE_FORBIDDEN_FIELDS = {"workspace_id", "created_by", "status", "parent_id", "sort_order"}

# 인증되었으나 대상이 존재하지 않을 때 어댑터 404 를 관측하기 위한 미존재 문서 id.
MISSING_DOCUMENT_ID = 999_999_999


def _unique_title(prefix: str) -> str:
    """공유 테스트 DB 충돌을 피하는 고유 제목(uuid4 접미사)."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _assert_public_node_minimal(node: dict) -> None:
    """공개 렌더 노드가 s01 최소 노출 규약(id·title·content_html·children 만)을 따르는지 재귀 강제.

    각 노드는 정확히 계약 필드만 담고 내부 필드(workspace_id·status 등)를 유출하지 않으며,
    ``content_html`` 은 s07 안전 HTML 렌더 결과인 문자열이다(INV-8 정보 비노출의 스키마 근거).
    """
    keys = set(node)
    assert keys == PUBLIC_NODE_FIELDS, (
        f"공개 렌더 노드는 id·title·content_html·children 만 노출해야 한다(최소 노출): "
        f"관측 키={sorted(keys)}"
    )
    leaked = PUBLIC_NODE_FORBIDDEN_FIELDS & keys
    assert not leaked, f"공개 렌더 노드가 내부 필드를 유출하면 안 된다: 유출={sorted(leaked)}"
    assert isinstance(node["content_html"], str), (
        f"공개 렌더 노드 content_html 은 안전 HTML 문자열이어야 한다: {node['content_html']!r}"
    )
    assert isinstance(node["title"], str)
    for child in node["children"]:
        _assert_public_node_minimal(child)


# =============================================================================
# Group 1 — 발급·게이트 (Req 3.1 / 7.1·7.2·7.3)
# =============================================================================


def test_issue_gate_on_active_document_returns_200_active_link(share_scenario):
    """게이트 on·문서 active 면 editor 발급 → 200 `ShareLinkRead`(활성 토큰) (3.1, 7.1·7.3).

    `share_scenario` 는 게이트를 열고 active 루트에 이미 발급한 상태다. editor 가 발급
    라우트(`POST /documents/{id}/share`)를 태우면 계약상 **200**(upsert 통일이라 201 아님)로
    `ShareLinkRead` 를 돌려주고, 링크가 활성(`is_enabled=True`)이며 비어있지 않은 토큰과
    `share_url=/public/{token}` 을 노출함을 확인한다(발급 게이트 통과).
    """
    resp = helpers.attempt_issue_share(
        share_scenario.editor_client, share_scenario.document_id
    )
    assert resp.status_code == 200, (
        f"게이트 on active 문서 editor 발급은 200 이어야 한다(upsert 통일): "
        f"{resp.status_code} {resp.text}"
    )
    link = resp.json()
    assert link["is_enabled"] is True, f"발급 링크는 활성이어야 한다: {link!r}"
    assert isinstance(link["token"], str) and link["token"], (
        f"발급 링크는 비어있지 않은 토큰을 노출해야 한다: {link!r}"
    )
    assert link["document_id"] == share_scenario.document_id, (
        f"발급 링크 document_id 는 공유 문서여야 한다: {link!r}"
    )
    assert link["share_url"] == f"/public/{link['token']}", (
        f"share_url 은 /public/{{token}} 파생이어야 한다: {link!r}"
    )


def test_issue_gate_off_returns_409_conflict(doc_tree_scenario):
    """게이트 off 워크스페이스의 active 문서 editor 발급 → 409 conflict (3.1, 7.2).

    `doc_tree_scenario` 워크스페이스는 `is_shareable` 기본 false(s01 기본)이므로 게이트를 열지
    않고 editor 가 active 루트에 발급을 시도하면 서비스가 게이트 off 관측으로 409(conflict)로
    거부한다. 게이트가 s05 소유(s14 는 관측만)임을 상태 기반 거부로 재확인한다.
    """
    resp = helpers.attempt_issue_share(
        doc_tree_scenario.editor_client, doc_tree_scenario.root_id
    )
    assert resp.status_code == 409, (
        f"게이트 off 발급은 409 여야 한다: {resp.status_code} {resp.text}"
    )
    assert resp.json()["code"] == "conflict", (
        f"게이트 off 발급 409 는 code=conflict 여야 한다: {resp.json()!r}"
    )


def test_activate_disabled_link_gate_off_returns_409_conflict(share_scenario):
    """게이트 off 상태에서 비활성 링크의 활성화 토글 → 409 conflict (3.1, 7.2).

    준비: (1) editor 가 링크를 비활성화(항상 허용, 200·토큰 유지), (2) owner 가 s05 경로로
    게이트를 닫는다. 이후 (3) editor 가 재활성화(`PATCH is_enabled=true`)를 시도하면 서비스가
    게이트 off 관측으로 409(conflict)로 거부함을 확인한다(활성화만이 재발급 통일의 상태 기반
    예외이며 게이트에 종속됨). 비활성화는 게이트 무관 항상 허용됨도 함께 관측한다.
    """
    editor = share_scenario.editor_client
    doc_id = share_scenario.document_id

    # (1) 비활성화 — 게이트·status 무관 항상 허용(토큰 유지).
    disabled = helpers.toggle_share(editor, doc_id, is_enabled=False)
    assert disabled["is_enabled"] is False, f"비활성화 후 is_enabled False 여야 한다: {disabled!r}"

    # (2) 게이트 닫기 — owner 경로 s05 설정 라우트 재사용.
    helpers.set_gate(
        share_scenario.owner_client, share_scenario.workspace_id, is_shareable=False
    )

    # (3) 재활성화 시도 — 게이트 off → 409 conflict.
    resp = helpers.attempt_toggle_share(editor, doc_id, is_enabled=True)
    assert resp.status_code == 409, (
        f"게이트 off 재활성화는 409 여야 한다: {resp.status_code} {resp.text}"
    )
    assert resp.json()["code"] == "conflict", (
        f"게이트 off 재활성화 409 는 code=conflict 여야 한다: {resp.json()!r}"
    )


# =============================================================================
# Group 2 — 공개 읽기전용 렌더 (Req 3.2 / 7.4)
# =============================================================================


def test_public_render_returns_readonly_minimal_tree(share_scenario):
    """익명 `GET /public/{token}` → 200 `PublicDocumentRead{root}` 안전 HTML 최소 노출 트리 (3.2, 7.4).

    인증 없이 익명 공개 클라이언트로 유효 토큰을 렌더하면 200 `PublicDocumentRead` 가 반환되고,
    root id 가 공유 문서이며, 트리의 모든 노드가 id·title·content_html·children 만 노출(내부
    필드 은닉)하고 root 가 s07 안전 HTML `content_html`(문자열)을 가짐을 확인한다. 공유 문서의
    현재 active 하위(child·grandchild)가 트리에 포함됨도 관측한다.
    """
    public = helpers.public_render(share_scenario.public_client, share_scenario.token)
    assert set(public) == {"root"}, (
        f"PublicDocumentRead 는 root 만 담아야 한다: 관측 키={sorted(public)}"
    )
    root = public["root"]
    assert root["id"] == share_scenario.document_id, (
        f"공개 렌더 root 는 공유 문서여야 한다: root_id={root['id']} 공유={share_scenario.document_id}"
    )
    _assert_public_node_minimal(root)

    ids = helpers.collect_node_ids(public)
    assert share_scenario.child_id in ids, (
        f"현재 active 하위(child)가 공개 트리에 포함되어야 한다: 트리 id={sorted(ids)}"
    )
    assert share_scenario.grandchild_id in ids, (
        f"현재 active 하위(grandchild)가 공개 트리에 포함되어야 한다: 트리 id={sorted(ids)}"
    )


def test_public_route_is_get_only_no_mutating_verbs(share_scenario):
    """공개 렌더 라우트는 GET 전용 — 변경 동작(POST/PATCH/DELETE)이 제공되지 않음(3.2, 7.4 읽기 전용).

    공개 경로는 읽기 전용 렌더만 노출한다. 익명 클라이언트로 유효 토큰에 대해 변경 동사를
    태우면 성공(2xx)하지 않고 라우트가 그 동사를 제공하지 않음(405 Method Not Allowed 또는
    404)을 확인해, 공개 접근에 상태 변화 경로가 없음을 구조적으로 관측한다. GET 은 여전히 200.
    """
    client = share_scenario.public_client
    token = share_scenario.token
    for verb in ("post", "patch", "delete", "put"):
        resp = getattr(client, verb)(f"/public/{token}")
        assert resp.status_code >= 400, (
            f"공개 렌더 라우트에 {verb.upper()} 변경 동작이 성공하면 안 된다(읽기 전용): "
            f"{resp.status_code} {resp.text}"
        )
        assert resp.status_code in (404, 405), (
            f"공개 렌더 라우트는 {verb.upper()} 를 제공하지 않아야 한다(405/404): "
            f"{resp.status_code} {resp.text}"
        )
    # GET 은 여전히 유효(읽기 전용 렌더는 정상 동작).
    assert helpers.attempt_public_render(client, token).status_code == 200


# =============================================================================
# Group 3 — 동적 active 하위 (Req 3.3 / 7.5·7.6)
# =============================================================================


def test_new_active_child_included_then_trashed_excluded(share_scenario):
    """공유 문서에 새 active 하위 추가 시 동적 포함, 그 하위 trashed 시 제외(같은 토큰) (3.3, 7.5·7.6).

    같은 토큰을 관통해: (1) 최초 공개 트리에는 새 하위가 없다, (2) editor 가 공유 문서 밑에 새
    active 하위를 추가(s07 `create_document`, parent=공유 문서)하면 재요청 트리에 그 id 가
    동적으로 포함된다(접근 시점 active_descendants 산정), (3) editor 가 그 하위를 trashed(s10
    `delete_document`)로 전이시키면 재요청 트리에서 제외된다(trashed 서브트리 배제). 동일 토큰이
    문서 트리 변화를 시점별로 반영함을 관측한다.
    """
    editor = share_scenario.editor_client
    token = share_scenario.token
    ws_id = share_scenario.workspace_id
    doc_id = share_scenario.document_id

    # (1) 최초 트리 — 새 하위 아직 없음.
    before = helpers.collect_node_ids(
        helpers.public_render(share_scenario.public_client, token)
    )

    # (2) 새 active 하위 추가 → 동적 포함.
    new_child = helpers.l3_helpers.create_document(
        editor, ws_id, _unique_title("동적하위"), parent_id=doc_id
    )
    new_child_id = new_child["id"]
    assert new_child_id not in before, (
        f"추가 전 트리에는 새 하위가 없어야 한다: {new_child_id} in {sorted(before)}"
    )

    after_add = helpers.collect_node_ids(
        helpers.public_render(share_scenario.public_client, token)
    )
    assert new_child_id in after_add, (
        f"새 active 하위가 같은 토큰 재요청 트리에 동적 포함되어야 한다(7.5·7.6): "
        f"{new_child_id} not in {sorted(after_add)}"
    )

    # (3) 그 하위 trashed → 동적 제외.
    helpers.l3_helpers.delete_document(editor, new_child_id)

    after_trash = helpers.collect_node_ids(
        helpers.public_render(share_scenario.public_client, token)
    )
    assert new_child_id not in after_trash, (
        f"trashed 하위는 같은 토큰 재요청 트리에서 제외되어야 한다(active_descendants 배제): "
        f"{new_child_id} in {sorted(after_trash)}"
    )
    # 공유 문서(root)는 여전히 렌더된다(트리 자체는 유효).
    assert doc_id in after_trash, "공유 문서 root 는 여전히 트리에 있어야 한다"


# =============================================================================
# Group 4 — 토글 off/on 동일 토큰 (Req 3.4 / 7.7)
# =============================================================================


def test_toggle_off_on_keeps_same_token(share_scenario, share_link_observation):
    """editor off 토글 → 동일 토큰 공개 404 → on 토글 → 동일 토큰 공개 200, 토큰 불변(3.4, 7.7).

    재발급 통일 원칙의 유일한 상태 기반 예외(토글은 토큰 유지)를 관통 관찰한다: (1) 초기 토큰을
    응답·DB(`token_of`) 양쪽으로 확정, (2) editor 가 off 토글 → 동일 토큰 익명 공개 404(실시간
    게이트), (3) editor 가 on 토글 → 동일 토큰 익명 공개 200, (4) off→on 을 관통해 DB 토큰이
    교체되지 않았음(발급/retire 가 새 토큰을 내는 것과 대비되는 유일한 예외)을 확인한다.
    """
    editor = share_scenario.editor_client
    doc_id = share_scenario.document_id
    public = share_scenario.public_client
    token = share_scenario.token

    # (1) 초기 토큰 — 응답·DB 일치 확정.
    db_token_before = helpers.share_token(share_link_observation, doc_id)
    assert db_token_before == token, (
        f"초기 DB 토큰이 발급 응답 토큰과 일치해야 한다: DB={db_token_before!r} 응답={token!r}"
    )
    assert helpers.attempt_public_render(public, token).status_code == 200, (
        "토글 전 유효 토큰 공개 렌더는 200 이어야 한다"
    )

    # (2) off 토글 → 동일 토큰 공개 404(실시간 게이트).
    off = helpers.toggle_share(editor, doc_id, is_enabled=False)
    assert off["is_enabled"] is False and off["token"] == token, (
        f"off 토글은 토큰을 유지해야 한다: {off!r}"
    )
    assert helpers.attempt_public_render(public, token).status_code == 404, (
        "off 토글 후 동일 토큰 공개 렌더는 404 여야 한다(실시간 게이트)"
    )

    # (3) on 토글 → 동일 토큰 공개 200.
    on = helpers.toggle_share(editor, doc_id, is_enabled=True)
    assert on["is_enabled"] is True and on["token"] == token, (
        f"on 토글은 토큰을 유지해야 한다: {on!r}"
    )
    assert helpers.attempt_public_render(public, token).status_code == 200, (
        "on 토글 후 동일 토큰 공개 렌더는 200 이어야 한다(토큰 유지)"
    )

    # (4) off→on 관통 DB 토큰 불변 — 토글은 토큰을 교체하지 않는다(유일한 상태 기반 예외).
    db_token_after = helpers.share_token(share_link_observation, doc_id)
    assert db_token_after == token, (
        f"토글 off→on 을 관통해 DB 토큰이 교체되면 안 된다(7.7 유일한 예외): "
        f"이전={token!r} 이후={db_token_after!r}"
    )


# =============================================================================
# Group 5 — 게이팅 (Req 3.5 / INV-1·2·3)
# =============================================================================


def test_issue_viewer_forbidden_403(share_scenario):
    """viewer 의 공유 발급 → 403 forbidden (3.5, INV-2 viewer 읽기 전용).

    게이트 on·실존 active 문서 위에서 viewer(멤버지만 editor 미만)의 발급 요청이
    `require_ws_role(EDITOR)` 게이트에서 403 으로 거부됨을 실 멤버십 세션으로 확인한다.
    """
    resp = helpers.attempt_issue_share(
        share_scenario.viewer_client, share_scenario.document_id
    )
    assert resp.status_code == 403, (
        f"viewer 공유 발급은 403 이어야 한다(INV-2): {resp.status_code} {resp.text}"
    )
    assert resp.json()["code"] == "forbidden", f"{resp.json()!r}"


def test_toggle_viewer_forbidden_403(share_scenario):
    """viewer 의 공유 토글 → 403 forbidden (3.5, INV-2).

    발급과 대칭으로 토글도 editor 게이트에 걸린다. viewer 가 활성 링크를 비활성화 토글하려
    해도 role 게이트에서 403 으로 거부됨(변경 불가)을 확인한다.
    """
    resp = helpers.attempt_toggle_share(
        share_scenario.viewer_client, share_scenario.document_id, is_enabled=False
    )
    assert resp.status_code == 403, (
        f"viewer 공유 토글은 403 이어야 한다(INV-2): {resp.status_code} {resp.text}"
    )
    assert resp.json()["code"] == "forbidden", f"{resp.json()!r}"


def test_issue_nonmember_forbidden_403(share_scenario):
    """비멤버의 공유 발급 → 403 forbidden (3.5, INV-1 워크스페이스 단위 판정).

    워크스페이스 멤버가 아닌 사용자는 문서→WS resolver 가 role None 을 반환해 403 으로 막힌다
    (문서별 개별 권한 없음, 판정은 워크스페이스 단위). 실 멤버십 세션으로 확인한다.
    """
    resp = helpers.attempt_issue_share(
        share_scenario.nonmember_client, share_scenario.document_id
    )
    assert resp.status_code == 403, (
        f"비멤버 공유 발급은 403 이어야 한다(INV-1): {resp.status_code} {resp.text}"
    )
    assert resp.json()["code"] == "forbidden", f"{resp.json()!r}"


def test_issue_unauthenticated_401(share_scenario):
    """미인증 사용자의 공유 발급 → 401 unauthenticated (3.5).

    세션 없는 익명 클라이언트의 발급 요청은 요구 role·문서 존재 판정 이전에 `get_current_user`
    가 401 을 산출한다(발급은 공개 경로가 아니라 인증 게이트가 앞선다).
    """
    resp = helpers.attempt_issue_share(
        share_scenario.public_client, share_scenario.document_id
    )
    assert resp.status_code == 401, (
        f"미인증 공유 발급은 401 이어야 한다: {resp.status_code} {resp.text}"
    )
    assert resp.json()["code"] == "unauthenticated", f"{resp.json()!r}"


def test_issue_missing_document_404(share_scenario):
    """게이트를 통과하는 editor 로 미존재 문서 발급 → 404 not_found (3.5, 문서→WS 어댑터).

    인증 멤버(editor)로 미존재 문서에 발급을 시도하면 문서→WS 어댑터가 매핑 실패로 404 를
    낸다(서비스 진입 이전 어댑터 거부). 비멤버는 403 으로 막히므로 어댑터 404 경로를 관측하려면
    게이트를 통과하는 editor 로 호출한다.
    """
    resp = helpers.attempt_issue_share(
        share_scenario.editor_client, MISSING_DOCUMENT_ID
    )
    assert resp.status_code == 404, (
        f"미존재 문서 발급은 404 여야 한다: {resp.status_code} {resp.text}"
    )
    assert resp.json()["code"] == "not_found", f"{resp.json()!r}"


def test_toggle_missing_link_404(share_scenario):
    """링크가 없는 문서의 토글 → 404 not_found (3.5, 미존재 링크).

    게이트 on 워크스페이스에 editor 가 링크를 발급하지 않은 새 문서를 만들고 그 문서에
    `PATCH /documents/{id}/share` 토글을 시도하면, role 게이트(editor)는 통과하지만 대상
    share_link 부재로 404(not_found)로 거부됨을 확인한다(토글은 기존 링크 상태 전환이며 발급이
    아니다).
    """
    editor = share_scenario.editor_client
    fresh = helpers.l3_helpers.create_document(
        editor, share_scenario.workspace_id, _unique_title("링크없는문서")
    )
    resp = helpers.attempt_toggle_share(editor, fresh["id"], is_enabled=False)
    assert resp.status_code == 404, (
        f"미존재 링크 토글은 404 여야 한다: {resp.status_code} {resp.text}"
    )
    assert resp.json()["code"] == "not_found", f"{resp.json()!r}"


def test_admin_bypass_issue_and_toggle_on_nonmember_workspace(
    share_scenario, share_link_observation, harness
):
    """admin(비멤버)이 비멤버 WS 문서에 발급·토글 → 200 (3.5, INV-3 admin bypass).

    admin 은 이 워크스페이스의 멤버가 아니지만(먼저 `workspace_member` 부재로 확인) role 게이트를
    bypass 해 발급(`POST /documents/{id}/share` → 200)·토글(`PATCH …/share` → 200)에 성공한다.
    (1) admin `/auth/me` 로 admin user_id·is_admin 을 확정하고, (2) DB 에서 그 user_id 의
    이 워크스페이스 멤버십 행이 없음을 확인한 뒤, (3) 발급·토글이 모두 200 임을 관측한다(어떤
    권한 검사로도 차단되지 않음, INV-3).
    """
    admin = share_scenario.admin_client
    ws_id = share_scenario.workspace_id
    doc_id = share_scenario.document_id

    # (1) admin 정체성 확정 — is_admin·user_id.
    me = admin.get("/auth/me")
    assert me.status_code == 200, f"admin /auth/me 200 이어야 한다: {me.status_code} {me.text}"
    me_body = me.json()
    assert me_body["is_admin"] is True, f"admin_client 는 is_admin True 여야 한다: {me_body!r}"
    admin_user_id = me_body["id"]

    # (2) admin 이 이 워크스페이스의 멤버가 아님을 DB 로 확인(비멤버 bypass 관찰의 전제).
    with harness.session_local() as db:
        membership = (
            db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == ws_id,
                WorkspaceMember.user_id == admin_user_id,
            )
            .one_or_none()
        )
    assert membership is None, (
        f"admin 은 이 워크스페이스 멤버가 아니어야 한다(비멤버 bypass 전제): {membership!r}"
    )

    # (3) 발급 bypass → 200.
    issue_resp = helpers.attempt_issue_share(admin, doc_id)
    assert issue_resp.status_code == 200, (
        f"admin(비멤버) 발급은 role 게이트를 bypass 해 200 이어야 한다(INV-3): "
        f"{issue_resp.status_code} {issue_resp.text}"
    )
    assert issue_resp.json()["is_enabled"] is True, f"{issue_resp.json()!r}"

    # (3) 토글 bypass → 200(비활성화 후 재활성화, 게이트 on 이라 활성화도 허용).
    off_resp = helpers.attempt_toggle_share(admin, doc_id, is_enabled=False)
    assert off_resp.status_code == 200, (
        f"admin(비멤버) 비활성화 토글은 200 이어야 한다(INV-3): "
        f"{off_resp.status_code} {off_resp.text}"
    )
    on_resp = helpers.attempt_toggle_share(admin, doc_id, is_enabled=True)
    assert on_resp.status_code == 200, (
        f"admin(비멤버) 재활성화 토글은 게이트 on 위에서 200 이어야 한다(INV-3): "
        f"{on_resp.status_code} {on_resp.text}"
    )
    # 토글이 토큰을 유지함(admin 경로도 동일 계약).
    assert helpers.share_is_enabled(share_link_observation, doc_id) is True
