"""s14 공유 통합 테스트 하네스 (Task 4.x / design §Testing Strategy Integration Tests).

mock 없이 s01 ⊕ s02 ⊕ s03 ⊕ s05 ⊕ s07 ⊕ s09 ⊕ s10 ⊕ s12 ⊕ **s14** 의 실제 구현을 결합한
검증 환경을 제공한다. 핵심 원칙은 **L3 하네스 재사용**(중복 신설 금지)이다: 마이그레이션
(`alembic upgrade head`)·`s01` `create_app()` 부팅(공유 라우터 + 무효화 스케줄러 포함)·admin
시드·세션 유지 `TestClient` 팩토리·고유 login_id 생성기·워크스페이스 생성·멤버 추가(role)·
role별 세션 클라이언트·문서 트리 생성·부팅 앱과 동일 `SessionLocal`/`get_db` 세션은 모두 `s08`
`tests/integration_L3` 자산(그리고 그것이 재사용하는 `s06` `tests/integration_L2`·`s04`
`tests/integration_L1`)을 그대로 쓴다. 부팅 앱은 s02·s03·s05·s07·s09·s10·s12·**s14 공유
라우터가 조립된 상태**(`app.main.create_app`, task 3.3)이므로 발급·토글·공개 렌더·공개 첨부
서빙 라우트(s01 카탈로그 행 34~37)가 노출된다.

pytest 는 fixture 를 정의된 디렉터리 트리에서만 수집하므로, 형제 디렉터리(L3/L2/L1)의
fixture 는 `tests/sharing/` 에서 보이도록 **명시적 re-import** 해야 한다(attachment conftest 의
re-import 패턴 답습). L3 conftest 의 ``__all__`` 이 이미 `harness`(L1)·`ws_scenario`/
`WorkspaceScenario`(L2)·문서 트리·엔진 접근을 자신의 네임스페이스로 재-export 하므로, 이 모듈은
그 하나의 지점에서 하네스·워크스페이스 시나리오·문서 트리·엔진 접근 픽스처를 한꺼번에 재-import
한다.

이 모듈이 신규로 추가하는 것은 공유 통합 테스트 전용 두 픽스처다:

1. ``sharing_sweep`` (:class:`ShareInvalidationSweepAccess`): 부팅 앱과 **동일 세션 팩토리**
   (`harness.session_local`)로 실제 s14 `ShareInvalidationSweep` 을 구동해, API 가 커밋한 링크·
   문서·워크스페이스 행 위에서 무효화 반응 조정(retire)을 관찰하고 retire 건수를 반환한다(s12
   `archival_sweep` 의 s14 아날로그). 모듈 레벨 `run_invalidation_sweep()` 을 직접 호출하지
   않는 이유는 그것이 비-테스트 `app.common.db.SessionLocal` 에 바인딩되어 테스트 DB 에 커밋된
   행을 보지 못하기 때문이다. 4.2/4.3 무효화·재발급 seam 통합 테스트가 이 핸들로 스윕을 구동한다.
2. ``tmp_attachment_roots`` (:class:`AttachmentStorageRoots`): 저장/보관 루트를 tmp_path 하위로
   격리한 settings 대역을 s12 storage 모듈에 monkeypatch 한다(4.4 링크 경유 첨부 서빙 테스트가
   실제 `./var/...` 저장 루트를 오염시키지 않도록). attachment conftest 의 규약과 동일하다.

제약(design §Testing Strategy):
- 어떤 애플리케이션 코드·`config.yml`·L3/L2/L1 하네스 자산도 수정하지 않는다(재사용만).
- mock·stub 미사용(스윕 직접 호출은 실제 s14 코드 실행이므로 허용). 설정은 s01 `Settings`
  재사용(L1 하네스 경유)이며, storage 루트만 tmp 로 격리한다.
- DB 미가용·부팅 실패 시 스킵이 아니라 **실패**(L1 `harness` 가 오류를 전파; ``pytest.skip``
  을 쓰지 않는다).
- 공유 `notion_lite_test` DB 오염 방지를 위해 사용자·문서마다 고유 접미사(uuid4)를 쓴다.
"""

import types
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

import app.attachment.storage as storage_mod
from app.sharing.invalidation import ShareInvalidationSweep
from tests.integration_L1 import helpers as l1_helpers
from tests.integration_L2 import helpers as l2_helpers
from tests.integration_L3 import helpers as l3_helpers

# L3 conftest 에서 하네스·워크스페이스 시나리오·문서 트리·엔진 접근 픽스처를 한꺼번에 재-import
# 한다(L3 __all__ 이 L1 `harness`·L2 `ws_scenario`/`WorkspaceScenario` 를 이미 재-export 함).
# pytest 는 형제 디렉터리 fixture 를 자동 수집하지 않으므로 명시적 re-import 가 필요하다.
from tests.integration_L3.conftest import (  # noqa: F401 — L3(및 하위) 하네스 픽스처 재사용
    DocumentEngineAccess,
    DocumentTreeScenario,
    WorkspaceScenario,
    doc_tree_scenario,
    engine_access,
    harness,
    ws_scenario,
)

__all__ = [
    # (재사용) L3/L2/L1 하네스 재-export
    "harness",
    "ws_scenario",
    "WorkspaceScenario",
    "doc_tree_scenario",
    "DocumentTreeScenario",
    "engine_access",
    "DocumentEngineAccess",
    "l1_helpers",
    "l2_helpers",
    "l3_helpers",
    # (신규) s14 공유 통합 하네스 확장
    "ShareInvalidationSweepAccess",
    "sharing_sweep",
    "AttachmentStorageRoots",
    "tmp_attachment_roots",
]


class ShareInvalidationSweepAccess:
    """부팅 앱과 동일 세션 팩토리로 실제 s14 `ShareInvalidationSweep` 을 구동하는 접근 핸들.

    부팅 앱이 `get_db` override 로 쓰는 **같은** 세션 팩토리(`harness.session_local`)로 실제
    무효화 스윕을 조립·구동한다. API 가 커밋한 링크·문서·워크스페이스 행 위에서 문서 status·
    게이트 관측 기반 retire(비활성 + 토큰 교체)가 동작함을 관찰한다(관측 판정). 어떤 것도 mock
    하지 않는다. 4.2/4.3 무효화·재발급 seam 통합 테스트가 이 핸들로 스윕을 구동한다.

    모듈 레벨 `run_invalidation_sweep()` 을 직접 쓰지 않는 이유: 그 엔트리포인트는 호출 시점에
    비-테스트 `app.common.db.SessionLocal` 을 참조하므로, API 가 테스트 DB 에 커밋한 행을 보지
    못한다(다른 DB). 이 핸들은 `harness.session_local`(= 앱 override 팩토리)로 스윕해 동일 DB·
    커밋 경계를 정렬한다.

    노출 표면:
    - ``session_local``: 부팅 앱과 동일한 세션 팩토리.
    - ``service``: 주입된 실제 :class:`ShareInvalidationSweep`.
    - :meth:`sweep`: 새 세션을 열어 ``invalidate_by_observation(db)`` 를 구동하고 커밋한 뒤
      retire 건수를 반환.
    """

    def __init__(self, session_local: sessionmaker) -> None:
        self.session_local = session_local
        self.service = ShareInvalidationSweep()

    def sweep(self) -> int:
        """새 세션으로 무효화 반응 조정 스윕을 1회 구동하고 retire 건수를 반환한다.

        부팅 앱과 동일 세션 팩토리를 써서 API 가 커밋한 링크·문서·게이트 행 위에서 실제 스윕이
        동작함을 관찰한다. 세션 수명(commit·close)은 이 핸들이 소유한다.
        """
        with self.session_local() as db:
            retired = self.service.invalidate_by_observation(db)
            db.commit()
        return retired


@pytest.fixture
def sharing_sweep(harness) -> ShareInvalidationSweepAccess:
    """부팅 앱과 동일 세션 팩토리로 실제 s14 `ShareInvalidationSweep` 을 조립한 스윕 접근 핸들.

    `harness.session_local` 은 앱 `get_db` override 와 **동일한** 세션 팩토리이므로, 여기서
    구동하는 스윕은 API 가 커밋한 공유 링크·문서·워크스페이스 행을 그대로 관측·retire 한다(동일
    DB·커밋 경계 정렬). 모듈 레벨 엔트리포인트가 아닌 이 핸들을 쓰는 이유는 위 클래스 docstring
    참조.
    """
    return ShareInvalidationSweepAccess(harness.session_local)


@dataclass
class AttachmentStorageRoots:
    """tmp 로 격리된 저장/보관 루트 경로 번들(디스크상 WS 격리 단언용).

    - ``file_storage_root``: 업로드 파일이 실제 기록되는 tmp 저장 루트. 저장 파일은
      ``{file_storage_root}/{workspace_id}/{server_name}`` 에 존재한다(8.3, INV-6).
    - ``attachment_archive_root``: 아카이브 스윕이 파일을 옮기는 tmp 보관 루트.
    """

    file_storage_root: Path
    attachment_archive_root: Path


@pytest.fixture
def tmp_attachment_roots(tmp_path, monkeypatch) -> AttachmentStorageRoots:
    """저장/보관 루트를 tmp_path 하위로 격리한 settings 대역을 storage 모듈에 주입한다.

    `AttachmentStorage` 는 `app.attachment.storage.get_settings()` 로 저장/보관 루트를 **호출
    시점**에 해석하므로, 그 모듈의 `get_settings` 를 tmp 루트를 가리키는 namespace 로 대체하면
    API 업로드(라우터→서비스→스토리지)와 링크 경유 서빙이 모두 tmp 하위에 쓰기·읽기하게 되어
    실제 `config.yml` 저장 루트(`./var/...`)를 오염시키지 않는다. 반환된 경로로 테스트가
    디스크상 워크스페이스 격리 저장을 직접 관찰한다(test_archival.py `roots` 픽스처와 동일 규약).
    ``monkeypatch``·``tmp_path`` 는 둘 다 function-scope 라 이 픽스처와 수명이 정합한다.
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
