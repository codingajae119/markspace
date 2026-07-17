"""첨부 설정의 s01 단일 Settings additive 확장 단위 테스트 (Requirement 7.5·7.6).

`attachment_archive_root`·`attachment_sweep_interval_seconds`·`attachment_max_bytes` 는
모듈별 설정 파일이 아니라 s01 공용 Settings 에 additive 로 추가된다(7.6). 저장 루트는
기존 `file_storage_root` 를 재사용하며 기존 필드 계약은 그대로 유지된다.

각 테스트는 개발자 로컬의 실제 backend/config.yml·.env 에 의존하지 않도록
tmp_path 로 격리한다(monkeypatch.chdir + secret env var 제거).
"""

import pytest

from app.config import Settings, get_settings

# attachment_* 는 의도적으로 생략 → 스키마 기본값 검증
CONFIG_YML = """\
app_name: notion-lite
db_host: 127.0.0.1
db_port: 3306
db_name: notion_lite
db_user: root
default_trash_retention_days: 30
file_storage_root: ./var/attachments
session_cookie_name: session
session_max_age_seconds: 1209600
"""

ENV_FILE = """\
db_password=secret-pw
session_secret=secret-session-value
"""

# 실제 프로세스 env에서 새어들 수 있는 설정 키(테스트 결정성 보장을 위해 제거)
_ENV_KEYS = (
    "APP_NAME", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER",
    "DEFAULT_TRASH_RETENTION_DAYS", "FILE_STORAGE_ROOT",
    "SESSION_COOKIE_NAME", "SESSION_MAX_AGE_SECONDS",
    "TRASH_SWEEP_INTERVAL_SECONDS",
    "ATTACHMENT_ARCHIVE_ROOT", "ATTACHMENT_SWEEP_INTERVAL_SECONDS",
    "ATTACHMENT_MAX_BYTES",
    "DB_PASSWORD", "SESSION_SECRET",
)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """cwd를 tmp_path로 옮기고 설정 관련 env var를 비운 격리 환경."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _write_config(tmp_path):
    (tmp_path / "config.yml").write_text(CONFIG_YML, encoding="utf-8")
    (tmp_path / ".env").write_text(ENV_FILE, encoding="utf-8")


def test_attachment_archive_root_loads_default(isolated):
    """config.yml에서 생략 시 보관 루트 기본값이 로드된다 (7.5·7.6)."""
    _write_config(isolated)
    s = Settings()
    assert isinstance(s.attachment_archive_root, str)
    assert s.attachment_archive_root  # 비어있지 않은 기본 경로


def test_attachment_sweep_interval_default_is_3600(isolated):
    """생략 시 아카이브 스윕 주기 기본값이 3600초로 로드된다 (7.5)."""
    _write_config(isolated)
    s = Settings()
    assert s.attachment_sweep_interval_seconds == 3600
    assert isinstance(s.attachment_sweep_interval_seconds, int)


def test_attachment_sweep_interval_allows_disable_value(isolated):
    """0 이하 값이 표현 가능하다 → 인프로세스 스케줄러 비활성 계약 (7.5)."""
    _write_config(isolated)
    s = Settings(attachment_sweep_interval_seconds=0)
    assert s.attachment_sweep_interval_seconds == 0


def test_attachment_max_bytes_has_default(isolated):
    """생략 시 업로드 크기 한도 기본값이 양수 int로 로드된다 (7.5)."""
    _write_config(isolated)
    s = Settings()
    assert isinstance(s.attachment_max_bytes, int)
    assert s.attachment_max_bytes > 0


def test_file_storage_root_reused_for_attachments(isolated):
    """저장 루트는 신규 필드가 아니라 기존 file_storage_root 를 재사용한다 (7.6)."""
    _write_config(isolated)
    s = Settings()
    assert s.file_storage_root == "./var/attachments"


def test_existing_settings_contract_preserved(isolated):
    """additive 추가가 기존 Settings 필드 계약(기본값)을 그대로 유지한다 (7.6)."""
    _write_config(isolated)
    s = Settings()
    assert s.default_trash_retention_days == 30
    assert s.trash_sweep_interval_seconds == 3600
    assert s.session_cookie_name == "session"
    assert s.session_max_age_seconds == 1209600
    assert s.db_port == 3306
