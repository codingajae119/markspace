"""파일 저장 어댑터 — `AttachmentStorage`
(design.md §Components and Interfaces #AttachmentStorage, Feature/Data).

워크스페이스 격리 저장/보관 디렉터리 규약과 파일 저장·서빙 스트림 열기·보관 위치로의
이동만 소유하는 순수 파일 I/O 어댑터다. DB·SQLAlchemy·`is_archived` 표시는 다루지 않으며
(그것은 Repository·Service 소관), 표준 라이브러리 파일 I/O만 사용한다.

규약(design.md §Responsibilities & Constraints):
- 저장 위치 `{file_storage_root}/{workspace_id}/...`, 보관 위치
  `{attachment_archive_root}/{workspace_id}/...` 로 워크스페이스 단위 격리(8.3·8.8, INV-6).
- 경로 트래버설 방지를 위해 저장 파일명은 **서버 생성**(`uuid4` + best-effort 확장자)이며,
  원본 파일명은 DB `original_name` 에만 보존한다.
- `save` 반환값은 저장 루트에 독립적인 **상대 경로**(`{workspace_id}/{server_name}`)로,
  DB 는 루트 비의존 참조만 보관한다. 스토리지는 open_stream/move 에서 루트를 내부 결합한다.
- `move_to_archive` 는 파일을 보관 위치로 **이동**만 하고 물리 삭제하지 않는다(INV-4). 이미
  이동된 파일에 대한 재호출은 오류 없이 멱등(no-op)이다.
- 보관 폴더는 자동 정리하지 않으며 단조 증가를 수용한다(8.11).

설정 접근은 s01 단일 Settings(`get_settings`) 경유이며 모듈별 설정 파일을 신설하지 않는다.
테스트가 저장/보관 루트를 격리할 수 있도록 `get_settings` 를 모듈 속성으로 참조한다.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from app.common.errors import DomainError, ErrorCode
from app.config import get_settings

__all__ = ["AttachmentStorage"]


class AttachmentStorage:
    """워크스페이스 격리 저장·서빙·보관 이동을 담당하는 파일 I/O 어댑터."""

    def _storage_root(self) -> Path:
        """저장 루트(`file_storage_root`)를 s01 단일 Settings 로 해석한다."""
        return Path(get_settings().file_storage_root)

    def _archive_root(self) -> Path:
        """보관 루트(`attachment_archive_root`)를 s01 단일 Settings 로 해석한다."""
        return Path(get_settings().attachment_archive_root)

    def save(self, *, workspace_id: int, upload_filename: str, stream: BinaryIO) -> str:
        """업로드 스트림을 워크스페이스 저장 디렉터리에 기록하고 저장 상대 경로를 반환한다.

        저장 파일명은 원본을 쓰지 않고 서버가 생성(`uuid4` + best-effort 확장자)해 경로
        트래버설을 차단한다. 원본 파일명은 여기서 쓰지 않고 DB `original_name` 에만 보존된다.
        디렉터리는 자동 생성한다. 반환값은 루트 독립적인 `{workspace_id}/{server_name}` 이다.
        """
        server_name = f"{uuid4().hex}{_safe_suffix(upload_filename)}"
        rel_path = f"{workspace_id}/{server_name}"
        dest = self._storage_root() / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            shutil.copyfileobj(stream, fh)
        return rel_path

    def open_stream(self, file_path: str) -> BinaryIO:
        """저장 경로의 파일을 서빙용 바이너리 스트림으로 연다.

        `file_path` 는 저장 루트 기준 상대 경로다. 파일이 없으면(예: 이미 보관 이동됨)
        s01 공통 `DomainError`(404 NOT_FOUND)로 표면화해 사라진 파일 서빙을 깨끗이 드러낸다.
        """
        target = self._storage_root() / file_path
        try:
            return target.open("rb")
        except FileNotFoundError as exc:
            raise DomainError(
                code=ErrorCode.NOT_FOUND,
                message="첨부 파일을 찾을 수 없습니다",
                http_status=404,
            ) from exc

    def move_to_archive(self, *, workspace_id: int, file_path: str) -> str:
        """저장 파일을 워크스페이스 보관 디렉터리로 이동하고 새 보관 상대 경로를 반환한다.

        물리 삭제 없이 파일을 옮기기만 한다(INV-4). 보관 상대 경로는
        `{workspace_id}/{원본 저장 파일명}` 이다. 이미 이동된 경우(저장 위치엔 없고 보관
        위치엔 존재) 재호출은 오류 없이 보관 경로를 반환하는 멱등 no-op 이다.
        """
        archived_rel = f"{workspace_id}/{Path(file_path).name}"
        source = self._storage_root() / file_path
        dest = self._archive_root() / archived_rel

        if source.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            # 물리 삭제 없이 저장→보관 위치로 이동(INV-4). 서버 생성 uuid 파일명이라 충돌 없음.
            shutil.move(str(source), str(dest))
            return archived_rel

        if dest.exists():
            # 이미 보관 이동된 상태 → 멱등 no-op.
            return archived_rel

        # 저장·보관 어느 위치에도 파일이 없으면 이동할 대상이 없음.
        raise DomainError(
            code=ErrorCode.NOT_FOUND,
            message="보관 이동할 첨부 파일을 찾을 수 없습니다",
            http_status=404,
        )


def _safe_suffix(upload_filename: str) -> str:
    """업로드 파일명에서 확장자를 best-effort 로 추출한다(트래버설 안전).

    `Path(...).name.suffix` 는 최종 경로 요소의 확장자만 반환하므로 경로 구분자·상위 참조가
    섞여 있어도 안전하다. 확장자가 없으면 빈 문자열을 반환한다.
    """
    return Path(Path(upload_filename).name).suffix
