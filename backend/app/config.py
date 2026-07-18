"""단일 설정 로더 (Requirement 2).

비밀이 아닌 값은 ``config.yml``에서, secret 값은 ``.env``에서 읽어 하나의
불변 :class:`Settings` 객체로 결합한다. 애플리케이션 코드는 오직
:func:`get_settings` 를 통해서만 설정을 읽는다(``os.environ`` 직접 접근 금지).

우선순위(높음→낮음): init 인자 > 환경변수 > .env > config.yml.
필수 항목 누락 시 인스턴스화 시점에 pydantic ``ValidationError`` 로 fail-fast 한다.
"""

from functools import lru_cache

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        yaml_file="config.yml",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- config.yml (비밀 아님) ---
    app_name: str
    db_host: str
    db_port: int = 3306
    db_name: str
    db_user: str
    default_trash_retention_days: int = 30
    trash_sweep_interval_seconds: int = 3600  # 배치 실행 주기(초). 0 이하이면 인프로세스 스케줄러 비활성(외부 cron 신호)
    file_storage_root: str  # 첨부 파일 저장 루트(WS별 격리 하위 디렉터리)
    # s12-attachment additive 확장(비파괴적). 저장 루트는 file_storage_root 재사용.
    attachment_archive_root: str = "./var/attachments_archive"  # 보관 폴더 루트(WS별 격리)
    attachment_sweep_interval_seconds: int = 3600  # 아카이브 스윕 주기(초). 0 이하이면 인프로세스 스케줄러 비활성(외부 cron 신호)
    attachment_max_bytes: int = 26214400  # 업로드 크기 한도(바이트, 기본 25MiB)
    # s14-sharing additive 확장(비파괴적). 새 DB 마이그레이션·모듈별 설정 파일 없음.
    share_token_bytes: int = 32  # 공유 토큰 생성 바이트 수(secrets.token_urlsafe, token VARCHAR(64) 내 적재)
    share_invalidation_sweep_interval_seconds: int = 3600  # 무효화 스윕 주기(초). 0 이하이면 인프로세스 스케줄러 비활성(외부 cron 신호)
    session_cookie_name: str = "session"
    session_max_age_seconds: int = 1209600  # 14d
    # user_setting additive 확장(비파괴적). user_setting 레코드가 없을 때 반환할
    # 사용자별 autosave 기본값(도메인 서비스가 이 값으로 대체한다).
    default_autosave_enabled: bool = False

    # --- .env (secret) ---
    db_password: str
    session_secret: str

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # 우선순위: init > env > .env > config.yml (YAML은 최하위)
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
        )

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    """단일 접근자. 애플리케이션 전역에서 동일 인스턴스를 반환(캐시)한다."""
    return Settings()
