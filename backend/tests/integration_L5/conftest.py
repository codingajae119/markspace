"""L5 통합 테스트 하네스 (Task 1.1 / Req 1.1·1.2·1.3·1.4·1.6, design §L5TestHarness).

mock 없이 s01 ⊕ s02 ⊕ s03 ⊕ s05 ⊕ s07 ⊕ s09 ⊕ s10 ⊕ **s12** 의 실제 구현을 결합한 검증
환경을 제공한다. 핵심 원칙은 **L4 하네스 재사용·확장**(중복 신설 금지)이다: 마이그레이션
(`alembic upgrade head`)·`s01` `create_app()` 부팅·admin 시드·세션 유지 `TestClient` 팩토리·
고유 login_id 생성기·워크스페이스 생성·멤버 추가(role)·role별 세션 클라이언트·문서 트리 생성·
부팅 앱과 동일 `SessionLocal`/`get_db` 세션의 `DocumentStateEngine` 접근·두 editor(A·B) 세션·
휴지통 삭제·`now` 주입 `RetentionSweepService` 호출은 모두 `s11` `tests/integration_L4` 자산
(그리고 그것이 재사용하는 `s08` `tests/integration_L3`·`s06` `tests/integration_L2`·`s04`
`tests/integration_L1`)을 그대로 쓴다. 부팅 앱은 s02·s03·s05·s07·s09·s10·**s12 첨부 라우터 +
아카이브 스케줄러가 조립된 상태**(`app.main.create_app`/lifespan)이므로 첨부 업로드·서빙 라우트
(s01 카탈로그 행 32~33)와 lifespan 아카이브 스케줄러 훅이 결합되어 있다.

pytest 는 fixture 를 정의된 디렉터리 트리에서만 수집하므로, 형제 디렉터리(L4/L3/L2/L1)의
fixture 는 L5 에서 보이도록 **명시적 re-import** 해야 한다(L4 conftest 의 re-import 패턴 답습).
L3 conftest 의 ``__all__`` 이 이미 `harness`(L1)·`ws_scenario`/`WorkspaceScenario`(L2)·문서
트리·엔진 접근을 자신의 네임스페이스로 재-export 하고, L4 conftest 가 그 위에 `lock_scenario`·
`trash_scenario`·`sweep_access` 를 더한다. 이 모듈은 그 두 지점에서 하네스·시나리오·스윕 접근
픽스처를 한꺼번에 재-import 한다.

이 모듈이 신규로 추가하는 것은 s12 첨부 통합 전용 두 픽스처다:

1. ``tmp_attachment_roots`` (:class:`AttachmentStorageRoots`): 저장/보관 루트를 tmp_path
   하위로 격리한 settings 대역을 storage 모듈에 monkeypatch 한다. `AttachmentStorage` 가
   `app.attachment.storage.get_settings()` 를 **호출 시점**에 읽으므로, 이 대역은 API 업로드
   경로(라우터→서비스→스토리지)와 아카이브 스윕(완전삭제 반응·참조 소멸) 양쪽을 모두 tmp
   루트로 돌려 실제 `./var/attachments` 저장 루트를 오염시키지 않는다. 노출된
   ``file_storage_root``/``attachment_archive_root`` 경로로 파일시스템 관찰 스위트가 디스크상
   WS 격리 저장·보관 이동을 직접 단언한다.
2. ``archival_sweep`` (:class:`ArchivalSweepAccess`): 부팅 앱과 **동일 세션 팩토리**
   (`harness.session_local`)로 실제 s12 `ArchivalSweepService` 를 조립해, 주입된 ``now`` 로
   ``sweep`` 을 1회 구동하고 처리 건수를 반환한다(L4 `SweepAccess` 의 s12 아카이브 아날로그 —
   `SweepAccess` 는 s10 retention 스윕, ``archival_sweep`` 은 s12 아카이브 스윕). 후속
   스위트(보관 이동↔완전삭제 결합 2.3·참조 소멸↔버전 저장 결합 2.4·보관 격리 2.5)가 이 하나의
   접근 핸들로 완전삭제 반응(8.6)·참조 소멸(8.7) 아카이브를 관찰하도록 지금 함께 둔다.

제약(design §L5TestHarness):
- 어떤 애플리케이션 코드·`config.yml`·L4/L3/L2/L1 하네스 자산도 수정하지 않는다(재사용만). 동일
  하네스를 중복 정의하지 않는다.
- mock·stub 미사용(스윕 직접 호출은 실제 s12·s10·s07 코드 실행이므로 허용). 설정은 s01
  `Settings` 재사용(첨부 additive `attachment_archive_root`·`attachment_sweep_interval_seconds`·
  `attachment_max_bytes` 포함, L1 하네스 경유)이며, storage 루트만 tmp 로 격리한다.
- DB·파일시스템 미가용·부팅 실패 시 스킵이 아니라 **실패**(L1 `harness` 가 오류를 전파;
  여기서 ``pytest.skip`` 을 쓰지 않는다).
- 공유 `markspace_test` DB 오염 방지를 위해 사용자·문서마다 고유 접미사(uuid4)를 쓴다.
"""

import types
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

import app.attachment.storage as storage_mod
from app.attachment.archival import ArchivalSweepService

# L4 conftest 에서 하네스(L1)·워크스페이스 시나리오(L2)·문서 트리·엔진 접근(L3) 및 L4 전용
# 확장(lock_scenario·trash_scenario·sweep_access)을 한꺼번에 재-import 한다. L4 conftest 의
# ``__all__`` 이 L3(및 하위)의 재-export 를 이미 자신의 네임스페이스로 노출하므로, 이 하나의
# 지점에서 하네스 계보 전체와 L4 확장 픽스처를 함께 가져올 수 있다. pytest 는 형제 디렉터리
# fixture 를 자동 수집하지 않으므로 명시적 re-import 가 필요하다.
from tests.integration_L4.conftest import (  # noqa: F401 — L4(및 하위) 하네스 픽스처 재사용
    DocumentEngineAccess,
    DocumentTreeScenario,
    LockScenario,
    SweepAccess,
    TrashScenario,
    WorkspaceScenario,
    doc_tree_scenario,
    engine_access,
    harness,
    lock_scenario,
    sweep_access,
    trash_scenario,
    ws_scenario,
)

__all__ = [
    # (재사용) L4/L3/L2/L1 하네스 재-export
    "harness",
    "ws_scenario",
    "WorkspaceScenario",
    "doc_tree_scenario",
    "DocumentTreeScenario",
    "engine_access",
    "DocumentEngineAccess",
    "lock_scenario",
    "LockScenario",
    "trash_scenario",
    "TrashScenario",
    "sweep_access",
    "SweepAccess",
    # (신규) s12 첨부 통합 하네스 확장
    "AttachmentStorageRoots",
    "tmp_attachment_roots",
    "ArchivalSweepAccess",
    "archival_sweep",
]


# =============================================================================
# (1) 파일시스템 격리 — 저장/보관 루트를 tmp 로 돌리는 settings 대역
# =============================================================================


@dataclass
class AttachmentStorageRoots:
    """tmp 로 격리된 저장/보관 루트 경로 번들(디스크상 WS 격리·보관 이동 단언용).

    - ``file_storage_root``: 업로드 파일이 실제 기록되는 tmp 저장 루트. 저장 파일은
      ``{file_storage_root}/{workspace_id}/{server_name}`` 에 존재한다(INV-6).
    - ``attachment_archive_root``: 아카이브 스윕이 파일을 옮기는 tmp 보관 루트(8.6/8.7용).
    """

    file_storage_root: Path
    attachment_archive_root: Path


@pytest.fixture
def tmp_attachment_roots(tmp_path, monkeypatch) -> AttachmentStorageRoots:
    """저장/보관 루트를 tmp_path 하위로 격리한 settings 대역을 storage 모듈에 주입한다.

    `AttachmentStorage` 는 `app.attachment.storage.get_settings()` 로 저장/보관 루트를 **호출
    시점**에 해석하므로, 그 모듈의 `get_settings` 를 tmp 루트를 가리키는 namespace 로 대체하면
    API 업로드(라우터→서비스→스토리지)와 아카이브 스윕(완전삭제 반응·참조 소멸)이 모두 tmp
    하위에 쓰기·이동하게 되어 실제 `config.yml` 저장 루트(`./var/attachments`)를 오염시키지
    않는다. 반환된 경로로 파일시스템 관찰 스위트가 디스크상 WS 격리 저장·보관 이동을 직접
    관찰한다. ``monkeypatch``·``tmp_path`` 는 둘 다 function-scope 라 이 픽스처와 수명이 정합한다.
    """
    storage_root = tmp_path / "storage"
    archive_root = tmp_path / "archive"
    settings = types.SimpleNamespace(
        file_storage_root=str(storage_root),
        attachment_archive_root=str(archive_root),
    )
    monkeypatch.setattr(storage_mod, "get_settings", lambda: settings)
    return AttachmentStorageRoots(
        file_storage_root=storage_root,
        attachment_archive_root=archive_root,
    )


# =============================================================================
# (2) 아카이브 스윕 접근 — 부팅 앱과 동일 세션으로 실제 s12 스윕을 now 주입 구동
# =============================================================================


class ArchivalSweepAccess:
    """부팅 앱과 동일 세션 팩토리로 실제 s12 `ArchivalSweepService` 를 구동하는 접근 핸들.

    부팅 앱이 `get_db` override 로 쓰는 **같은** 세션 팩토리(`harness.session_local`)로 실제
    스윕 서비스를 조립한다. API 가 커밋한 첨부·문서·버전 행 위에서 주입된 ``now`` 로 완전삭제
    반응(8.6)·참조 소멸(8.7) 아카이브가 동작함을 관찰한다(엔진 위임·관측 판정). 어떤 것도
    mock 하지 않는다 — L4 `SweepAccess`(s10 retention 스윕)의 s12 아카이브 아날로그다. 후속
    2.3/2.4/2.5 seam 통합 스위트가 이 핸들로 스윕을 구동한다.

    노출 표면:
    - ``session_local``: 부팅 앱과 동일한 세션 팩토리.
    - ``service``: 주입된 실제 :class:`ArchivalSweepService`.
    - :meth:`sweep`: 새 세션을 열어 ``sweep(db, now)`` 를 구동하고 커밋한 뒤 처리 건수를 반환.
    """

    def __init__(self, session_local: sessionmaker) -> None:
        self.session_local = session_local
        self.service = ArchivalSweepService()

    def sweep(self, now: datetime) -> int:
        """새 세션으로 주입된 ``now`` 기준 스윕을 1회 구동하고 처리 건수를 반환한다.

        부팅 앱과 동일 세션 팩토리를 써서 API 가 커밋한 행 위에서 실제 스윕이 동작함을
        관찰한다(완전삭제 반응 + 참조 소멸의 합산 처리 건수). 세션 수명(commit·close)은 이
        핸들이 소유한다.
        """
        with self.session_local() as db:
            processed = self.service.sweep(db, now)
            db.commit()
        return processed


@pytest.fixture
def archival_sweep(harness) -> ArchivalSweepAccess:
    """부팅 앱과 동일 세션 팩토리로 실제 s12 `ArchivalSweepService` 를 조립한 스윕 접근 핸들.

    `harness.session_local` 은 앱 `get_db` override 와 **동일한** 세션 팩토리이므로, 여기서
    구동하는 스윕은 API 가 커밋한 첨부·문서·버전 행을 그대로 관찰·이동한다(동일 DB·커밋 경계
    정렬). ``now`` 는 :meth:`ArchivalSweepAccess.sweep` 호출 시 주입해 붙여넣기 보호 경계 등
    만료 판정을 결정적으로 검증한다. 실제 s12 코드를 실행하며 어떤 것도 mock 하지 않는다.
    """
    return ArchivalSweepAccess(harness.session_local)
