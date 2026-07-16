"""Alembic 마이그레이션 환경 (s01-contract-foundation, Task 2.2).

DB 접속 URL 은 ``alembic.ini`` 가 아니라 :func:`app.config.get_settings` 의
``sqlalchemy_url`` 에서 주입한다(단일 설정 소스, 크리덴셜 하드코딩 금지).
``app.models`` 를 import 하여 ``Base.metadata`` 에 7개 테이블을 등록한 뒤
``target_metadata`` 로 사용한다(autogenerate 대조 기준). offline·online 모드 지원.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.common.db import Base
from app.config import get_settings

# app.models 를 import 하는 것만으로 모든 모델 클래스가 Base.metadata 에 등록된다.
import app.models  # noqa: F401  (side-effect import: populate Base.metadata)

# Alembic Config 객체(alembic.ini 값 접근).
config = context.config

# 로깅 설정(alembic.ini 의 [loggers] 등).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate·비교 대상 메타데이터 = 전체 ORM 스키마.
target_metadata = Base.metadata

# DB URL 은 오직 Settings 에서 주입(ini 의 sqlalchemy.url 은 비어 있음).
DB_URL = get_settings().sqlalchemy_url


def run_migrations_offline() -> None:
    """오프라인(SQL 스크립트 방출) 모드로 마이그레이션 실행."""
    context.configure(
        url=DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """온라인(실제 커넥션) 모드로 마이그레이션 실행."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = DB_URL
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
