"""
Configuration module for ytdlp-microservice.

Uses pydantic-settings to load configuration from environment variables.
This allows runtime tuning of anti-bot detection strategies without code changes.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings with environment variable support.

    Note: The env_prefix is set to "YTDLP_" but populate_by_name=True allows
    using field names directly. All settings can be set via either:
    - Prefixed: YTDLP_<SETTING_NAME> (e.g., YTDLP_CACHE_ENABLED)
    - Unprefixed: <SETTING_NAME> or <alias> (e.g., CACHE_ENABLED or HOST)
    - In .env file without prefix (recommended for brevity)

    Environment Variables:
        HOST: Server host (default: 0.0.0.0)
        PORT: Server port (default: 8000)
        LOG_LEVEL: Logging level (default: info)
        SLEEP_SECONDS: Time to sleep between subtitle requests (default: 60)
            Higher values reduce 429 errors but slow down responses.
            References GitHub issues #13831, #13770 for context.
        IMPERSONATE_TARGET: Browser to impersonate for TLS fingerprinting (default: "chrome")
            Valid options: "chrome", "chrome-110", "safari", "edge", etc.
            This bypasses YouTube's Python request detection via TLS fingerprint matching.
        TEMP_DIR: Directory for temporary subtitle files (default: system temp)
            Must be writable. Files are cleaned up after each request.
        REQUEST_TIMEOUT: Request timeout in seconds (default: 120)
        RATE_LIMIT_ENABLED: Enable rate limiting (default: true)
        RATE_LIMIT_PER_MINUTE: Requests per minute per IP (default: 10)
        ENABLE_SECURITY_HEADERS: Enable security headers middleware (default: true)
        CACHE_ENABLED: Enable response caching (default: true)
        CACHE_TTL: Cache TTL in seconds (default: 3600)
        CACHE_MAXSIZE: Maximum cache entries (default: 1000)
    """

    # ========== Server Configuration ==========

    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")
    log_level: str = Field(default="info", alias="LOG_LEVEL")

    # ========== YouTube Extraction Settings ==========

    # Strategy B: Aggressive Throttling - stay under YouTube's bot detection threshold
    # 60 seconds is conservative; can be tuned based on observed 429 error rates
    ytdlp_sleep_seconds: int = 60

    # Strategy A: Browser Impersonation - TLS fingerprint spoofing
    # "chrome" is the most reliable target for bypassing bot detection
    ytdlp_impersonate_target: str = "chrome"

    # Temporary directory for subtitle downloads (auto-cleaned after each request)
    ytdlp_temp_dir: str | None = None

    # Request timeout for yt-dlp operations
    ytdlp_request_timeout: int = 120

    # ========== Security Settings ==========

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 10

    # Security headers middleware
    enable_security_headers: bool = True

    # ========== Caching Settings ==========

    # Response caching
    cache_enabled: bool = True
    cache_ttl: int = 3600  # 1 hour in seconds
    cache_maxsize: int = 1000  # Maximum number of cached entries
    redis_url: str | None = None  # Optional Redis backend for future use

    # ========== Database Settings ==========

    # SQLite database file path (relative to app directory or absolute)
    database_path: str = "database.db"

    model_config = SettingsConfigDict(
        env_prefix="YTDLP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,  # Allow using field names or aliases
    )


# Global settings instance - loaded at startup with environment variables
settings = Settings()
