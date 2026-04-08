from pathlib import Path

from pydantic_settings import BaseSettings

# Look for .env in backend/ first, then project root (ads-platform/)
_backend_dir = Path(__file__).resolve().parent.parent
_project_root = _backend_dir.parent
_env_file = _backend_dir / ".env" if (_backend_dir / ".env").exists() else _project_root / ".env"


class Settings(BaseSettings):
    # Database
    POSTGRES_CONNECTION_STRING: str = "postgresql://postgres:password@localhost:5432/ads_platform"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Meta Ads API — per-branch tokens
    META_ACCESS_TOKEN_SAIGON: str = ""
    META_AD_ACCOUNT_SAIGON: str = ""
    META_ACCESS_TOKEN_OANI: str = ""
    META_AD_ACCOUNT_OANI: str = ""
    META_ACCESS_TOKEN_OSAKA: str = ""
    META_AD_ACCOUNT_OSAKA: str = ""
    META_ACCESS_TOKEN_TAIPEI: str = ""
    META_AD_ACCOUNT_TAIPEI: str = ""
    META_ACCESS_TOKEN_1948: str = ""
    META_AD_ACCOUNT_1948: str = ""
    META_ACCESS_TOKEN_BREAD: str = ""
    META_AD_ACCOUNT_BREAD: str = ""

    # Google Ads API (Phase 4)
    GOOGLE_DEVELOPER_TOKEN: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REFRESH_TOKEN: str = ""
    GOOGLE_LOGIN_CUSTOMER_ID: str = ""

    # TikTok Ads API (Phase 4)
    TIKTOK_APP_ID: str = ""
    TIKTOK_APP_SECRET: str = ""
    TIKTOK_ACCESS_TOKEN: str = ""

    # Claude API
    ANTHROPIC_API_KEY: str = ""

    # JWT Auth
    JWT_SECRET_KEY: str = "change-me-to-a-random-32-char-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24

    # SMTP (Email notifications)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_NAME: str = "Meander Ads Platform"

    # App Config
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "info"

    # Frontend
    NEXT_PUBLIC_API_BASE_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"

    # Figma API (Phase 6)
    FIGMA_ACCESS_TOKEN: str = ""
    FIGMA_TEAM_ID: str = ""

    # Export API
    EXPORT_API_RATE_LIMIT_DAILY: int = 1000

    # Sync
    SYNC_INTERVAL_MINUTES: int = 15

    model_config = {"env_file": str(_env_file), "extra": "ignore"}


settings = Settings()
