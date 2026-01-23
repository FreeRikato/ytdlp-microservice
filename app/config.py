"""
Configuration module for ytdlp-microservice.

Uses pydantic-settings to load configuration from environment variables.
This allows runtime tuning of anti-bot detection strategies without code changes.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings with environment variable support.

    Environment Variables:
        YTDLP_SLEEP_SECONDS: Time to sleep between subtitle requests (default: 60)
            Higher values reduce 429 errors but slow down responses.
            References GitHub issues #13831, #13770 for context.

        YTDLP_IMPERSONATE_TARGET: Browser to impersonate for TLS fingerprinting (default: "chrome")
            Valid options: "chrome", "chrome-110", "safari", "edge", etc.
            This bypasses YouTube's Python request detection via TLS fingerprint matching.

        YTDLP_TEMP_DIR: Directory for temporary subtitle files (default: system temp)
            Must be writable. Files are cleaned up after each request.
    """

    # Strategy B: Aggressive Throttling - stay under YouTube's bot detection threshold
    # 60 seconds is conservative; can be tuned based on observed 429 error rates
    ytdlp_sleep_seconds: int = 60

    # Strategy A: Browser Impersonation - TLS fingerprint spoofing
    # "chrome" is the most reliable target for bypassing bot detection
    ytdlp_impersonate_target: str = "chrome"

    # Temporary directory for subtitle downloads (auto-cleaned after each request)
    ytdlp_temp_dir: str | None = None

    model_config = SettingsConfigDict(
        env_prefix="YTDLP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Global settings instance - loaded at startup with environment variables
settings = Settings()
