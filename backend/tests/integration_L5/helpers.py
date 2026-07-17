"""L5 첨부·아카이브 스윕·파일시스템 시나리오 헬퍼 — 실제 라우트·실제 스윕·실제 파일 I/O 의
얇은 래퍼 (Task 1.2 / Req 1.4, 3.1, 4.1, 5.1, 6.1, design §Helpers).

후속 스위트(첨부 흐름 2.2 · 완전삭제 결합 2.3 · 저장 참조 소멸 결합 2.4 · 보관 격리·비노출 2.5 ·
아래 계층 결합 엣지 2.6)가 이미지·파일 업로드→서빙, 이미지 참조 본문 저장/소멸, 완전삭제·보관
만료 반응 스윕, 저장/보관 파일시스템 관찰 같은 cross-spec 시나리오를 간결하게 표현하도록, s12
첨부 라우트(s01 카탈로그 행 32~33)의 **실제** 엔드포인트와 s12 `ArchivalSweepService` 의
**실제** 스윕(부팅 앱과 동일 세션 팩토리로 조립)을 감싸는 얇은 래퍼를 모은다. mock 이 아니라
부팅된 앱(`app.main.create_app`, s12 첨부 라우터·아카이브 스케줄러 조립)의 실 라우트·실 스윕·실
파일 I/O 를 태운다.

## 설계 규칙 (음성 경로 가능성 보존 — L4/L3/L2/L1 helpers.py 관용 답습)
- **attempt 계열** (:func:`attempt_upload_attachment`·:func:`attempt_get_attachment`): 후속
  스위트가 같은 래퍼로 성공(201/200)과 실패(401/403/404/422)를 **둘 다** 단언해야 하므로 **응답
  객체를 그대로 반환하고 상태를 내부에서 단언하지 않는다**. 계약 대조 스위트가 크기 초과 422·
  role별 거부를 같은 래퍼로 관찰한다.
- **setup 계열** (:func:`upload_attachment`·:func:`upload_image`·:func:`upload_file`·
  :func:`get_attachment`·:func:`save_with_reference`·:func:`save_without_reference`·
  :func:`lock_and_save`): 시나리오 준비상 항상 성공하는 단계이므로 성공 상태를 내부에서 단언하고
  유용한 값(파싱된 ``AttachmentRead`` dict / 버전 dict / :class:`Response`)을 돌려주어 시나리오
  코드를 읽기 쉽게 한다. 내부적으로 대응하는 attempt/L4 래퍼를 재사용한다(URL·바디 단일 정의).

## L4/L3/L2/L1 헬퍼 재사용 (중복 정의 금지)
잠금(`lock`)·저장(`save`)·편집 취소(`cancel`)·강제 해제(`force_unlock`)·버전 목록
(`list_versions`)·휴지통 목록(`list_trash`)·복구/완전삭제(`restore_bundle_via_api`·
`purge_bundle_via_api`)·retention 스윕(`run_sweep`) 래퍼와, 그것이 재사용하는 문서 생성·삭제·
이동·조회(L3)·워크스페이스·멤버·role(L2)·계정·로그인·상태 전이(L1) 헬퍼는 `s11` L4
`helpers.py`(및 그것이 재-export 하는 L3/L2/L1)를 **그대로** 쓴다(재정의하지 않는다). 이 모듈은
L4 helpers 를 참조로 재-export 하므로 스위트가 한 지점(``tests.integration_L5.helpers``)에서 첨부
업로드·서빙·이미지 참조 저장·아카이브 스윕·파일 관찰 래퍼는 물론 잠금·저장·휴지통·문서·엔진·
워크스페이스·계정 헬퍼까지 모두 도달한다(중복 **정의**가 아닌 참조).

## 이미지 참조 저장 — s09 저장(L4 `save`) 재사용
:func:`save_with_reference`/:func:`save_without_reference` 는 s12 저장 로직을 새로 만들지 않고
s09 저장 라우트(L4 `save`)에 참조 토큰(`/attachments/{id}`)을 포함/제외한 markdown 본문을 실어
현재 버전 참조를 만들거나 소멸시킨다. s09 저장은 **잠금 보유**를 요구하고 저장 후 잠금을
해제하므로, 두 래퍼는 L4 `lock` → L4 `save` 순서를 내부에 캡슐화한다
(:func:`lock_and_save` 로 단일화). s12 는 이 저장·버전 생성을 소유하지 않는다 — 스윕이 s09 가
만든 현재 버전 참조라는 관측 가능한 결과를 뒤에서 관측할 뿐이다.

첨부 엔드포인트 계약 (s01 단일 소스, 카탈로그 행 32~33):
- ``POST /documents/{id}/attachments`` (EDITOR, multipart ``file`` + 선택 ``kind`` Form) → 201
  ``AttachmentRead``(``id``·``url``=`/attachments/{id}`·``kind``·``original_name``·
  ``is_archived``·``workspace_id``·``document_id``; ``file_path`` 미노출) / viewer 403 / 비멤버
  403 / 미인증 401 / 미존재 문서 404 / 크기 초과 422
- ``GET /attachments/{id}`` (VIEWER, 첨부→WS 어댑터) → 200 binary stream / 비멤버 403 / 미인증
  401 / 미존재·보관 첨부 404
"""

import io
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import sessionmaker

from app.models import Attachment

# L4 헬퍼 재-export (중복 정의가 아니라 참조). L4 는 잠금·저장·휴지통·retention 스윕 래퍼를
# 정의하고, 그것이 재사용하는 L3(문서·엔진)·L2(워크스페이스)·L1(계정) 헬퍼를 재-export 한다.
from tests.integration_L4 import helpers as l4_helpers

# 아카이브 스윕 접근 핸들·저장 루트 번들 타입(래퍼가 받는 얇은 위임 대상, 아래 참조).
from tests.integration_L5.conftest import ArchivalSweepAccess, AttachmentStorageRoots

l3_helpers = l4_helpers.l3_helpers
l2_helpers = l4_helpers.l2_helpers
l1_helpers = l4_helpers.l1_helpers

__all__ = [
    # (재사용) L4/L3/L2/L1 헬퍼 재-export — 잠금·저장·휴지통·문서·엔진·워크스페이스·계정
    "l4_helpers",
    "l3_helpers",
    "l2_helpers",
    "l1_helpers",
    # (A) 첨부 업로드·서빙 래퍼 (multipart)
    "attempt_upload_attachment",
    "upload_attachment",
    "upload_image",
    "upload_file",
    "attempt_get_attachment",
    "get_attachment",
    # (B) 이미지 참조 저장 래퍼 (s09 저장 = L4 `save` 재사용)
    "attachment_url",
    "lock_and_save",
    "save_with_reference",
    "save_without_reference",
    # (C) 아카이브 스윕 래퍼
    "run_archival_sweep",
    # (D) 파일시스템 관찰 래퍼
    "stored_file_path",
    "archived_file_path",
    "assert_stored",
    "assert_not_stored",
    "assert_archived",
    "assert_not_archived",
    "assert_ws_isolated",
    "attachment_file_path",
    "attachment_is_archived",
]


# =============================================================================
# (A) 첨부 업로드·서빙 래퍼 — 실제 s12 라우트 호출(부팅 앱, multipart)
# =============================================================================


def attempt_upload_attachment(
    client: TestClient,
    document_id: int,
    *,
    filename: str,
    content: bytes,
    content_type: str,
    kind: str | None = None,
) -> Response:
    """``POST /documents/{id}/attachments`` multipart 업로드를 태우고 **응답을 그대로 반환**한다.

    ATTEMPT 헬퍼 — EDITOR+ 는 201 ``AttachmentRead``, viewer/비멤버 403, 미인증 401, 미존재 문서
    404(문서→WS 어댑터), 크기 초과 422 를 스위트가 각각 단언한다. 파일 필드명은 계약상 ``file``
    이며 tuple 의 ``content_type`` 이 라우터의 kind 추론(image/* → image, 그 외 → file)을 구동한다.
    ``kind`` 를 주면 Form 필드로 실어 추론보다 우선시킨다. 상태는 호출자가 단언한다(성공·게이팅
    음성 경로를 같은 래퍼로 관찰). ``content`` 를 큰 바이트열로 주면 계약 스위트가 422 를 유발한다.
    """
    files = {"file": (filename, io.BytesIO(content), content_type)}
    data = {"kind": kind} if kind is not None else None
    return client.post(
        f"/documents/{document_id}/attachments", files=files, data=data
    )


def upload_attachment(
    client: TestClient,
    document_id: int,
    *,
    filename: str,
    content: bytes,
    content_type: str,
    kind: str | None = None,
) -> dict:
    """editor 세션으로 첨부를 업로드한다. SETUP — 201 을 단언하고 파싱된 ``AttachmentRead`` dict 반환.

    응답 dict 는 ``id``·``url``(=`/attachments/{id}`)·``kind``·``original_name``·``is_archived``·
    ``workspace_id``·``document_id`` 를 담는다(``file_path`` 는 미노출 — DB 관찰은
    :func:`attachment_file_path` 로).
    """
    resp = attempt_upload_attachment(
        client,
        document_id,
        filename=filename,
        content=content,
        content_type=content_type,
        kind=kind,
    )
    assert resp.status_code == 201, (
        f"첨부 업로드 201 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp.json()


def upload_image(
    client: TestClient,
    document_id: int,
    *,
    content: bytes = b"\x89PNG\r\n\x1a\n-l5-image-payload",
    filename: str = "pic.png",
) -> dict:
    """editor 세션으로 이미지(붙여넣기) 첨부를 업로드한다. SETUP — ``image/png`` 로 kind=image 유도.

    content-type ``image/png`` 이 라우터의 kind 추론을 image 로 구동한다(8.1). 반환 dict 의
    ``url``(`/attachments/{id}`)이 이후 본문 참조 토큰이 된다. 201 단언 후 파싱된
    ``AttachmentRead`` dict 반환.
    """
    return upload_attachment(
        client,
        document_id,
        filename=filename,
        content=content,
        content_type="image/png",
    )


def upload_file(
    client: TestClient,
    document_id: int,
    *,
    content: bytes = b"%PDF-1.4 l5-file-payload\n%%EOF",
    filename: str = "doc.bin",
) -> dict:
    """editor 세션으로 일반 파일 첨부를 업로드한다. SETUP — 명시 ``kind=file`` 로 종류를 강제.

    ``application/octet-stream`` content-type + 명시 ``kind=file`` 로 일반 파일 종류를 강제한다
    (8.7 image 한정 스코프 밖 → 참조 소멸로 보관되지 않고 8.6 완전삭제 반응만이 보관 경로).
    201 단언 후 파싱된 ``AttachmentRead`` dict 반환.
    """
    return upload_attachment(
        client,
        document_id,
        filename=filename,
        content=content,
        content_type="application/octet-stream",
        kind="file",
    )


def attempt_get_attachment(client: TestClient, attachment_id: int) -> Response:
    """``GET /attachments/{id}`` 를 태우고 **응답을 그대로 반환**한다(상태 미단언).

    ATTEMPT 헬퍼 — VIEWER+ 는 200 binary stream(content·content-type 관찰), 비멤버 403, 미인증
    401, 미존재·**보관** 첨부 404(role 무관 비노출, INV-7)를 스위트가 각각 단언한다.
    """
    return client.get(f"/attachments/{attachment_id}")


def get_attachment(client: TestClient, attachment_id: int) -> Response:
    """viewer+ 세션으로 미보관 첨부 바이너리를 조회한다. SETUP — 200 을 단언하고 :class:`Response` 반환.

    호출자가 ``.content``(바이너리)·``.headers['content-type']`` 를 직접 읽을 수 있도록 파싱하지
    않고 :class:`Response` 를 그대로 돌려준다.
    """
    resp = attempt_get_attachment(client, attachment_id)
    assert resp.status_code == 200, (
        f"첨부 조회 200 이어야 한다: {resp.status_code} {resp.text}"
    )
    return resp


# =============================================================================
# (B) 이미지 참조 저장 래퍼 — s09 저장(L4 `save`) 재사용, 잠금→저장 순서 캡슐화
# =============================================================================


def attachment_url(attachment_id: int) -> str:
    """첨부 참조 URL 토큰(`/attachments/{id}`)을 만든다(본문 참조·비참조 대조의 단일 정의)."""
    return f"/attachments/{attachment_id}"


def lock_and_save(client: TestClient, document_id: int, content: str) -> dict:
    """editor 세션으로 잠금→저장(s09)을 한 번에 수행하고 파싱된 ``DocumentVersionRead`` 를 반환한다.

    s09 저장은 **잠금 보유**를 요구하고 저장 후 잠금을 해제한다(L4 계약). 이 래퍼는 L4 `lock` →
    L4 `save` 순서를 캡슐화해 스위트가 잠금 시퀀싱을 매번 반복하지 않게 한다(중복 정의가 아니라
    L4 래퍼 조합). s12 는 이 저장·버전 생성을 소유하지 않는다 — 스윕이 관측만 한다.
    """
    l4_helpers.lock(client, document_id)
    return l4_helpers.save(client, document_id, content)


def save_with_reference(
    client: TestClient,
    document_id: int,
    attachment_id: int,
    *,
    extra_text: str = "",
) -> dict:
    """현재 버전 본문에 첨부 참조 토큰(`/attachments/{id}`)을 포함해 저장한다(현재 버전 참조 생성).

    SETUP — 잠금→저장(L4 재사용, :func:`lock_and_save`)으로 현재 버전 본문에 참조 토큰을 남긴다.
    반환은 파싱된 ``DocumentVersionRead`` dict. 이 참조가 이후 참조 소멸(8.7) 대조의 근거가 된다.
    ``extra_text`` 로 본문에 임의 텍스트를 덧붙일 수 있다(참조 토큰은 항상 포함).
    """
    url = attachment_url(attachment_id)
    body = f"# 문서\n\n![붙여넣은 이미지]({url})\n\n{extra_text}"
    return lock_and_save(client, document_id, body)


def save_without_reference(
    client: TestClient,
    document_id: int,
    *,
    content: str = "본문",
) -> dict:
    """어떤 첨부도 참조하지 않는 본문으로 저장한다(참조 소멸·미참조 상태 구성).

    SETUP — 잠금→저장(L4 재사용)으로 현재 버전 본문에 어떤 `/attachments/{id}` 토큰도 남기지
    않는다. 반환은 파싱된 ``DocumentVersionRead`` dict. 이전 버전이 이미지를 참조했다면 이 저장이
    현재 버전 참조를 소멸시킨다(8.7 보관 이동 후보 구성). ``content`` 에 참조 토큰이 섞이지
    않도록 호출자가 보장한다(기본값은 참조 없는 텍스트).
    """
    assert "/attachments/" not in content, (
        "save_without_reference 본문에는 첨부 참조 토큰이 없어야 한다"
    )
    body = f"# 문서\n\n{content}\n"
    return lock_and_save(client, document_id, body)


# =============================================================================
# (C) 아카이브 스윕 래퍼 — ArchivalSweepAccess 핸들에 now 를 주입해 실제 s12 스윕 1회 구동
# =============================================================================


def run_archival_sweep(archival_sweep: ArchivalSweepAccess, now: datetime) -> int:
    """주입된 ``now`` 로 실제 s12 아카이브 스윕(완전삭제 반응 8.6 + 참조 소멸 8.7)을 1회 구동한다.

    :class:`~tests.integration_L5.conftest.ArchivalSweepAccess` 핸들(부팅 앱과 동일 세션 팩토리로
    실제 :class:`~app.attachment.archival.ArchivalSweepService` 를 조립)에 위임하는 **얇은
    래퍼**로, 스위트가 ``now`` 주입 스윕을 균일하게 표현하게 한다(로직 중복·mock 없음 — 세션
    수명·커밋은 핸들이 소유). 반환값은 ``sweep(db, now)`` 가 보관 이동한 첨부 수(int; 완전삭제
    반응 + 참조 소멸 합산)다. ``now`` 는 붙여넣기 보호 경계(8.7)에만 영향을 준다. 이는 L4
    `run_sweep`(s10 retention 스윕)의 s12 아카이브 아날로그다.
    """
    return archival_sweep.sweep(now)


# =============================================================================
# (D) 파일시스템 관찰 래퍼 — 저장/보관 루트 위 파일 존재·부재·WS 격리 관찰
# =============================================================================


def stored_file_path(roots: AttachmentStorageRoots, rel_path: str) -> Path:
    """저장 루트 기준 상대 경로(DB `file_path`)를 절대 저장 파일 경로로 해석한다."""
    return roots.file_storage_root / rel_path


def archived_file_path(roots: AttachmentStorageRoots, rel_path: str) -> Path:
    """보관 루트 기준 상대 경로(보관 후 DB `file_path`)를 절대 보관 파일 경로로 해석한다."""
    return roots.attachment_archive_root / rel_path


def assert_stored(roots: AttachmentStorageRoots, rel_path: str) -> Path:
    """저장 루트의 ``rel_path`` 위치에 파일이 물리적으로 존재함을 단언하고 그 경로를 반환한다."""
    path = stored_file_path(roots, rel_path)
    assert path.is_file(), (
        f"저장 파일이 저장 루트의 WS 격리 위치에 존재해야 한다: {path}"
    )
    return path


def assert_not_stored(roots: AttachmentStorageRoots, rel_path: str) -> None:
    """저장 루트의 ``rel_path`` 위치에 파일이 **없음**을 단언한다(보관 이동 후 원본 소멸 관찰)."""
    path = stored_file_path(roots, rel_path)
    assert not path.exists(), (
        f"이동/미저장으로 저장 루트에는 파일이 남아 있지 않아야 한다: {path}"
    )


def assert_archived(roots: AttachmentStorageRoots, rel_path: str) -> Path:
    """보관 루트의 ``rel_path`` 위치에 파일이 물리적으로 존재함을 단언하고 그 경로를 반환한다(INV-4)."""
    path = archived_file_path(roots, rel_path)
    assert path.is_file(), (
        f"보관 이동된 파일이 보관 루트의 WS 격리 위치에 존재해야 한다(INV-4, 삭제 아님): {path}"
    )
    return path


def assert_not_archived(roots: AttachmentStorageRoots, rel_path: str) -> None:
    """보관 루트의 ``rel_path`` 위치에 파일이 **없음**을 단언한다(미보관 첨부 관찰)."""
    path = archived_file_path(roots, rel_path)
    assert not path.exists(), (
        f"미보관 첨부는 보관 루트에 파일이 없어야 한다: {path}"
    )


def assert_ws_isolated(rel_path: str, workspace_id: int) -> None:
    """저장/보관 상대 경로가 ``{workspace_id}/`` 로 시작함을 단언한다(WS 격리, 8.3·8.8, INV-6)."""
    assert rel_path.startswith(f"{workspace_id}/"), (
        f"저장/보관 경로는 WS 격리 상대 경로여야 한다: {rel_path!r} (ws={workspace_id})"
    )


def attachment_file_path(
    session_local: sessionmaker, attachment_id: int
) -> str | None:
    """부팅 앱과 동일 세션 팩토리로 첨부 행의 현재 ``file_path``(저장/보관 rel path)를 신규 세션 관측.

    ``AttachmentRead`` 응답은 ``file_path`` 를 노출하지 않으므로, 파일시스템 관찰 스위트는 이
    래퍼로 DB rel path 를 읽는다. ``AttachmentRepository.mark_archived`` 가 보관 이동 시
    ``file_path`` 를 보관 rel path(`{workspace_id}/{name}`)로 갱신하므로, 스윕 후 이 값을 다시
    읽으면 보관 경로가 된다. ``session_local`` 로 ``harness.session_local`` 을 넘긴다. 미존재면
    ``None``.
    """
    with session_local() as db:
        att = db.get(Attachment, attachment_id)
        return None if att is None else att.file_path


def attachment_is_archived(
    session_local: sessionmaker, attachment_id: int
) -> bool | None:
    """부팅 앱과 동일 세션 팩토리로 첨부 행의 ``is_archived`` 를 신규 세션으로 관측한다(미존재면 None).

    보관 이동(8.6·8.7)이 실제로 ``is_archived=true`` 로 표시했는지 DB 부수효과로 확인한다.
    ``session_local`` 로 ``harness.session_local`` 을 넘긴다.
    """
    with session_local() as db:
        att = db.get(Attachment, attachment_id)
        return None if att is None else att.is_archived
