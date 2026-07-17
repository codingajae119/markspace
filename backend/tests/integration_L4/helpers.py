"""L4 잠금·버전·휴지통·스윕 시나리오 헬퍼 — 실제 라우트·실제 스윕 호출의 얇은 래퍼
(Task 1.2 / Req 1.4, 3.1, 4.1, 6.1, design §Helpers).

후속 스위트(계약 대조 2.1 · 잠금·버전 흐름 2.2 · 휴지통 흐름 2.3 · 잠금↔삭제 독립 2.4 · 보관
타이머 독립성 2.5 · 아래 계층 결합 엣지 2.6)가 잠금→저장→버전, 삭제→휴지통→복구/완전삭제,
보관 만료 스윕 같은 cross-spec 시나리오를 간결하게 표현하도록, s09 잠금·버전 라우트(s01 카탈로그
행 24~28)·s10 휴지통 라우트(행 29~31)의 **실제** 엔드포인트와 s10 `RetentionSweepService` 의
**실제** 스윕을 감싸는 얇은 래퍼를 모은다. mock 이 아니라 부팅된 앱(`app.main.create_app`, s09·
s10 라우터 조립)의 실 라우트와, 부팅 앱과 동일 세션 팩토리로 조립된 실제 스윕 서비스를 태운다.

## 설계 규칙 (음성 경로 가능성 보존 — L3/L2/L1 helpers.py 관용 답습)
- **attempt 계열** (:func:`attempt_lock`·:func:`attempt_save`·:func:`attempt_cancel`·
  :func:`attempt_force_unlock`·:func:`attempt_list_versions`·:func:`attempt_list_trash`·
  :func:`attempt_restore_bundle`·:func:`attempt_purge_bundle`): 후속 스위트가 같은 래퍼로
  성공(2xx)과 실패(401/403/404/409/422)를 **둘 다** 단언해야 하므로 **응답 객체를 그대로
  반환하고 상태를 내부에서 단언하지 않는다**. 각 스위트가 원시 URL·바디를 중복하지 않고
  role별 통과·거부·타인 잠금 409·admin bypass·어댑터 404 를 관찰한다.
- **setup 계열** (:func:`lock`·:func:`save`·:func:`cancel`·:func:`force_unlock`·
  :func:`list_versions`·:func:`list_trash`·:func:`restore_bundle_via_api`·
  :func:`purge_bundle_via_api`): 시나리오 준비상 항상 성공하는 단계이므로 성공 상태를
  내부에서 단언하고 유용한 값(파싱된 body dict / None)을 돌려주어 시나리오 코드를 읽기
  쉽게 한다. 내부적으로 대응하는 attempt 래퍼를 재사용한다(URL·바디 단일 정의).

## 명명 규칙 — 재-export 한 L3 엔진 primitive 와의 충돌 회피
`l3_helpers` 는 엔진 primitive 래퍼로 이미 :func:`~tests.integration_L3.helpers.restore_bundle`·
:func:`~tests.integration_L3.helpers.purge_bundle` 를 정의한다(엔진 직접 호출, 스냅샷 반환).
이 모듈의 **휴지통 라우트** 복구/완전삭제 래퍼는 이름 충돌·혼동을 피하려 setup 형에
``_via_api`` 접미사를 붙인다(:func:`restore_bundle_via_api`·:func:`purge_bundle_via_api`).
attempt 형(:func:`attempt_restore_bundle`·:func:`attempt_purge_bundle`)은 ``attempt_`` 접두사
자체가 엔진 primitive(접두사 없음)와 구별되므로 그대로 둔다. 따라서 스위트는 엔진 경로
(``l3_helpers.restore_bundle``)와 API 경로(``restore_bundle_via_api``)를 이름으로 명확히
구분한다.

## L3/L2/L1 헬퍼 재사용 (중복 정의 금지)
문서 생성·하위 문서·이동·삭제·조회 라우트 래퍼와 엔진 primitive(`identify_bundles`·
`get_bundle`·`restore_bundle`·`purge_bundle`·`active_descendants`·`DocumentSnapshot`·
`BundleSnapshot`), 그리고 그것이 재사용하는 워크스페이스 생성·멤버 추가(role)·role 변경·
소유권·설정 헬퍼(L2)·계정 생성·로그인·상태 전이 헬퍼(L1)는 `s08` L3 `helpers.py`(및 그것이
재-export 하는 L2/L1)를 **그대로** 쓴다(재정의하지 않는다). 이 모듈은 L3 helpers 를 참조로
재-export 하므로 스위트가 한 지점(``tests.integration_L4.helpers``)에서 잠금·버전·휴지통·스윕
래퍼는 물론 문서·엔진·워크스페이스·계정 헬퍼까지 모두 도달한다(중복 **정의**가 아닌 참조).

잠금·버전 엔드포인트 계약 (s01 단일 소스, 카탈로그 행 24~28):
- ``POST /documents/{id}/lock`` (EDITOR) → 200 ``DocumentLockRead`` / 타인 잠금 409
- ``POST /documents/{id}/save`` body ``{"content": <str, "" 허용>}`` (EDITOR) → 200
  ``DocumentVersionRead`` / 비보유자 409 / content 누락·형식 422
- ``POST /documents/{id}/cancel`` (EDITOR) → 204 (미잠금 멱등 no-op·타인 잠금 409)
- ``POST /documents/{id}/force-unlock`` (OWNER) → 204 (editor 403·미잠금 멱등)
- ``GET /documents/{id}/versions?limit&offset`` (VIEWER) → 200 ``Page[DocumentVersionRead]``

휴지통 엔드포인트 계약 (s01 단일 소스, 카탈로그 행 29~31):
- ``GET /workspaces/{id}/trash?limit&offset`` (EDITOR) → 200 ``Page[TrashBundleRead]``
- ``POST /trash/{bundleId}/restore`` (EDITOR) → 204 / 유효하지 않은 묶음 404
- ``DELETE /trash/{bundleId}`` (EDITOR) → 204 / 유효하지 않은 묶음 404 (**비가역** 완전삭제)
"""

from datetime import datetime

from fastapi.testclient import TestClient
from httpx import Response

# L3 헬퍼 재-export (중복 정의가 아니라 참조). L3 는 문서 라우트 래퍼·엔진 primitive 래퍼·
# 스냅샷을 정의하고, 그것이 재사용하는 L2(워크스페이스)·L1(계정) 헬퍼를 재-export 한다.
from tests.integration_L3 import helpers as l3_helpers

# 스윕 접근 핸들 타입(스윕 래퍼가 받는 얇은 위임 대상, 아래 참조).
from tests.integration_L4.conftest import SweepAccess

l2_helpers = l3_helpers.l2_helpers
l1_helpers = l3_helpers.l1_helpers

__all__ = [
    # (재사용) L3/L2/L1 헬퍼 재-export — 문서 라우트·엔진 primitive·워크스페이스·계정
    "l3_helpers",
    "l2_helpers",
    "l1_helpers",
    # (A) 잠금·버전 라우트 래퍼
    "attempt_lock",
    "lock",
    "attempt_save",
    "save",
    "attempt_cancel",
    "cancel",
    "attempt_force_unlock",
    "force_unlock",
    "attempt_list_versions",
    "list_versions",
    # (B) 휴지통 라우트 래퍼 (엔진 primitive 와 충돌 회피 — setup 형은 _via_api)
    "attempt_list_trash",
    "list_trash",
    "attempt_restore_bundle",
    "restore_bundle_via_api",
    "attempt_purge_bundle",
    "purge_bundle_via_api",
    # (C) 스윕 래퍼
    "run_sweep",
]


# =============================================================================
# (A) 잠금·버전 라우트 래퍼 — 실제 s09 라우트 호출(부팅 앱)
# =============================================================================


def attempt_lock(client: TestClient, document_id: int) -> Response:
    """``POST /documents/{id}/lock`` 을 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — EDITOR+ 는 200 ``DocumentLockRead``, 타인 잠금 문서는 409("편집 중"),
    viewer/비멤버 403, 미인증 401, 미존재 문서 404(문서→WS 어댑터)를 스위트가 각각 단언한다.
    ``client`` 는 호출자의 role 세션(인증된 :class:`TestClient`).
    """
    return client.post(f"/documents/{document_id}/lock")


def lock(client: TestClient, document_id: int) -> dict:
    """editor 세션으로 편집 잠금을 획득한다. SETUP — 200 을 단언하고 파싱된 ``DocumentLockRead`` 반환."""
    resp = attempt_lock(client, document_id)
    assert resp.status_code == 200, (
        f"잠금 시작 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def attempt_save(client: TestClient, document_id: int, content: str) -> Response:
    """``POST /documents/{id}/save`` 를 body ``{"content": ...}`` 로 태우고 **응답을 그대로 반환**한다.

    ATTEMPT 헬퍼 — 잠금 보유자는 200 ``DocumentVersionRead``(새 버전·current 갱신·잠금 해제),
    비보유자/타인 잠금 409, ``content`` 누락·형식 오류 422, viewer/비멤버 403, 미존재 404 를
    스위트가 각각 단언한다. ``content`` 는 빈 문자열(``""``)도 허용된다.
    """
    return client.post(f"/documents/{document_id}/save", json={"content": content})


def save(client: TestClient, document_id: int, content: str) -> dict:
    """잠금 보유자 세션으로 본문을 저장한다. SETUP — 200 을 단언하고 파싱된 ``DocumentVersionRead`` 반환."""
    resp = attempt_save(client, document_id, content)
    assert resp.status_code == 200, (
        f"저장 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def attempt_cancel(client: TestClient, document_id: int) -> Response:
    """``POST /documents/{id}/cancel`` 을 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — 잠금 보유자는 204(잠금 해제·변경분 폐기·새 버전 미생성), 미잠금은 멱등
    204 no-op, 타인 잠금 409, viewer/비멤버 403, 미존재 404 를 스위트가 각각 단언한다.
    """
    return client.post(f"/documents/{document_id}/cancel")


def cancel(client: TestClient, document_id: int) -> None:
    """잠금 보유자 세션으로 편집을 취소한다. SETUP — 204 를 단언한다(반환값 없음)."""
    resp = attempt_cancel(client, document_id)
    assert resp.status_code == 204, (
        f"편집 취소 204 이어야 한다: {resp.status_code} {resp.text}"
    )


def attempt_force_unlock(client: TestClient, document_id: int) -> Response:
    """``POST /documents/{id}/force-unlock`` 을 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — OWNER+ 는 204(보유자 무관 강제 해제·새 버전 미생성·미잠금 멱등), 비 owner
    editor 403, viewer/비멤버 403, 미인증 401, 미존재 404 를 스위트가 각각 단언한다.
    """
    return client.post(f"/documents/{document_id}/force-unlock")


def force_unlock(client: TestClient, document_id: int) -> None:
    """owner 세션으로 잠금을 강제 해제한다. SETUP — 204 를 단언한다(반환값 없음)."""
    resp = attempt_force_unlock(client, document_id)
    assert resp.status_code == 204, (
        f"강제 해제 204 이어야 한다: {resp.status_code} {resp.text}"
    )


def attempt_list_versions(
    client: TestClient,
    document_id: int,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> Response:
    """``GET /documents/{id}/versions`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — VIEWER+ 는 200 ``Page[DocumentVersionRead]``(최신 저장순 메타데이터, 본문
    없음), 비멤버 403, 미존재 404 를 스위트가 각각 단언한다. ``limit``/``offset`` 은 지정
    시에만 쿼리 파라미터로 실린다(미지정 시 라우터 기본값 limit=50·offset=0 사용).
    """
    params: dict[str, int] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    return client.get(f"/documents/{document_id}/versions", params=params)


def list_versions(
    client: TestClient,
    document_id: int,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    """viewer+ 세션으로 버전 목록을 조회한다. SETUP — 200 을 단언하고 ``Page`` dict(``{items, total}``) 반환."""
    resp = attempt_list_versions(client, document_id, limit=limit, offset=offset)
    assert resp.status_code == 200, (
        f"버전 목록 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


# =============================================================================
# (B) 휴지통 라우트 래퍼 — 실제 s10 라우트 호출(부팅 앱)
# =============================================================================


def attempt_list_trash(
    client: TestClient,
    workspace_id: int,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> Response:
    """``GET /workspaces/{id}/trash`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — EDITOR+ 는 200 ``Page[TrashBundleRead]``(묶음 루트·구성원 요약·trashed_at·
    expires_at), viewer/비멤버 403, admin bypass, 미인증 401 을 스위트가 각각 단언한다.
    ``limit``/``offset`` 은 지정 시에만 쿼리 파라미터로 실린다(미지정 시 라우터 기본값 사용).
    """
    params: dict[str, int] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    return client.get(f"/workspaces/{workspace_id}/trash", params=params)


def list_trash(
    client: TestClient,
    workspace_id: int,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    """editor+ 세션으로 휴지통 목록을 조회한다. SETUP — 200 을 단언하고 ``Page`` dict(``{items, total}``) 반환."""
    resp = attempt_list_trash(client, workspace_id, limit=limit, offset=offset)
    assert resp.status_code == 200, (
        f"휴지통 목록 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def attempt_restore_bundle(client: TestClient, bundle_id: int) -> Response:
    """``POST /trash/{bundleId}/restore`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — EDITOR+ 는 204(묶음 전체 active 복구), viewer/비멤버 403, admin bypass,
    유효하지 않은 묶음 루트 404(묶음→WS 어댑터/서비스)를 스위트가 각각 단언한다. 엔진 primitive
    래퍼 ``l3_helpers.restore_bundle`` 와 달리 **실제 s10 API** 를 태운다(명명 규칙 참조).
    """
    return client.post(f"/trash/{bundle_id}/restore")


def restore_bundle_via_api(client: TestClient, bundle_id: int) -> None:
    """editor+ 세션으로 휴지통 묶음을 복구한다(실제 API). SETUP — 204 를 단언한다(반환값 없음).

    엔진 primitive 를 직접 부르는 ``l3_helpers.restore_bundle`` 와 구별하려 ``_via_api`` 접미사를
    쓴다(모듈 docstring 명명 규칙).
    """
    resp = attempt_restore_bundle(client, bundle_id)
    assert resp.status_code == 204, (
        f"휴지통 복구 204 이어야 한다: {resp.status_code} {resp.text}"
    )


def attempt_purge_bundle(client: TestClient, bundle_id: int) -> Response:
    """``DELETE /trash/{bundleId}`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — EDITOR+ 는 204(묶음 전체 deleted 종착·**비가역**), viewer/비멤버 403, admin
    bypass, 유효하지 않은 묶음 루트 404 를 스위트가 각각 단언한다. 엔진 primitive 래퍼
    ``l3_helpers.purge_bundle`` 와 달리 **실제 s10 API** 를 태운다(명명 규칙 참조).
    """
    return client.delete(f"/trash/{bundle_id}")


def purge_bundle_via_api(client: TestClient, bundle_id: int) -> None:
    """editor+ 세션으로 휴지통 묶음을 완전삭제한다(실제 API, **비가역**). SETUP — 204 를 단언한다.

    엔진 primitive 를 직접 부르는 ``l3_helpers.purge_bundle`` 와 구별하려 ``_via_api`` 접미사를
    쓴다(모듈 docstring 명명 규칙).
    """
    resp = attempt_purge_bundle(client, bundle_id)
    assert resp.status_code == 204, (
        f"휴지통 완전삭제 204 이어야 한다: {resp.status_code} {resp.text}"
    )


# =============================================================================
# (C) 스윕 래퍼 — SweepAccess 핸들에 now 를 주입해 실제 s10 스윕 1회 구동
# =============================================================================


def run_sweep(sweep_access: SweepAccess, now: datetime) -> int:
    """주입된 ``now`` 로 실제 s10 보관 만료 스윕을 1회 구동하고 전환한 묶음 수를 반환한다.

    :class:`~tests.integration_L4.conftest.SweepAccess` 핸들(부팅 앱과 동일 세션 팩토리로
    실제 :class:`~app.trash.retention.RetentionSweepService` 를 조립)에 위임하는 **얇은 래퍼**로,
    스위트가 ``now`` 주입 스윕을 균일하게 표현하게 한다(로직 중복·mock 없음 — 세션 수명·커밋은
    핸들이 소유). 반환값은 ``sweep_expired_bundles(db, now)`` 가 전환한 묶음 수(int)다. 스윕
    결과의 DB 관찰은 ``sweep_access.status_of(document_id)`` 로 한다.
    """
    return sweep_access.sweep(now)
