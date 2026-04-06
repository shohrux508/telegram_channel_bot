from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Единая конфигурация приложения.

    Все значения загружаются из .env и доступны через ``from app.config import settings``.
    """

    # ── Запуск компонентов ───────────────────────────────────────────────
    RUN_TELEGRAM: bool = True
    RUN_API: bool = True

    # ── Telegram ─────────────────────────────────────────────────────────
    BOT_TOKEN: str | None = None

    # ── API ──────────────────────────────────────────────────────────────
    API_HOST: str = "0.0.0.0"
    API_PORT: int = Field(default=8000, alias="PORT", validation_alias="PORT")


    # ── AI / LLM ─────────────────────────────────────────────────────────
    LLM_PROVIDER: str = "openai"        # openai | anthropic
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_BASE_URL: str | None = None     # Для self-hosted / proxy

    # ── RAG / Qdrant ─────────────────────────────────────────────────────
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str | None = None
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    # ── MQTT ─────────────────────────────────────────────────────────────
    MQTT_HOST: str = "localhost"
    MQTT_PORT: int = 1883
    MQTT_USER: str | None = None
    MQTT_PASSWORD: str | None = None

    # ── WebSocket ────────────────────────────────────────────────────────
    WS_URL: str = "ws://localhost:8080/ws"

    # ── Redis ────────────────────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    REDIS_KEY_PREFIX: str = ""
    REDIS_PUB_URL: str | None = None  # Railway public Redis URL
    REDIS_URL: str | None = None      # Railway internal/Standard Redis URL

    # ── Manifesto Publisher ───────────────────────────────────────────────
    MANIFESTO_ADMIN_ID: int = 0       # Telegram ID администратора
    MANIFESTO_CODE_LENGTH: int = 8    # Длина генерируемого short_code

    # ── HTTP ─────────────────────────────────────────────────────────────
    HTTP_TIMEOUT: float = 30.0

    # ── Логирование ──────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str | None = None
    LOG_JSON: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
