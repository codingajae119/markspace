"""L3 문서·엔진 시나리오 헬퍼 — 실제 라우트·실제 엔진 호출의 얇은 래퍼 (Task 1.2 / Req 1.4, 3.1).

후속 스위트(권한 게이팅 2.2 · 계층 이동 2.3 · bundle 삭제 캐스케이드 2.4 · 복구/완전삭제 2.5 ·
결합 엣지케이스 2.6)가 문서 생성→하위문서→이동→삭제→묶음 관찰 같은 cross-spec 시나리오를
간결하게 표현하도록, s07 문서 라우트(s01 카탈로그 행 18~23)의 **실제** 엔드포인트와 s07
`DocumentStateEngine` 의 **실제** primitive 를 감싸는 얇은 래퍼를 모은다. mock 이 아니라 부팅된
앱(`app.main.create_app`, s07 라우터 조립)의 실 라우트와, 부팅 앱과 동일 세션 팩토리로 인스턴스화된
실제 엔진을 태운다(design §Helpers).

## 설계 규칙 (음성 경로 가능성 보존 — L2/L1 helpers.py 관용 반영)
- **attempt 계열** (:func:`attempt_create_document`·:func:`attempt_get_document`·
  :func:`attempt_list_documents`·:func:`attempt_patch_title`·:func:`attempt_move_document`·
  :func:`attempt_delete_document`): 후속 스위트가 같은 래퍼로 성공(2xx)과 실패
  (401/403/404/409/422)를 **둘 다** 단언해야 하므로 **응답 객체를 그대로 반환하고 상태를
  내부에서 단언하지 않는다**. 각 스위트가 원시 URL·바디를 중복하지 않고 role별 통과·거부·admin
  bypass·어댑터 404 를 관찰한다.
- **setup 계열** (:func:`create_document`·:func:`get_document`·:func:`list_documents`·
  :func:`patch_title`·:func:`move_document`·:func:`delete_document`): 시나리오 준비상 항상 성공
  하는 단계이므로 성공 상태를 내부에서 단언하고 유용한 값(파싱된 ``DocumentRead`` dict / 생성
  id / ``Page`` dict / None)을 돌려주어 시나리오 코드를 읽기 쉽게 한다. 내부적으로 대응하는
  attempt 래퍼를 재사용한다(URL·바디 단일 정의).

## 엔진 primitive 래퍼 — DetachedInstanceError 회피 설계
엔진 primitive(`identify_bundles`·`get_bundle`·`restore_bundle`·`purge_bundle`·
`active_descendants`)는 `db: Session` 을 첫 인자로 받고 ORM `Document`/`Bundle` 을 돌려준다. 이
래퍼들은 :class:`~tests.integration_L3.conftest.DocumentEngineAccess` 핸들을 받아
``engine_access.session()`` 으로 **호출마다 새 세션**을 열어 API 가 커밋한 최신 행을 신선하게
관찰한다(conftest 모듈 docstring 세션 수명 설계 참조).

세션이 닫히면 ORM 객체는 detached 되어 이후 속성 접근이 :class:`DetachedInstanceError` 를 낼 수
있으므로(특히 지연 로드 대상), 이 래퍼들은 ORM 객체를 그대로 반환하지 않고 **세션이 살아 있는
동안** 필요한 스칼라 필드를 :class:`DocumentSnapshot`(그리고 묶음은 :class:`BundleSnapshot`)로
스냅샷한 뒤 반환한다. 스위트(2.4/2.5/2.6)가 비교하는 것 — 구성원 집합(``member_ids``)·
``trashed_at`` 동치·``status``·``parent_id``·``sort_order``·``lock_user_id`` — 을 모두 스냅샷이
담으므로, detached ORM 객체를 만지지 않고도 단언할 수 있다.

## L2/L1 헬퍼 재사용 (중복 정의 금지)
워크스페이스 생성·멤버 추가(role)·role 변경·소유권 변경·설정 갱신 헬퍼는 `s06` L2
`helpers.py` 를, 계정 생성·로그인·상태 전이(비활동/삭제) 헬퍼는 그것이 재사용하는 `s04` L1
`helpers.py` 를 **그대로** 쓴다(재정의하지 않는다). 이 모듈은 L2 helpers 가 L1 을 재-export 하듯
:data:`l2_helpers`·:data:`l1_helpers` 를 참조로 재-export 한다(중복 **정의**가 아닌 참조). role별
세션 클라이언트·워크스페이스·문서 트리 셋업 픽스처는 L3 conftest 가 제공한다.

문서 엔드포인트 계약 (s01 단일 소스, 카탈로그 행 18~23):
- ``POST /workspaces/{id}/documents`` body ``{"title", "parent_id"?}`` (EDITOR) → 201 ``DocumentRead``
- ``GET /workspaces/{id}/documents`` (VIEWER) → 200 ``Page[DocumentRead]`` (``limit``/``offset`` 쿼리)
- ``GET /documents/{id}`` (VIEWER, 문서→WS 어댑터) → 200 ``DocumentRead`` / 미존재 404
- ``PATCH /documents/{id}`` body ``{"title"}`` (EDITOR) → 200 ``DocumentRead``
- ``POST /documents/{id}/move`` body ``{new_parent_id?, before_sibling_id?, after_sibling_id?}``
  (EDITOR) → 200 ``DocumentRead`` / 순환·타 WS·비active 부모 409 / 잘못된 형제 참조 422
- ``DELETE /documents/{id}`` (EDITOR) → 204 (엔진 `trash_document` 캐스케이드, 비active 409)
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient
from httpx import Response

from app.models import Document

# 엔진 primitive 래퍼가 받는 접근 핸들 타입(스냅샷 반환에만 사용, 아래 참조).
from tests.integration_L3.conftest import DocumentEngineAccess

# L2/L1 헬퍼 재-export (중복 정의가 아니라 참조).
# L2 helpers: 워크스페이스 생성·멤버·role·소유권·설정 래퍼. L1 helpers: 계정·로그인·상태 전이.
from tests.integration_L2 import helpers as l2_helpers

l1_helpers = l2_helpers.l1_helpers

__all__ = [
    "l2_helpers",
    "l1_helpers",
    # (A) 문서 라우트 래퍼
    "attempt_create_document",
    "create_document",
    "attempt_get_document",
    "get_document",
    "attempt_list_documents",
    "list_documents",
    "attempt_patch_title",
    "patch_title",
    "attempt_move_document",
    "move_document",
    "attempt_delete_document",
    "delete_document",
    # (B) 엔진 primitive 래퍼 + detached-safe 스냅샷
    "DocumentSnapshot",
    "BundleSnapshot",
    "identify_bundles",
    "get_bundle",
    "restore_bundle",
    "purge_bundle",
    "active_descendants",
]


# "인자 미제공" 을 값 None(= new_parent_id 의 경우 root 로 이동이라는 유의미한 값)과 구분하기
# 위한 센티널. move 바디는 제공된 키만 실어 보낸다(불필요한 필드로 의도치 않은 root 이동 방지).
_UNSET: Any = object()


# =============================================================================
# (A) 문서 라우트 래퍼 — 실제 s07 라우트 호출(부팅 앱)
# =============================================================================


def attempt_create_document(
    client: TestClient,
    workspace_id: int,
    title: str,
    parent_id: int | None = None,
) -> Response:
    """``POST /workspaces/{id}/documents`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — EDITOR+ 는 201, viewer/비멤버 403, 미인증 401, 빈 제목 422, 미존재/타 WS/
    비active 부모 404·409 를 스위트가 각각 단언한다. ``parent_id`` 를 주면 하위 문서를 만든다.
    ``client`` 는 호출자의 role 세션(인증된 :class:`TestClient`).
    """
    body: dict[str, object] = {"title": title}
    if parent_id is not None:
        body["parent_id"] = parent_id
    return client.post(f"/workspaces/{workspace_id}/documents", json=body)


def create_document(
    client: TestClient,
    workspace_id: int,
    title: str,
    parent_id: int | None = None,
) -> dict:
    """editor 세션으로 문서를 만든다. SETUP — 201 을 단언하고 파싱된 ``DocumentRead`` dict 반환."""
    resp = attempt_create_document(client, workspace_id, title, parent_id)
    assert resp.status_code == 201, (
        f"문서 생성 201 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def attempt_get_document(client: TestClient, document_id: int) -> Response:
    """``GET /documents/{id}`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — VIEWER+ 는 200, 비멤버 403, 미존재 문서 404(문서→WS 어댑터)를 스위트가
    각각 단언한다.
    """
    return client.get(f"/documents/{document_id}")


def get_document(client: TestClient, document_id: int) -> dict:
    """viewer+ 세션으로 문서를 조회한다. SETUP — 200 을 단언하고 파싱된 ``DocumentRead`` 반환."""
    resp = attempt_get_document(client, document_id)
    assert resp.status_code == 200, (
        f"문서 조회 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def attempt_list_documents(
    client: TestClient,
    workspace_id: int,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> Response:
    """``GET /workspaces/{id}/documents`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — VIEWER+ 는 200 ``Page[DocumentRead]``, 비멤버 403 을 스위트가 각각 단언한다.
    ``limit``/``offset`` 은 지정 시에만 쿼리 파라미터로 실린다(미지정 시 라우터 기본값 사용).
    """
    params: dict[str, int] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    return client.get(f"/workspaces/{workspace_id}/documents", params=params)


def list_documents(
    client: TestClient,
    workspace_id: int,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    """viewer+ 세션으로 문서 목록을 조회한다. SETUP — 200 을 단언하고 ``Page`` dict(``{items, total}``) 반환."""
    resp = attempt_list_documents(client, workspace_id, limit=limit, offset=offset)
    assert resp.status_code == 200, (
        f"문서 목록 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def attempt_patch_title(
    client: TestClient, document_id: int, title: str
) -> Response:
    """``PATCH /documents/{id}`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — EDITOR+ 는 200, viewer/비멤버 403, 미존재 404, 빈 제목 422 를 스위트가
    각각 단언한다. 본문 갱신은 title 메타데이터만 다룬다(본문·버전은 s09 소유).
    """
    return client.patch(f"/documents/{document_id}", json={"title": title})


def patch_title(client: TestClient, document_id: int, title: str) -> dict:
    """editor 세션으로 제목을 갱신한다. SETUP — 200 을 단언하고 파싱된 ``DocumentRead`` 반환."""
    resp = attempt_patch_title(client, document_id, title)
    assert resp.status_code == 200, (
        f"문서 제목 갱신 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def attempt_move_document(
    client: TestClient,
    document_id: int,
    *,
    new_parent_id: int | None = _UNSET,
    before_sibling_id: int | None = _UNSET,
    after_sibling_id: int | None = _UNSET,
) -> Response:
    """``POST /documents/{id}/move`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — EDITOR+ 는 200, 순환(자기·후손 밑)·타 WS·비active 부모 409, 잘못된 형제
    참조 422, viewer/비멤버 403, 미존재 문서 404 를 스위트가 각각 단언한다.

    세 필드는 **명시 지정한 것만** 바디에 실린다(센티널 ``_UNSET`` 구분). ``new_parent_id=None``
    을 명시하면 root 로 이동, 미지정이면 부모를 바꾸지 않는 재정렬 의도로 전달한다.
    """
    body: dict[str, object] = {}
    if new_parent_id is not _UNSET:
        body["new_parent_id"] = new_parent_id
    if before_sibling_id is not _UNSET:
        body["before_sibling_id"] = before_sibling_id
    if after_sibling_id is not _UNSET:
        body["after_sibling_id"] = after_sibling_id
    return client.post(f"/documents/{document_id}/move", json=body)


def move_document(
    client: TestClient,
    document_id: int,
    *,
    new_parent_id: int | None = _UNSET,
    before_sibling_id: int | None = _UNSET,
    after_sibling_id: int | None = _UNSET,
) -> dict:
    """editor 세션으로 문서를 이동/재정렬한다. SETUP — 200 을 단언하고 파싱된 ``DocumentRead`` 반환."""
    resp = attempt_move_document(
        client,
        document_id,
        new_parent_id=new_parent_id,
        before_sibling_id=before_sibling_id,
        after_sibling_id=after_sibling_id,
    )
    assert resp.status_code == 200, (
        f"문서 이동 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def attempt_delete_document(client: TestClient, document_id: int) -> Response:
    """``DELETE /documents/{id}`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — EDITOR+ 는 204(엔진 캐스케이드 삭제), 비active 재삭제 409, viewer/비멤버
    403, 미존재 문서 404 를 스위트가 각각 단언한다.
    """
    return client.delete(f"/documents/{document_id}")


def delete_document(client: TestClient, document_id: int) -> None:
    """editor 세션으로 문서를 삭제(trashed 캐스케이드)한다. SETUP — 204 를 단언한다(반환값 없음)."""
    resp = attempt_delete_document(client, document_id)
    assert resp.status_code == 204, (
        f"문서 삭제 204 이어야 한다: {resp.status_code} {resp.text}"
    )


# =============================================================================
# (B) 엔진 primitive 래퍼 — 실제 s07 DocumentStateEngine 직접 호출 + detached-safe 스냅샷
# =============================================================================


@dataclass(frozen=True)
class DocumentSnapshot:
    """세션이 살아 있는 동안 수집한 문서 스칼라 필드의 detached-safe 스냅샷.

    엔진 primitive 가 돌려준 ORM :class:`Document` 를 그대로 반환하면 세션이 닫힌 뒤 속성 접근이
    :class:`DetachedInstanceError` 를 낼 수 있으므로, 스위트가 비교하는 필드만 즉시 복사해 담는다.
    상태(``status``)·복귀 위치(``parent_id``·``sort_order``)·삭제 시각(``trashed_at``)·잠금
    독립 관찰(``lock_user_id``)·소속(``workspace_id``)을 담는다(값 객체, 불변).
    """

    id: int
    workspace_id: int
    parent_id: int | None
    status: str
    sort_order: Decimal
    trashed_at: datetime | None
    lock_user_id: int | None


@dataclass(frozen=True)
class BundleSnapshot:
    """엔진 :class:`~app.document.engine.Bundle` 의 detached-safe 스냅샷.

    ``root_document_id``·``trashed_at`` 와 구성원 스냅샷 리스트를 담는다. ``member_ids`` 편의
    속성으로 스위트가 구성원 집합을 직접 비교(오병합·비흡수·독립 묶음 확인)한다.
    """

    root_document_id: int
    trashed_at: datetime | None
    members: list[DocumentSnapshot]

    @property
    def member_ids(self) -> set[int]:
        """구성원 문서 id 집합(구성원 집합 비교 편의)."""
        return {m.id for m in self.members}


def _snapshot_document(document: Document) -> DocumentSnapshot:
    """세션이 살아 있는 동안 :class:`Document` 스칼라 필드를 스냅샷으로 복사한다."""
    return DocumentSnapshot(
        id=document.id,
        workspace_id=document.workspace_id,
        parent_id=document.parent_id,
        status=document.status,
        sort_order=document.sort_order,
        trashed_at=document.trashed_at,
        lock_user_id=document.lock_user_id,
    )


def _snapshot_bundle(bundle) -> BundleSnapshot:
    """세션이 살아 있는 동안 :class:`Bundle` 을 detached-safe 스냅샷으로 변환한다."""
    return BundleSnapshot(
        root_document_id=bundle.root_document_id,
        trashed_at=bundle.trashed_at,
        members=[_snapshot_document(m) for m in bundle.members],
    )


def identify_bundles(
    engine_access: DocumentEngineAccess, workspace_id: int
) -> list[BundleSnapshot]:
    """실제 엔진 ``identify_bundles`` 를 새 세션으로 호출하고 스냅샷 리스트를 반환한다.

    API 가 커밋한 trashed 행을 신선 관찰한다(새 세션). 휴지통이 비면 빈 리스트다. detached
    안전을 위해 세션 안에서 각 :class:`Bundle` 을 :class:`BundleSnapshot` 으로 즉시 변환한다.
    """
    with engine_access.session() as db:
        bundles = engine_access.engine.identify_bundles(db, workspace_id)
        return [_snapshot_bundle(b) for b in bundles]


def get_bundle(
    engine_access: DocumentEngineAccess, root_document_id: int
) -> BundleSnapshot:
    """실제 엔진 ``get_bundle`` 을 새 세션으로 호출하고 묶음 스냅샷을 반환한다.

    유효하지 않은 루트(미존재·비trashed·비루트 구성원)면 엔진이 :class:`DomainError`(404)를
    raise 하며 이 래퍼는 그대로 전파한다(스위트가 음성 경로를 단언). 유효하면 세션 안에서
    :class:`BundleSnapshot` 으로 변환해 detached 안전하게 반환한다.
    """
    with engine_access.session() as db:
        bundle = engine_access.engine.get_bundle(db, root_document_id)
        return _snapshot_bundle(bundle)


def restore_bundle(
    engine_access: DocumentEngineAccess, root_document_id: int
) -> list[DocumentSnapshot]:
    """실제 엔진 ``restore_bundle`` 을 새 세션으로 호출(변경+커밋)하고 구성원 스냅샷 리스트를 반환한다.

    엔진이 복귀 위치·순서를 결정해 trashed→active 로 되돌린 뒤 단일 커밋한다. 반환은 복구된
    구성원(`list[Document]`)이며, 세션 안에서 각 문서를 :class:`DocumentSnapshot` 으로 변환해
    복귀 위치(``parent_id``·``sort_order``)·상태(``status=active``)·``trashed_at=None`` 을
    detached 안전하게 관찰하게 한다. 복구 API 는 L4(s10)에만 있어 엔진 직접 호출로 선검증한다.
    """
    with engine_access.session() as db:
        members = engine_access.engine.restore_bundle(db, root_document_id)
        return [_snapshot_document(m) for m in members]


def purge_bundle(
    engine_access: DocumentEngineAccess, root_document_id: int
) -> BundleSnapshot:
    """실제 엔진 ``purge_bundle`` 을 새 세션으로 호출(변경+커밋)하고 묶음 스냅샷을 반환한다.

    엔진이 묶음 구성원 전체를 trashed→deleted(종착)로 단일 커밋 전환하며 ``trashed_at`` 은
    보존한다(물리 삭제 없음, INV-4). 반환 :class:`Bundle` 을 세션 안에서 :class:`BundleSnapshot`
    으로 변환해 구성원·``trashed_at``·now-deleted ``status`` 를 detached 안전하게 관찰하게 한다.
    유효하지 않은 루트면 엔진 404 를 그대로 전파한다. 완전삭제 API 도 L4(s10)에만 있어 엔진 직접
    호출로 선검증한다.
    """
    with engine_access.session() as db:
        bundle = engine_access.engine.purge_bundle(db, root_document_id)
        return _snapshot_bundle(bundle)


def active_descendants(
    engine_access: DocumentEngineAccess, document_id: int
) -> list[DocumentSnapshot]:
    """실제 엔진 ``active_descendants`` 를 새 세션으로 호출하고 구성원 스냅샷 리스트를 반환한다.

    primitive 는 :class:`Document` 인자를 요구하므로 **같은 세션 안에서** ``db.get(Document, id)``
    로 대상을 로드해(사설 repository 속성에 손대지 않음) 호출한다. root 를 포함한 active 하위
    집합(이미 trashed 된 하위·그 서브트리 제외)을 세션 안에서 :class:`DocumentSnapshot` 으로
    변환해 detached 안전하게 반환한다. 대상 문서 미존재면 명확한 오류를 낸다.
    """
    with engine_access.session() as db:
        document = db.get(Document, document_id)
        if document is None:
            raise ValueError(
                f"active_descendants 대상 문서를 찾을 수 없다: id={document_id}"
            )
        descendants = engine_access.engine.active_descendants(db, document)
        return [_snapshot_document(d) for d in descendants]
