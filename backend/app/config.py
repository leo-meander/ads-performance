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

    # Email (Resend HTTP API)
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = ""

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

    # Canva Connect API (winning-ads regenerate flow)
    # When CANVA_API_TOKEN is empty the client runs in stub mode: it returns
    # a deterministic mock URL so the regenerate flow is testable end-to-end
    # without OAuth setup. Production needs a Canva Enterprise org with the
    # Connect app installed; the token is the org-scoped OAuth access token.
    CANVA_API_TOKEN: str = ""
    CANVA_API_BASE_URL: str = "https://api.canva.com/rest/v1"

    # PMS (Reservation system)
    PMS_API_BASE_URL: str = "https://meander-hid-dashboard.zeabur.app"
    PMS_API_KEY: str = ""

    # Export API
    EXPORT_API_RATE_LIMIT_DAILY: int = 1000

    # yt-dlp (video transcription)
    YTDLP_COOKIES_FROM_BROWSER: str = ""  # e.g. "chrome", "firefox" — local dev
    YTDLP_COOKIES_FILE: str = ""  # path to cookies.txt — for deployment

    # Sync
    SYNC_INTERVAL_MINUTES: int = 15

    # Internal scheduled-task endpoints (Zeabur cron hits these with X-Internal-Secret header)
    INTERNAL_TASK_SECRET: str = ""

    # Microsoft Clarity — Data Export API + tracking snippet
    # Token: long-lived JWT with scope=Data.Export issued in Clarity settings.
    #        See Settings > Data Export API in the Clarity project dashboard.
    # Project ID: the 16-digit tracking id embedded in the Clarity JS snippet
    #             (same value as the token's `sub` claim).
    CLARITY_API_TOKEN: str = ""
    CLARITY_PROJECT_ID: str = ""

    # Google Analytics 4 Data API — service account JSON as base64.
    # Base64 used because the raw JSON contains newlines in private_key which
    # some deploy targets (Zeabur UI text field) don't preserve correctly.
    # Also accept raw JSON in GA4_SERVICE_ACCOUNT_JSON as a fallback — the
    # code decodes whichever is set.
    GA4_SERVICE_ACCOUNT_JSON_B64: str = ""
    GA4_SERVICE_ACCOUNT_JSON: str = ""

    model_config = {"env_file": str(_env_file), "extra": "ignore"}


settings = Settings()
