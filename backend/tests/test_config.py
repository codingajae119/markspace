"""단일 Settings 로더 단위 테스트 (Requirement 2.1~2.6).

각 테스트는 개발자 로컬의 실제 backend/config.yml·.env에 의존하지 않도록
tmp_path로 격리한다(monkeypatch.chdir + secret env var 제거).
"""

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings

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


def _write_config(tmp_path, with_env=True):
    (tmp_path / "config.yml").write_text(CONFIG_YML, encoding="utf-8")
    if with_env:
        (tmp_path / ".env").write_text(ENV_FILE, encoding="utf-8")


def test_loads_config_yml_and_env(isolated):
    """config.yml + .env 로드 시 필드 값·기본값이 채워진다 (2.1, 2.2)."""
    _write_config(isolated)
    s = Settings()

    assert s.app_name == "markspace"
    assert s.db_host == "127.0.0.1"
    assert s.db_port == 3306
    assert s.db_name == "markspace"
    assert s.db_user == "root"
    assert s.default_trash_retention_days == 30
    assert s.file_storage_root == "./var/attachments"
    assert s.session_cookie_name == "session"
    assert s.session_max_age_seconds == 1209600
    # secret은 .env에서만 온다 (2.3)
    assert s.db_password == "secret-pw"
    assert s.session_secret == "secret-session-value"


def test_defaults_applied_when_omitted(isolated):
    """선택 항목은 config.yml에서 빠져도 스키마 기본값이 적용된다 (2.6)."""
    minimal = (
        "app_name: markspace\n"
        "db_host: 127.0.0.1\n"
        "db_name: markspace\n"
        "db_user: root\n"
        "file_storage_root: ./var/attachments\n"
    )
    (isolated / "config.yml").write_text(minimal, encoding="utf-8")
    (isolated / ".env").write_text(ENV_FILE, encoding="utf-8")

    s = Settings()
    assert s.db_port == 3306
    assert s.default_trash_retention_days == 30
    assert s.session_cookie_name == "session"
    assert s.session_max_age_seconds == 1209600


def test_sqlalchemy_url(isolated):
    """sqlalchemy_url이 pymysql DSN을 조립한다 (2.5)."""
    _write_config(isolated)
    s = Settings()
    assert s.sqlalchemy_url == (
        "mysql+pymysql://root:secret-pw@127.0.0.1:3306/markspace?charset=utf8mb4"
    )


def test_missing_secret_fails_fast(isolated):
    """필수 secret 누락 시 인스턴스화가 ValidationError로 실패한다 (2.4)."""
    _write_config(isolated, with_env=False)  # .env 없음, secret env도 fixture가 제거함
    with pytest.raises(ValidationError) as exc:
        Settings()
    msg = str(exc.value)
    assert "db_password" in msg
    assert "session_secret" in msg


def test_get_settings_is_cached_singleton(isolated):
    """get_settings()는 캐시된 단일 인스턴스를 반환한다 (2.5)."""
    _write_config(isolated)
    first = get_settings()
    second = get_settings()
    assert first is second
    assert isinstance(first, Settings)
