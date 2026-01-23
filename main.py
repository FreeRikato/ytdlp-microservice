"""
Entry point for the ytdlp-microservice.

Run this file directly to start the FastAPI server:
    uv run python main.py
    uv run uvicorn app.main:app

Or use uvicorn directly:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

import uvicorn

from app.config import settings


def main() -> None:
    """
    Start the uvicorn server with settings from configuration.

    Server configuration can be overridden via environment variables:
    - HOST: Server host (default: 0.0.0.0)
    - PORT: Server port (default: 8000)
    - LOG_LEVEL: Logging level (default: info)
    - YTDLP_SLEEP_SECONDS: Sleep interval for anti-bot detection
    - YTDLP_IMPERSONATE_TARGET: Browser to impersonate (default: chrome)
    """
    print("=" * 60)
    print("YouTube Subtitle Microservice")
    print("=" * 60)
    print(f"Starting server on http://{settings.host}:{settings.port}")
    print("Configuration:")
    print(f"  - Host: {settings.host}")
    print(f"  - Port: {settings.port}")
    print(f"  - Log Level: {settings.log_level}")
    print("Anti-blocking config:")
    print(f"  - Impersonate: {settings.ytdlp_impersonate_target}")
    print(f"  - Sleep: {settings.ytdlp_sleep_seconds}s")
    print("Security features:")
    print(f"  - Rate Limiting: {'enabled' if settings.rate_limit_enabled else 'disabled'}")
    print(f"  - Security Headers: {'enabled' if settings.enable_security_headers else 'disabled'}")
    print(f"Cache: {'enabled' if settings.cache_enabled else 'disabled'}")
    print("=" * 60)

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
