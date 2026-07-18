"""L6 하네스 스모크 (Task 1.1 / Req 1.1·1.2·1.3·1.4·1.6, design §L6TestHarness 관찰 가능 완료).

L6 통합 하네스(`conftest.py`)가 실제 전체 결합 환경을 제공하는지 RED→GREEN 으로 증명한다.
mock 없이 마이그레이션된 DB + 부팅 앱(s14 공유 라우터 + 무효화 스케줄러 조립) + admin 시드 +
role별/익명 공개 세션 클라이언트 위에서:

- editor 가 게이트 on 의 active 문서에 `POST /documents/{id}/share` 발급 → 200 `ShareLinkRead`
  (활성 토큰) 을 받고,
- 비인증 `public_client` 가 `GET /public/{token}` → 200 `PublicDocumentRead{root}` 를 받으며,
- 무효화 스윕 접근 픽스처의 `sweep()` 이 int 를 반환(문서를 trashed 로 만든 뒤 retire 건수가
  DB 상태를 반영) 하고,
- share_link 관찰 픽스처가 토큰·`is_enabled` 를 읽으며 retire 후에도 행이 물리 삭제되지 않고
  (INV-4) 남아 있음(토큰 교체 + 비활성)

을 관찰한다. 이 스모크가 통과하면 L6 하네스가 후속 스위트(2.x)의 결합 환경을 제공한다.
"""

from fastapi.testclient import TestClient


def test_share_scenario_issues_active_link_on_gated_active_document(share_scenario):
    """게이트 on active 문서에 editor 발급 → 200 `ShareLinkRead`(활성 토큰) 이 준비돼 있다."""
    link = share_scenario.share_link
    # ShareLinkRead 규약: TimestampedRead(id·created_at·updated_at=None) + document_id·token·
    # is_enabled·share_url(=/public/{token}).
    assert link["document_id"] == share_scenario.document_id
    assert link["is_enabled"] is True
    assert isinstance(link["token"], str) and link["token"]
    assert link["share_url"] == f"/public/{link['token']}"
    assert link["updated_at"] is None
    # 시나리오 편의 접근이 발급 응답 토큰과 일치한다.
    assert share_scenario.token == link["token"]


def test_public_client_is_anonymous_and_renders_shared_document(share_scenario):
    """비인증 `public_client` 가 `GET /public/{token}` → 200 `PublicDocumentRead{root}` 를 받는다."""
    public = share_scenario.public_client
    assert isinstance(public, TestClient)
    # 인증 세션과 독립된 익명 쿠키 자(세션 쿠키 부재).
    assert share_scenario.harness.session_cookie_name not in public.cookies

    resp = public.get(f"/public/{share_scenario.token}")
    assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
    body = resp.json()
    root = body["root"]
    # 최소 노출 노드: id·title·content_html·children (내부 필드 비노출).
    assert root["id"] == share_scenario.document_id
    assert "title" in root and "content_html" in root
    assert isinstance(root["children"], list)
    assert "workspace_id" not in root


def test_invalidation_sweep_returns_int_and_retires_on_trashed_document(
    share_scenario, invalidation_sweep, share_link_observation
):
    """무효화 스윕이 int 를 반환하고, 문서를 trashed 로 만든 뒤 활성 링크를 retire 한다.

    스윕이 retire 를 수행함을 관찰하려면 그 전에 공개 접근(실시간 게이트의 lazy retire)이 일어나지
    않아야 한다 — lazy retire 는 활성 링크를 먼저 비활성화해 스윕 스코프(`is_enabled=True`)에서
    제외하기 때문이다(별도 테스트에서 관찰). 여기서는 공개 접근 없이 스윕이 retire 하는 경로를 본다.
    """
    doc_id = share_scenario.document_id

    # 무효 조건이 없을 때(문서 active·게이트 on) 스윕은 정수(0 이상)를 반환한다 — mock 아님.
    baseline = invalidation_sweep.sweep()
    assert isinstance(baseline, int)
    assert baseline == 0

    token_before = share_link_observation.token_of(doc_id)
    assert share_link_observation.is_enabled_of(doc_id) is True

    # 실제 s10 삭제 라우트로 문서를 trashed 로 전이(관측 기반 무효화 유발).
    resp = share_scenario.editor_client.delete(f"/documents/{doc_id}")
    assert resp.status_code in (200, 204), f"{resp.status_code} {resp.text}"

    # 공개 접근 없이 무효화 스윕이 활성 링크를 retire(비활성 + 토큰 교체) → retire 건수 1 이상.
    retired = invalidation_sweep.sweep()
    assert isinstance(retired, int)
    assert retired >= 1

    # DB 관찰: is_enabled=False + 토큰 교체, 그러나 행은 물리 삭제되지 않음(INV-4).
    assert share_link_observation.is_enabled_of(doc_id) is False
    assert share_link_observation.token_of(doc_id) != token_before
    assert share_link_observation.row_exists(doc_id) is True

    # 교체된(무효화된) 이전 토큰으로의 공개 접근은 404(재발급 없이 되살아나지 않음, INV-8).
    gone = share_scenario.public_client.get(f"/public/{token_before}")
    assert gone.status_code == 404


def test_realtime_public_gate_lazy_retires_on_trashed_document(
    share_scenario, invalidation_sweep, share_link_observation
):
    """비인증 공개 접근이 trashed 문서를 실시간 게이트로 404 처리하며 그 자리에서 lazy retire 한다.

    실시간 게이트(스윕 이전에도 즉시 차단)와 lazy retire(is_enabled=False + 토큰 교체, 물리 삭제
    부재)를 익명 `public_client` + share_link 관찰 픽스처로 확인한다. 이후 스윕은 이미 비활성 링크를
    스코프에서 제외해 0 을 반환(멱등)한다.
    """
    doc_id = share_scenario.document_id
    token_before = share_scenario.token

    share_scenario.editor_client.delete(f"/documents/{doc_id}")

    # 실시간 게이트: 스윕 이전에도 즉시 404(정보 비노출).
    gated = share_scenario.public_client.get(f"/public/{token_before}")
    assert gated.status_code == 404

    # lazy retire: 활성 링크가 그 자리에서 비활성 + 토큰 교체되었으나 행은 남는다(INV-4).
    assert share_link_observation.is_enabled_of(doc_id) is False
    assert share_link_observation.token_of(doc_id) != token_before
    assert share_link_observation.row_exists(doc_id) is True

    # 이미 lazy retire 된 링크는 후속 스윕 스코프에서 제외된다(멱등).
    assert invalidation_sweep.sweep() == 0


def test_invalidation_sweep_is_idempotent(share_scenario, invalidation_sweep):
    """이미 무효화된 링크는 재실행 시 건너뛰어(멱등) retire 건수 0 을 반환한다."""
    doc_id = share_scenario.document_id
    share_scenario.editor_client.delete(f"/documents/{doc_id}")
    first = invalidation_sweep.sweep()
    assert first >= 1
    # 두 번째 스윕은 이미 비활성 링크를 스코프에서 제외한다(멱등, Req 5.6).
    second = invalidation_sweep.sweep()
    assert second == 0


def test_share_link_observation_reads_token_and_enabled_by_document_and_token(
    share_scenario, share_link_observation
):
    """share_link 관찰 픽스처가 문서/토큰 기준으로 token·is_enabled 를 읽고 행 존재를 확인한다."""
    doc_id = share_scenario.document_id
    token = share_scenario.token

    assert share_link_observation.token_of(doc_id) == token
    assert share_link_observation.is_enabled_of(doc_id) is True
    assert share_link_observation.row_exists(doc_id) is True

    # 토큰 기준 조회도 같은 행(문서 id 일치)을 가리킨다.
    by_token = share_link_observation.by_token(token)
    assert by_token is not None
    assert by_token.document_id == doc_id
    assert by_token.is_enabled is True
