"""AttachmentStorage 단위 테스트 — WS 격리 저장·스트리밍·보관 이동 (Task 1.2).

design.md §Components and Interfaces #AttachmentStorage(Feature/Data) 계약을 검증한다:
- 저장 위치 `{file_storage_root}/{workspace_id}/...`, 보관 위치
  `{attachment_archive_root}/{workspace_id}/...` 로 워크스페이스 단위 격리(3.1·6.1).
- `save` 는 업로드 스트림을 저장 디렉터리에 기록하고 저장 상대 경로를 반환하며, 저장 파일명은
  서버 생성이라 원본 파일명과 다르다(경로 트래버설 방지, 1.2).
- `open_stream` 은 저장 파일을 스트리밍용으로 열고, 부재 시 `DomainError` 를 낸다.
- `move_to_archive` 는 저장 파일을 보관 위치로 **이동**(물리 삭제 없음, INV-4·4.2)하고 새 보관
  상대 경로를 반환하며, 이미 이동된 파일에 대한 재호출은 오류 없이 멱등(4.4)이다.

설정 접근은 s01 단일 Settings(`get_settings`) 경유이며, 테스트는 tmp_path 하위 디렉터리를
가리키는 settings 대역을 monkeypatch 해 실제 config.yml 저장 루트에 의존하지 않는다.
"""

import io
import types
from pathlib import Path

import pytest

import app.attachment.storage as storage_mod
from app.attachment.storage import AttachmentStorage
from app.common.errors import DomainError


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """저장/보관 루트를 tmp_path 하위로 격리한 settings 대역을 주입한다."""
    storage_root = tmp_path / "storage"
    archive_root = tmp_path / "archive"
    settings = types.SimpleNamespace(
        file_storage_root=str(storage_root),
        attachment_archive_root=str(archive_root),
    )
    monkeypatch.setattr(storage_mod, "get_settings", lambda: settings)
    return storage_root, archive_root


@pytest.fixture
def storage():
    return AttachmentStorage()


def _save(storage, workspace_id, filename, data):
    return storage.save(
        workspace_id=workspace_id,
        upload_filename=filename,
        stream=io.BytesIO(data),
    )


def test_save_writes_file_under_workspace_dir(roots, storage):
    """저장은 `{storage_root}/{workspace_id}/` 아래에 파일을 쓰고 상대 경로를 반환한다 (3.1)."""
    storage_root, _ = roots
    data = b"hello-image-bytes"

    rel = _save(storage, 7, "photo.png", data)

    # 반환 경로는 루트 독립적인 상대 경로여야 한다(루트를 포함하지 않음).
    assert not Path(rel).is_absolute()
    saved = storage_root / rel
    assert saved.is_file(), "저장 파일이 저장 위치에 존재해야 한다"
    # 워크스페이스 격리: 파일이 해당 workspace_id 디렉터리 아래에 있어야 한다.
    assert saved.parent == storage_root / "7"
    assert saved.read_bytes() == data


def test_save_separates_workspaces(roots, storage):
    """서로 다른 워크스페이스는 분리된 저장 디렉터리를 갖는다 (3.1·격리)."""
    storage_root, _ = roots

    rel_a = _save(storage, 1, "a.png", b"aaa")
    rel_b = _save(storage, 2, "b.png", b"bbb")

    assert (storage_root / rel_a).parent == storage_root / "1"
    assert (storage_root / rel_b).parent == storage_root / "2"
    assert (storage_root / rel_a).parent != (storage_root / rel_b).parent


def test_saved_content_matches_input(roots, storage):
    """저장된 파일 내용은 입력 스트림과 동일하다 (무손실 저장)."""
    storage_root, _ = roots
    data = bytes(range(256)) * 4

    rel = _save(storage, 3, "blob.bin", data)

    assert (storage_root / rel).read_bytes() == data


def test_server_generated_name_differs_from_upload_filename(roots, storage):
    """저장 파일명은 서버 생성이라 원본 업로드 파일명과 다르다 (경로 트래버설 방지, 1.2)."""
    _, _ = roots
    upload_filename = "../../etc/passwd.png"

    rel = _save(storage, 4, upload_filename, b"x")

    on_disk_name = Path(rel).name
    assert on_disk_name != Path(upload_filename).name
    assert on_disk_name != upload_filename
    # 서버 생성명에는 경로 구분자가 포함되지 않는다(트래버설 불가).
    assert "/" not in on_disk_name and "\\" not in on_disk_name
    assert ".." not in on_disk_name
    # 확장자는 best-effort 로 보존한다.
    assert on_disk_name.endswith(".png")


def test_open_stream_returns_saved_bytes(roots, storage):
    """open_stream 은 저장한 바이트를 그대로 읽을 수 있는 스트림을 연다 (서빙)."""
    _, _ = roots
    data = b"served-binary-content"
    rel = _save(storage, 5, "doc.pdf", data)

    with storage.open_stream(rel) as fh:
        assert fh.read() == data


def test_open_stream_missing_file_raises_domain_error(roots, storage):
    """부재 파일 서빙은 DomainError 로 표면화된다 (부재 시 도메인 예외)."""
    _, _ = roots

    with pytest.raises(DomainError):
        storage.open_stream("5/nonexistent-file.bin")


def test_move_to_archive_moves_file_without_physical_delete(roots, storage):
    """보관 이동은 파일을 저장→보관 위치로 옮기되 물리 삭제하지 않는다 (INV-4·4.2)."""
    storage_root, archive_root = roots
    data = b"archive-me"
    rel = _save(storage, 9, "keep.png", data)
    source = storage_root / rel
    assert source.is_file()

    archived_rel = storage.move_to_archive(workspace_id=9, file_path=rel)

    # 반환 경로는 보관 루트 기준 상대 경로.
    assert not Path(archived_rel).is_absolute()
    archived = archive_root / archived_rel
    # 보관 위치에 파일이 존재하고(물리 삭제 없음) 내용이 보존된다.
    assert archived.is_file(), "보관 위치에 파일이 존재해야 한다(물리 삭제 없음)"
    assert archived.read_bytes() == data
    # 보관 디렉터리도 워크스페이스 단위 격리.
    assert archived.parent == archive_root / "9"
    # 저장 위치의 원본은 남지 않는다(이동).
    assert not source.exists(), "이동 후 저장 위치에 원본이 남으면 안 된다"


def test_move_to_archive_is_idempotent_noop(roots, storage):
    """이미 이동된 파일에 대한 재보관 이동은 오류 없이 멱등하다 (4.4)."""
    storage_root, archive_root = roots
    data = b"idempotent"
    rel = _save(storage, 11, "x.png", data)

    first = storage.move_to_archive(workspace_id=11, file_path=rel)
    # 재호출: 저장 위치엔 이미 없고 보관 위치엔 존재 → no-op, 동일 보관 경로 반환.
    second = storage.move_to_archive(workspace_id=11, file_path=rel)

    assert first == second
    archived = archive_root / first
    assert archived.is_file(), "재보관 이동 후에도 보관 파일이 유지되어야 한다"
    assert archived.read_bytes() == data
