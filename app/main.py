"""
FastAPI application for YouTube subtitle extraction.

This module provides a REST API endpoint for extracting subtitles from
YouTube videos with anti-bot detection strategies.
"""

import logging
from contextlib import asynccontextmanager
from enum import Enum
from typing import cast

import yt_dlp
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.service import SubtitleEntry, SubtitleExtractor, get_extractor
from app.utils import is_valid_youtube_url

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Lifespan Context Manager
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan events."""
    # Startup
    from app.config import settings

    logger.info("=" * 60)
    logger.info("YouTube Subtitle Microservice Starting")
    logger.info("=" * 60)
    logger.info("Anti-blocking strategies configured:")
    logger.info(f"  - Browser Impersonation: {settings.ytdlp_impersonate_target}")
    logger.info(f"  - Sleep Interval: {settings.ytdlp_sleep_seconds}s")
    logger.info(f"  - Client Source: default,-web (PO Token bypass)")
    logger.info("=" * 60)

    yield

    # Shutdown (if needed)


# Create FastAPI app
app = FastAPI(
    title="YouTube Subtitle Microservice",
    description="Extract subtitles from YouTube videos with anti-bot detection",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ============================================================================
# Pydantic Models
# ============================================================================


class SubtitleEntryModel(BaseModel):
    """A single subtitle entry with timing and text."""

    start: str = Field(..., description="Start timestamp in VTT format (HH:MM:SS.mmm)")
    end: str = Field(..., description="End timestamp in VTT format (HH:MM:SS.mmm)")
    text: str = Field(..., description="The subtitle text content")

    model_config = {"json_schema_extra": {"example": {"start": "00:00:00.000", "end": "00:00:03.500", "text": "Hello world"}}}


class SubtitleResponse(BaseModel):
    """Response model for subtitle data in JSON format."""

    video_id: str = Field(..., description="YouTube video ID (11 characters)")
    language: str = Field(..., description="Language code of the subtitles")
    subtitle_count: int = Field(..., description="Number of subtitle entries")
    subtitles: list[SubtitleEntryModel] = Field(..., description="List of subtitle entries")

    model_config = {
        "json_schema_extra": {
            "example": {
                "video_id": "dQw4w9WgXcQ",
                "language": "en",
                "subtitle_count": 2,
                "subtitles": [
                    {"start": "00:00:00.000", "end": "00:00:03.500", "text": "Hello world"},
                    {"start": "00:00:03.500", "end": "00:00:07.000", "text": "This is a test"},
                ],
            }
        }
    }


class ErrorResponse(BaseModel):
    """Error response model."""

    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Human-readable error message")
    detail: str | None = Field(None, description="Additional error details")


class OutputFormat(str, Enum):
    """Supported output formats for subtitles."""

    json = "json"
    vtt = "vtt"


# ============================================================================
# Exception Handlers
# ============================================================================


@app.exception_handler(yt_dlp.utils.DownloadError)
async def download_error_handler(request: Request, exc: yt_dlp.utils.DownloadError):
    """
    Handle yt-dlp download errors, specifically HTTP 429 rate limiting.

    Returns:
        503 Service Unavailable for HTTP Error 429
        500 Internal Server Error for other download errors
    """
    from app.config import settings

    error_msg = str(exc)

    # Check specifically for HTTP 429 - rate limit error
    if "HTTP Error 429" in error_msg:
        logger.warning(f"Rate limit detected (429): {error_msg}")
        error_response = ErrorResponse(
            error="rate_limit_exceeded",
            message=f"Upstream Rate Limit Detected. Please retry in {settings.ytdlp_sleep_seconds} seconds.",
        )
        return Response(
            content=error_response.model_dump_json(),
            status_code=503,
            media_type="application/json",
        )

    # Log other download errors
    logger.error(f"Download error: {error_msg}")
    error_response = ErrorResponse(
        error="download_failed",
        message="Failed to download subtitles",
        detail=error_msg[:200],
    )
    return Response(
        content=error_response.model_dump_json(),
        status_code=500,
        media_type="application/json",
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors."""
    logger.warning(f"Validation error: {exc}")
    error_response = ErrorResponse(
        error="validation_error",
        message="Invalid request parameters",
    )
    return Response(
        content=error_response.model_dump_json(),
        status_code=400,
        media_type="application/json",
    )


# ============================================================================
# API Endpoints
# ============================================================================


@app.get(
    "/api/v1/subtitles",
    response_model=SubtitleResponse,
    responses={
        200: {"description": "Subtitles extracted successfully"},
        400: {"model": ErrorResponse, "description": "Invalid URL or parameters"},
        404: {"model": ErrorResponse, "description": "Subtitles not found"},
        429: {"model": ErrorResponse, "description": "Too many requests"},
        503: {"model": ErrorResponse, "description": "Upstream rate limit (YouTube)"},
    },
    summary="Extract subtitles from a YouTube video",
)
async def get_subtitles(
    video_url: str = Query(..., description="YouTube video URL (e.g., https://www.youtube.com/watch?v=xxx)"),
    lang: str = Query("en", description="Language code for subtitles (e.g., en, es, fr)"),
    format: OutputFormat = Query(OutputFormat.json, description="Output format: json or vtt"),
) -> SubtitleResponse | PlainTextResponse:
    """
    Extract subtitles from a YouTube video.

    This endpoint downloads and returns subtitles for the specified video.
    It implements anti-bot detection strategies to bypass YouTube's rate limiting.

    **Parameters:**
    - **video_url**: Full YouTube URL or video ID
    - **lang**: Language code (default: "en")
    - **format**: Response format - "json" for structured data, "vtt" for raw WebVTT

    **Anti-Blocking Strategies:**
    1. Browser impersonation (TLS fingerprint spoofing)
    2. Request throttling (configurable sleep interval)
    3. Client source spoofing (bypass PO Token requirement)
    4. Graceful error fallbacks

    **Example Usage:**
    ```bash
    # JSON format
    curl "http://localhost:8000/api/v1/subtitles?video_url=https://www.youtube.com/watch?v=dQw4w9WgXcQ&lang=en&format=json"

    # VTT format
    curl "http://localhost:8000/api/v1/subtitles?video_url=https://www.youtube.com/watch?v=dQw4w9WgXcQ&lang=en&format=vtt"
    ```

    **Response Codes:**
    - 200: Success
    - 400: Invalid URL or parameters
    - 404: Subtitles not found for the video/language
    - 503: YouTube rate limit detected (retry after 60 seconds)
    """
    # Validate URL
    if not is_valid_youtube_url(video_url):
        logger.warning(f"Invalid URL provided: {video_url}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid YouTube URL: {video_url}. Expected format: https://www.youtube.com/watch?v=VIDEO_ID",
        )

    # Get extractor and run in thread pool (yt-dlp is blocking)
    extractor = get_extractor()

    try:
        # Use run_in_threadpool to avoid blocking the event loop
        # yt-dlp operations are synchronous and CPU-intensive
        from starlette.concurrency import run_in_threadpool

        video_id, subtitle_data = await run_in_threadpool(
            extractor.extract_subtitles, video_url, lang, format.value
        )

        # Return based on requested format
        if format == OutputFormat.vtt:
            # Return raw VTT content
            return PlainTextResponse(
                content=cast(str, subtitle_data),
                headers={
                    "Content-Type": "text/vtt; charset=utf-8",
                    "X-Video-ID": video_id,
                },
            )
        else:
            # Convert SubtitleEntry objects to Pydantic models
            subtitle_models = [
                SubtitleEntryModel(start=entry.start, end=entry.end, text=entry.text)
                for entry in cast(list[SubtitleEntry], subtitle_data)
            ]

            return SubtitleResponse(
                video_id=video_id,
                language=lang,
                subtitle_count=len(subtitle_models),
                subtitles=subtitle_models,
            )

    except ValueError as e:
        # No subtitles found or parsing error
        logger.warning(f"Value error during extraction: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except yt_dlp.utils.DownloadError as e:
        # Let the global handler handle this
        raise e


@app.get("/", summary="Health check")
async def root() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "ytdlp-microservice", "version": "0.1.0"}


@app.get("/health", summary="Health check endpoint")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "ytdlp-microservice", "version": "0.1.0"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
