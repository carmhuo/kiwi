import secrets
import warnings
from typing import Annotated, Any, Literal, Dict

from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    HttpUrl,
    computed_field,
    model_validator,
)
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self

from kiwi.core.logger import Logger


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )
    # 应用配置
    PROJECT_NAME: str = "Kiwi_App"
    VERSION: str = "v1.0.0"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    API_V1_STR: str = "/api/v1"

    SECRET_KEY: str = secrets.token_urlsafe(32)
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8

    FRONTEND_HOST: str = "http://localhost:5173"
    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    SENTRY_DSN: HttpUrl | None = None

    # 数据库配置
    DATABASE_TYPE: Literal["postgresql", "sqlite"] = "sqlite"
    DEBUG: bool = True

    SQLITE_DB_PATH: str = "kiwi.sqlite.db"

    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        """Return database URI based on DATABASE_TYPE setting"""
        if self.DATABASE_TYPE == "postgresql":
            # PostgreSQL connection
            return str(
                MultiHostUrl.build(
                    scheme="postgresql+asyncpg",
                    username=self.POSTGRES_USER,
                    password=self.POSTGRES_PASSWORD,
                    host=self.POSTGRES_SERVER,
                    port=self.POSTGRES_PORT,
                    path=self.POSTGRES_DB,
                )
            )
        if self.DATABASE_TYPE == "sqlite":
            return f"sqlite+aiosqlite:///{self.SQLITE_DB_PATH}"
        else:
            raise ValueError(f"Unsupported Database Type: {self.DATABASE_TYPE}")

    # 缓存配置
    CACHE_ENABLED: bool = True
    CACHE_TYPE: str = "memory" if ENVIRONMENT == "local" else "redis"
    REDIS_URL: str = "redis://localhost:6379"
    # Agent配置
    AGENT_DEFAULT_CONFIG: dict = {
        "TEXT2SQL": {"model": "gpt-4", "temperature": 0.7},
        "RETRIEVAL": {"top_k": 5}
    }
    VERSION_POLICY: str = "semantic"  # 版本策略
    OPENAI_API_KEY: str | None = None

    # 日志配置
    LOG_LEVEL: str = "DEBUG"
    LOG_TO_FILE: bool = True
    LOG_FILE_PATH: str = "logs/application.log"
    LOG_FORMAT: str = "text" if ENVIRONMENT == "local" else "json"  # 或 "text"

    # 邮件配置
    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: EmailStr | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    # 用户初始化配置
    TEST_USERNAME: str = "testuser"
    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: str
    FIRST_SUPERUSER_EMAIL: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _validate_database_settings(self) -> Self:
        """Validate database settings based on selected type"""
        if self.DATABASE_TYPE == "postgresql":
            # Validate required PostgreSQL settings
            required_postgres_settings = [
                ("POSTGRES_SERVER", self.POSTGRES_SERVER),
                ("POSTGRES_USER", self.POSTGRES_USER),
                ("POSTGRES_DB", self.POSTGRES_DB),
            ]

            for name, value in required_postgres_settings:
                if not value:
                    raise ValueError(
                        f"{name} is required when using PostgreSQL database"
                    )
        return self

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self

    # DuckDB配置
    DUCKDB_CONNECTION_POOL_SIZE: int = 10
    DUCKDB_CONNECTION_POOL_TIMEOUT: int = 30
    DUCKDB_CONFIG: Dict[str, Any] = {
        "max_connections": 50,  # 根据服务器内存调整(每个连接约10-50MB)
        "min_connections": 10,
        "connection_timeout": 10,
        "query_timeout": 60,
        "extensions": ['httpfs', 'sqlite', 'postgres', 'parquet', 'mysql', 'excel'],
        "enable_httpfs": True,
    }

    VECTOR_STORE_TYPE: str = "chromadb"
    VECTOR_STORE_CONFIG: Dict[str, Any] = {
        "n_results": 10,
    }

    STORAGE_PATH: str = "../storage" if ENVIRONMENT == "local" else '/opt/kiwi/uploads/file'
    FILE_SERVER_URL: str = "http://localhost:8000/files"
    IMAGE_PATH: str = "../img" if ENVIRONMENT == "local" else '/opt/kiwi/img'


settings = Settings()  # type: ignore

logger = Logger(
    name=settings.PROJECT_NAME,
    level=settings.LOG_LEVEL,
    log_to_console=True,
    log_to_file=settings.LOG_TO_FILE,
    log_file_path=settings.LOG_FILE_PATH,
    log_format=settings.LOG_FORMAT,
    extra_fields={"app": settings.PROJECT_NAME, "environment": settings.ENVIRONMENT}
)
