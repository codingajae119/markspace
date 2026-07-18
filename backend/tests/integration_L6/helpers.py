"""L6 공유·무효화 스윕·공개 접근·게이트 토글 시나리오 헬퍼 — 실제 s14 라우트·실제 무효화 스윕·
실제 share_link 관찰의 얇은 래퍼 (Task 1.2 / Req 1.4·3.1·4.1·5.1·6.1·7.1, design §Helpers).

후속 스위트(누적 계약 대조 2.1 · 공유 발급/토글/공개 렌더 흐름 2.2 · 무효화·재발급 결합 2.3 ·
링크 경유 첨부 접근·연동 차단 2.4 · 전 계층 불변식 회귀 2.5 · 전 계층 관통 e2e 2.6)가 공유 발급→
토글, 익명 공개 렌더·링크 경유 첨부 서빙, 관측 기반 무효화 스윕, retire/재발급 관찰, 게이트 토글
같은 cross-spec 시나리오를 간결하게 표현하도록, s14 공유 라우트(s01 카탈로그 행 34~37)의 **실제**
엔드포인트와 s14 `ShareInvalidationSweep` 의 **실제** 스윕(부팅 앱과 동일 세션 팩토리로 조립)·실제
`ShareLinkRepository` 관찰을 감싸는 얇은 래퍼를 모은다. mock 이 아니라 부팅된 앱
(`app.main.create_app`, s14 공유 라우터·무효화 스케줄러 조립)의 실 라우트·실 스윕·실 DB 관찰을 태운다.

## 설계 규칙 (음성 경로 가능성 보존 — L5/L4/L3/L2/L1 helpers.py 관용 답습)
- **attempt 계열** (:func:`attempt_issue_share`·:func:`attempt_toggle_share`·
  :func:`attempt_public_render`·:func:`attempt_public_attachment`): 후속 스위트가 같은 래퍼로
  성공(200)과 실패(401/403/404/409/422)를 **둘 다** 단언해야 하므로 **응답 객체를 그대로 반환하고
  상태를 내부에서 단언하지 않는다**. viewer/비멤버 403·미인증 401·미존재 404·게이트 off 409 를
  같은 래퍼로 관찰한다. 공개 경로는 무효/부재/범위 밖을 모두 404 로 통일(INV-8)함을 관찰한다.
- **setup 계열** (:func:`issue_share`·:func:`toggle_share`·:func:`public_render`·
  :func:`public_attachment`): 시나리오 준비상 항상 성공하는 단계이므로 성공 상태(200)를 내부에서
  단언하고 유용한 값(파싱된 ``ShareLinkRead``/``PublicDocumentRead`` dict / :class:`Response`)을
  돌려주어 시나리오 코드를 읽기 쉽게 한다. 내부적으로 대응하는 attempt 래퍼를 재사용한다(URL·바디
  단일 정의).

## L5/L4/L3/L2/L1 헬퍼 재사용 (중복 정의 금지)
잠금(`lock`)·저장(`save`)·휴지통 삭제/복구/완전삭제·retention 스윕(`run_sweep`)·아카이브 스윕
(`run_archival_sweep`)·첨부 업로드/서빙(`upload_image`·`upload_file`·`get_attachment`)·파일시스템
관찰·문서 생성/삭제/이동(L3)·워크스페이스·멤버·role·설정(L2)·계정·로그인·상태 전이(L1) 래퍼는
`s13` L5 `helpers.py`(및 그것이 재-export 하는 L4/L3/L2/L1)를 **그대로** 쓴다(재정의하지 않는다).
이 모듈은 L5 helpers 를 참조로 재-export 하므로 스위트가 한 지점
(``tests.integration_L6.helpers``)에서 공유 발급·토글·공개 렌더·링크 경유 첨부·무효화 스윕·
share_link 관찰 래퍼는 물론 잠금·저장·휴지통·첨부·문서·엔진·워크스페이스·계정 헬퍼까지 모두
도달한다(중복 **정의**가 아닌 참조).

## 게이트 토글 — s05 설정 라우트(L2 `update_settings`) 재사용
:func:`set_gate` 는 s14 전용 라우트를 새로 만들지 않고 s05 워크스페이스 설정 라우트(L2
`update_settings` = PATCH /workspaces/{id}, owner/admin 경로)에 `is_shareable` 필드를 실어
게이트를 연다/닫는다. s14 는 게이트 설정을 소유하지 않는다 — 무효화 스윕·발급 게이트가 s05 가
만든 `workspace.is_shareable` 관측 결과를 뒤에서 소비할 뿐이다.

## 무효화 스윕·share_link 관찰 — 하네스 접근 핸들에 얇게 위임
:func:`run_invalidation_sweep` 은 :class:`~tests.integration_L6.conftest.ShareInvalidationSweepAccess`
핸들(부팅 앱과 동일 세션 팩토리로 실제 :class:`~app.sharing.invalidation.ShareInvalidationSweep`
조립)에, share_link 관찰(:func:`share_token` 등)은
:class:`~tests.integration_L6.conftest.ShareLinkObservation` 핸들에 위임하는 **얇은 래퍼**다(로직
중복·mock 없음 — 세션 수명·커밋은 핸들이 소유).

공유 엔드포인트 계약 (s01 단일 소스, 카탈로그 행 34~37):
- ``POST /documents/{id}/share`` (EDITOR, 발급/재발급 upsert 통일) → 200 ``ShareLinkRead``
  (id·created_at·updated_at=None·document_id·token·is_enabled·share_url=`/public/{token}`; 항상
  새 토큰) / viewer·비멤버 403 / 미인증 401 / 미존재 문서 404 / 게이트 off·비active 409
- ``PATCH /documents/{id}/share`` (EDITOR, body `{"is_enabled": bool}`) → 200 ``ShareLinkRead``
  (토글, 토큰 유지) / 비활성→활성 게이트 off·비active 409 / 링크 부재 404 / 403·401 / 422
- ``GET /public/{token}`` (PUBLIC, 익명) → 200 ``PublicDocumentRead``{root:{id,title,content_html,
  children}} / 모든 무효·부재·범위 밖·trashed·게이트 off 는 404 로 통일(INV-8 비노출)
- ``GET /public/{token}/attachments/{aid}`` (PUBLIC) → 200 binary stream / 범위 밖·다른 WS·보관·
  부재 404 로 통일
"""

from fastapi.testclient import TestClient
from httpx import Response

# L5 헬퍼 재-export (중복 정의가 아니라 참조). L5 는 첨부 업로드/서빙·이미지 참조 저장·아카이브
# 스윕·파일 관찰 래퍼를 정의하고, 그것이 재사용하는 L4(잠금·저장·휴지통·retention)·L3(문서·엔진)·
# L2(워크스페이스·설정)·L1(계정) 헬퍼를 재-export 한다.
from tests.integration_L5 import helpers as l5_helpers

# 무효화 스윕 접근·share_link 관찰 핸들 타입(래퍼가 받는 얇은 위임 대상, 아래 참조).
from tests.integration_L6.conftest import (
    ShareInvalidationSweepAccess,
    ShareLinkObservation,
)

l4_helpers = l5_helpers.l4_helpers
l3_helpers = l5_helpers.l3_helpers
l2_helpers = l5_helpers.l2_helpers
l1_helpers = l5_helpers.l1_helpers

__all__ = [
    # (재사용) L5/L4/L3/L2/L1 헬퍼 재-export — 첨부·잠금·저장·휴지통·문서·엔진·워크스페이스·계정
    "l5_helpers",
    "l4_helpers",
    "l3_helpers",
    "l2_helpers",
    "l1_helpers",
    # (A) 공유 발급·토글 래퍼
    "attempt_issue_share",
    "issue_share",
    "attempt_toggle_share",
    "toggle_share",
    # (B) 공개 접근 래퍼(익명 클라이언트) + 트리-워크
    "attempt_public_render",
    "public_render",
    "attempt_public_attachment",
    "public_attachment",
    "collect_node_ids",
    "find_node",
    # (C) 게이트 토글 래퍼(s05 설정 라우트 재사용)
    "set_gate",
    # (D) 무효화 스윕 래퍼(핸들 위임)
    "run_invalidation_sweep",
    # (E) share_link 관찰 래퍼(핸들 위임)
    "share_token",
    "share_is_enabled",
    "share_row_exists",
    "token_resolves",
]


# =============================================================================
# (A) 공유 발급·토글 래퍼 — 실제 s14 라우트 호출(부팅 앱, editor 게이트)
# =============================================================================


def attempt_issue_share(client: TestClient, document_id: int) -> Response:
    """``POST /documents/{id}/share`` 발급/재발급을 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — EDITOR+ 는 200 ``ShareLinkRead``(항상 새 토큰; 발급==재발급 동일 호출),
    viewer/비멤버 403, 미인증 401, 미존재 문서 404(문서→WS 어댑터), 게이트 off·비active 문서
    409 를 스위트가 각각 단언한다. 문서당 링크 최대 1개라 발급/재발급을 upsert 로 통일해 200 을
    쓴다(순수 create 가 아님). 상태는 호출자가 단언한다(성공·게이팅 음성 경로를 같은 래퍼로 관찰).
    """
    return client.post(f"/documents/{document_id}/share")


def issue_share(client: TestClient, document_id: int) -> dict:
    """editor 세션으로 공유 링크를 발급/재발급한다. SETUP — 200 을 단언하고 파싱된 ``ShareLinkRead`` 반환.

    응답 dict 는 ``id``·``created_at``·``updated_at``(=None)·``document_id``·``token``·
    ``is_enabled``·``share_url``(=`/public/{token}`)를 담는다. 발급과 재발급은 **동일 호출**이며
    항상 **새 토큰**을 낸다(INV-8). 재발급 관찰도 이 래퍼를 그대로 쓴다.
    """
    resp = attempt_issue_share(client, document_id)
    assert resp.status_code == 200, (
        f"공유 발급/재발급 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def attempt_toggle_share(
    client: TestClient, document_id: int, *, is_enabled: bool
) -> Response:
    """``PATCH /documents/{id}/share`` 토글을 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — EDITOR+ 는 200 ``ShareLinkRead``(토큰 유지), 비활성→활성 시 게이트 off·비active
    409, 링크 부재 404, viewer/비멤버 403, 미인증 401, 잘못된 바디 422 를 스위트가 각각 단언한다.
    비활성화는 항상 허용, 활성화는 게이트 on·문서 active 일 때만 허용된다(재발급 통일의 유일한
    상태 기반 예외, INV-8 — 토큰 유지). 상태는 호출자가 단언한다.
    """
    return client.patch(
        f"/documents/{document_id}/share", json={"is_enabled": is_enabled}
    )


def toggle_share(client: TestClient, document_id: int, *, is_enabled: bool) -> dict:
    """editor 세션으로 공유 링크 상태를 토글한다. SETUP — 200 을 단언하고 파싱된 ``ShareLinkRead`` 반환.

    토글은 **토큰을 유지**한다(발급/재발급이 새 토큰을 내는 것과 대비되는 유일한 예외, INV-8).
    반환 dict 의 ``is_enabled`` 는 요청한 값을, ``token`` 은 이전 토큰을 그대로 담는다.
    """
    resp = attempt_toggle_share(client, document_id, is_enabled=is_enabled)
    assert resp.status_code == 200, (
        f"공유 토글 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


# =============================================================================
# (B) 공개 접근 래퍼 — 익명 클라이언트로 실제 s14 공개 라우트 호출 + 트리-워크
# =============================================================================


def attempt_public_render(client: TestClient, token: str) -> Response:
    """``GET /public/{token}`` 공개 렌더를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — 익명 클라이언트로 호출한다(인증·권한 게이트 없음, 공개). 유효 토큰·게이트 on·
    active 문서는 200 ``PublicDocumentRead``, 무효·미존재 토큰·문서 trashed/deleted·게이트 off·
    범위 밖은 사유 구분 없이 모두 **404** 로 통일된다(존재 추정 차단, INV-8). 상태는 호출자가
    단언한다(성공·404 통일을 같은 래퍼로 관찰).
    """
    return client.get(f"/public/{token}")


def public_render(client: TestClient, token: str) -> dict:
    """익명 세션으로 공개 문서 트리를 렌더한다. SETUP — 200 을 단언하고 파싱된 ``PublicDocumentRead`` 반환.

    반환 dict 는 ``root``(id·title·content_html·children)를 담는 읽기 전용 중첩 트리다.
    ``children`` 은 접근 시점의 현재 active 하위(동적)이므로, 트리-워크 헬퍼
    (:func:`collect_node_ids`/:func:`find_node`)로 동적 하위 포함/제외를 단언한다.
    """
    resp = attempt_public_render(client, token)
    assert resp.status_code == 200, (
        f"공개 렌더 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def attempt_public_attachment(
    client: TestClient, token: str, attachment_id: int
) -> Response:
    """``GET /public/{token}/attachments/{aid}`` 링크 경유 첨부 서빙을 태우고 **응답을 그대로 반환**한다.

    ATTEMPT 헬퍼 — 익명 클라이언트로 호출한다(인증·권한 게이트 없음, 공개). 공개 렌더와 **동일한**
    유효성 게이트(토큰·게이트·문서 status·WS 격리)를 통과하고 문서 트리 범위 안의 미보관 첨부면
    200 + 바이너리 스트림, 범위 밖·다른 WS·보관·부재 첨부는 모두 **404** 로 통일된다(존재 추정
    차단). 상태·``.content``·``.headers['content-type']`` 는 호출자가 관찰한다.
    """
    return client.get(f"/public/{token}/attachments/{attachment_id}")


def public_attachment(
    client: TestClient, token: str, attachment_id: int
) -> Response:
    """익명 세션으로 링크 경유 첨부 바이너리를 서빙한다. SETUP — 200 을 단언하고 :class:`Response` 반환.

    호출자가 ``.content``(바이너리)·``.headers['content-type']`` 를 직접 읽을 수 있도록 파싱하지
    않고 :class:`Response` 를 그대로 돌려준다(L5 `get_attachment` 의 공개 아날로그).
    """
    resp = attempt_public_attachment(client, token, attachment_id)
    assert resp.status_code == 200, (
        f"링크 경유 첨부 서빙 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp


def collect_node_ids(public_document: dict) -> set[int]:
    """공개 렌더 트리(``PublicDocumentRead`` dict)의 모든 노드 id 를 재귀로 수집한다.

    ``root`` 부터 ``children`` 을 깊이 우선으로 순회해 노드 id 집합을 만든다. 동적 하위 포함/제외
    (active 하위만 렌더, trashed/이동 하위 제외)를 스위트가 집합 멤버십으로 단언하게 한다.
    """
    ids: set[int] = set()

    def _walk(node: dict) -> None:
        ids.add(node["id"])
        for child in node.get("children", []):
            _walk(child)

    _walk(public_document["root"])
    return ids


def find_node(public_document: dict, document_id: int) -> dict | None:
    """공개 렌더 트리에서 ``document_id`` 노드를 재귀 탐색해 반환한다(미포함 None).

    동적 하위 포함을 단언할 때 특정 노드의 title·content_html·children 을 함께 관찰하도록 노드
    dict 를 그대로 돌려준다.
    """

    def _walk(node: dict) -> dict | None:
        if node["id"] == document_id:
            return node
        for child in node.get("children", []):
            found = _walk(child)
            if found is not None:
                return found
        return None

    return _walk(public_document["root"])


# =============================================================================
# (C) 게이트 토글 래퍼 — s05 워크스페이스 설정 라우트(L2 `update_settings`) 재사용
# =============================================================================


def set_gate(client: TestClient, workspace_id: int, *, is_shareable: bool) -> dict:
    """워크스페이스 공유 게이트(`is_shareable`)를 연다/닫는다. SETUP — 200 을 단언하고 ``WorkspaceRead`` 반환.

    s14 전용 라우트가 아니라 s05 설정 라우트(L2 `update_settings` = PATCH /workspaces/{id},
    owner/admin 경로)에 `is_shareable` 필드를 실어 게이트를 토글하는 **얇은 래퍼**다(신규 라우트
    불필요). s14 는 게이트 설정을 소유하지 않는다 — 발급 게이트·무효화 스윕이 s05 가 만든
    `workspace.is_shareable` 관측 결과를 소비할 뿐이다. 게이트 off 후 후속 발급은 409, 공개 접근은
    404 로 표면화됨을 스위트가 관찰한다.
    """
    return l5_helpers.l2_helpers.update_settings(
        client, workspace_id, is_shareable=is_shareable
    )


# =============================================================================
# (D) 무효화 스윕 래퍼 — ShareInvalidationSweepAccess 핸들에 위임해 실제 s14 스윕 1회 구동
# =============================================================================


def run_invalidation_sweep(invalidation_sweep: ShareInvalidationSweepAccess) -> int:
    """실제 s14 관측 기반 무효화 스윕을 1회 구동하고 retire 건수(int)를 반환한다(Req 5.1~5.6, INV-8).

    :class:`~tests.integration_L6.conftest.ShareInvalidationSweepAccess` 핸들(부팅 앱과 동일 세션
    팩토리로 실제 :class:`~app.sharing.invalidation.ShareInvalidationSweep` 을 조립)에 위임하는
    **얇은 래퍼**로, 스위트가 무효화 스윕을 균일하게 표현하게 한다(로직 중복·mock 없음). 무효화는
    ``now`` 주입이 아니라 호출 시점의 실제 문서 status·게이트 상태를 관측하므로 이 래퍼는 핸들만
    받는다(L5 `run_archival_sweep` 이 now 를 받는 것과 대비). **세션 바인딩 함정 회피 근거**:
    앱 모듈 전역 `run_invalidation_sweep()` 은 호출 시점에 `app.common.db.SessionLocal`(개발 DB 에
    묶임)로 자기 세션을 열어 테스트 DB 가 아니라 개발 DB 를 친다. 따라서 이 래퍼는 그 엔트리포인트를
    직접 호출하지 않고, 부팅 앱과 **동일 세션 팩토리**(`harness.session_local`)로 스윕을 구동하는
    핸들의 :meth:`sweep` 에 위임한다(세션·커밋 경계 정렬). 반환값은 retire 한 링크 수다.

    **스코프 주의(공개 게이트 lazy retire)**: `list_enabled_invalidatable` 은 `is_enabled=True`
    링크만 대상으로 하므로, 무효 문서에 공개 접근(`_resolve_valid_link`)이 먼저 일어나 그 링크가
    lazy retire 되었다면 이 스윕은 그 링크를 스코프에서 제외한다(멱등). 즉 「retire 건수 > 0」은
    아직 공개 접근이 무효화하지 않은 활성 링크가 있을 때만 관측된다(스위트가 이 순서를 통제).
    """
    return invalidation_sweep.sweep()


# =============================================================================
# (E) share_link 관찰 래퍼 — ShareLinkObservation 핸들에 위임(token·is_enabled·물리 존재)
# =============================================================================


def share_token(
    share_link_observation: ShareLinkObservation, document_id: int
) -> str | None:
    """문서의 현재 share_link 토큰을 DB 로 관측한다(미존재 None). retire·재발급이 이 값을 교체한다(INV-8).

    :class:`~tests.integration_L6.conftest.ShareLinkObservation` 핸들(부팅 앱과 동일 세션 팩토리)에
    위임하는 얇은 래퍼로, 응답이 노출하지 않는 내부 상태를 DB 로 관측한다(L5 `attachment_file_path`
    관찰 패턴의 s14 아날로그).
    """
    return share_link_observation.token_of(document_id)


def share_is_enabled(
    share_link_observation: ShareLinkObservation, document_id: int
) -> bool | None:
    """문서의 현재 share_link `is_enabled` 를 DB 로 관측한다(미존재 None). retire 는 False 로 만든다."""
    return share_link_observation.is_enabled_of(document_id)


def share_row_exists(
    share_link_observation: ShareLinkObservation, document_id: int
) -> bool:
    """문서의 share_link 행이 물리적으로 존재하는지 관측한다(retire 후에도 True, INV-4 물리 삭제 부재)."""
    return share_link_observation.row_exists(document_id)


def token_resolves(
    share_link_observation: ShareLinkObservation, token: str
) -> bool:
    """토큰이 현재 share_link 행으로 해석되는지 관측한다(retire 로 교체된 이전 토큰은 False).

    `ShareLinkRepository.get_by_token` 소비 — retire 가 토큰을 교체하면 이전 토큰은 더 이상 어떤
    행으로도 해석되지 않아 False, 교체된 새 토큰은 True 다(INV-8 토큰 교체 관찰).
    """
    return share_link_observation.by_token(token) is not None
