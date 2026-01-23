"""
Entry point for the ytdlp-microservice.

Run this file directly to start the FastAPI server:
    python main.py
    python -m main

Or use uvicorn directly:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

import sys

import uvicorn

from app.config import settings


def main() -> None:
    """
    Start the uvicorn server.

    Server configuration can be overridden via environment variables:
    - HOST: Server host (default: 0.0.0.0)
    - PORT: Server port (default: 8000)
    - YTDLP_SLEEP_SECONDS: Sleep interval for anti-bot detection
    - YTDLP_IMPERSONATE_TARGET: Browser to impersonate (default: chrome)
    """
    import os

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    print("=" * 60)
    print("YouTube Subtitle Microservice")
    print("=" * 60)
    print(f"Starting server on http://{host}:{port}")
    print(f"Anti-blocking config:")
    print(f"  - Impersonate: {settings.ytdlp_impersonate_target}")
    print(f"  - Sleep: {settings.ytdlp_sleep_seconds}s")
    print("=" * 60)

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
