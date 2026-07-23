"""배치 실행 주기 설정의 s01 단일 Settings additive 확장 단위 테스트 (Requirement 6.7).

`trash_sweep_interval_seconds`는 모듈별 설정 파일이 아니라 s01 공용 Settings에
additive로 추가된다. 보관일 기본값은 기존 `default_trash_retention_days`(30)를 재사용한다.

각 테스트는 개발자 로컬의 실제 backend/config.yml·.env에 의존하지 않도록
tmp_path로 격리한다(monkeypatch.chdir + secret env var 제거).
"""

import pytest

from app.config import Settings, get_settings

# trash_sweep_interval_seconds는 의도적으로 생략 → 스키마 기본값(3600) 검증
CONFIG_YML = """\
app_name: markspace
db_host: 127.0.0.1
db_port: 3306
db_name: markspace
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


def test_sweep_interval_default_is_3600(isolated):
    """config.yml에서 생략 시 배치 실행 주기 기본값이 3600초로 로드된다 (6.7)."""
    _write_config(isolated)
    s = Settings()
    assert s.trash_sweep_interval_seconds == 3600
    assert isinstance(s.trash_sweep_interval_seconds, int)


def test_sweep_interval_override_allows_disable_value(isolated):
    """0 이하 값이 표현 가능하다 → 인프로세스 스케줄러 비활성 계약 (6.7)."""
    _write_config(isolated)
    s = Settings(trash_sweep_interval_seconds=0)
    assert s.trash_sweep_interval_seconds == 0


def test_existing_settings_contract_preserved(isolated):
    """additive 추가가 기존 Settings 필드 계약(기본값)을 그대로 유지한다 (6.7)."""
    _write_config(isolated)
    s = Settings()
    # 보관일 기본값은 신규 필드가 아니라 기존 필드를 재사용한다
    assert s.default_trash_retention_days == 30
    assert s.session_cookie_name == "session"
    assert s.session_max_age_seconds == 1209600
    assert s.db_port == 3306
