"""
FastAPI application for YouTube subtitle extraction.

This module provides a REST API endpoint for extracting subtitles from
YouTube videos with anti-bot detection strategies.
"""

import asyncio
import logging
import re
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from contextvars import ContextVar
from enum import Enum
from typing import TYPE_CHECKING, cast

import yt_dlp
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars

if TYPE_CHECKING:
    from app.service import VideoMetadata

from app.service import SubtitleEntry, get_extractor
from app.utils import is_valid_youtube_url

# Caching
from app.cache import cache

# Rate limiting
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Import database lifecycle for startup/shutdown
from app.database import db_lifecycle, db_engine

# Configure logging with request ID context
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger()

# Request ID context variable
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_remote_address_proxied(request: Request) -> str:
    """Get client address, considering X-Forwarded-For header."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host


# Initialize rate limiter with proxy support
limiter = Limiter(key_func=get_remote_address_proxied)
rate_limit_exception_handler = _rate_limit_exceeded_handler

# Track app startup time for uptime calculation
_app_start_time = time.time()

# Simple in-memory rate limiting tracker (for conditional rate limiting)
_rate_limit_tracker: defaultdict[str, list[float]] = defaultdict(list)
_rate_limit_lock = asyncio.Lock()
_MAX_TRACKED_IPS = 10000  # Prevent memory leak from unbounded growth


async def _check_rate_limit(ip: str, max_requests: int, window_seconds: int = 60) -> bool:
    """
    Check if the IP has exceeded the rate limit.

    Args:
        ip: Client IP address
        max_requests: Maximum requests allowed
        window_seconds: Time window in seconds

    Returns:
        True if request is allowed, False if rate limit exceeded
    """
    async with _rate_limit_lock:
        now = time.time()
        # Clean old entries
        _rate_limit_tracker[ip] = [
            t for t in _rate_limit_tracker[ip] if now - t < window_seconds
        ]
        # Check limit
        if len(_rate_limit_tracker[ip]) >= max_requests:
            return False
        # Add current request
        _rate_limit_tracker[ip].append(now)

        # Prevent memory leak: clean up inactive IPs if tracking too many
        if len(_rate_limit_tracker) > _MAX_TRACKED_IPS:
            inactive_ips = [
                tracked_ip for tracked_ip, timestamps in _rate_limit_tracker.items()
                if all(now - t > window_seconds for t in timestamps)
            ]
            # Remove up to 10% of inactive IPs
            for inactive_ip in inactive_ips[:max(1, _MAX_TRACKED_IPS // 10)]:
                del _rate_limit_tracker[inactive_ip]

        return True


# ============================================================================
# Utility Functions
# ============================================================================


def sanitize_for_log(input_str: str) -> str:
    """
    Sanitize user input for logging to prevent log injection attacks.

    Replaces newlines, carriage returns, and tabs with their escaped
    representations to prevent malicious log injection.

    Args:
        input_str: User input string to sanitize

    Returns:
        Sanitized string safe for logging
    """
    return input_str.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def metadata_to_response_dict(metadata: "VideoMetadata") -> dict:
    """
    Convert VideoMetadata to a dictionary for API responses.

    Args:
        metadata: VideoMetadata object from the extractor

    Returns:
        Dictionary suitable for API response serialization
    """
    return {
        "video_id": metadata.video_id,
        "title": metadata.title,
        "description": metadata.description,
        "duration": metadata.duration,
        "duration_formatted": metadata.duration_formatted,
        "thumbnail": metadata.thumbnail,
        "channel": metadata.channel,
        "channel_id": metadata.channel_id,
        "upload_date": metadata.upload_date,
        "view_count": metadata.view_count,
        "like_count": metadata.like_count,
        "tags": metadata.tags,
        "categories": metadata.categories,
        "webpage_url": metadata.webpage_url,
        "extractor": metadata.extractor,
    }


# ============================================================================
# Lifespan Context Manager
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan events."""
    from app.config import settings

    # Startup
    logger.info("=" * 60)
    logger.info("YouTube Subtitle Microservice Starting")
    logger.info("=" * 60)
    logger.info("Anti-blocking strategies configured:")
    logger.info(f"  - Browser Impersonation: {settings.ytdlp_impersonate_target}")
    logger.info(f"  - Sleep Interval: {settings.ytdlp_sleep_seconds}s")
    logger.info("  - Client Source: default,-web (PO Token bypass)")
    logger.info("Security features:")
    logger.info(f"  - Rate Limiting: {'enabled' if settings.rate_limit_enabled else 'disabled'}")
    logger.info(f"  - Rate Limit: {settings.rate_limit_per_minute}/minute")
    logger.info(f"  - Security Headers: {'enabled' if settings.enable_security_headers else 'disabled'}")
    logger.info("Cache settings:")
    logger.info(f"  - Caching: {'enabled' if settings.cache_enabled else 'disabled'}")
    logger.info(f"  - TTL: {settings.cache_ttl}s")
    logger.info(f"  - Max Size: {settings.cache_maxsize} entries")
    logger.info("Database:")
    logger.info("  - Type: SQLite (async with sqlmodel)")
    logger.info(f"  - File: {settings.database_path}")
    logger.info("=" * 60)

    # Initialize database on startup
    try:
        await db_lifecycle.startup()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    yield

    # Shutdown database
    try:
        await db_lifecycle.shutdown()
    except Exception as e:
        logger.error(f"Error during database shutdown: {e}")
        raise


# Create FastAPI app
app = FastAPI(
    title="YouTube Subtitle Microservice",
    description="Extract subtitles from YouTube videos with anti-bot detection",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ============================================================================
# Middleware Configuration
# ============================================================================


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware to add request ID for tracing."""

    async def dispatch(self, request: Request, call_next):
        """Process request and add request ID."""
        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request_id_var.set(request_id)

        # Clear and bind context vars for structured logging
        clear_contextvars()
        bind_contextvars(request_id=request_id)

        # Add request ID to response headers
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def configure_middleware():
    """Configure middleware based on settings."""
    from app.config import settings
    from app.middleware import SecurityHeadersMiddleware
    from fastapi.middleware.cors import CORSMiddleware

    # Add CORS middleware first (runs first in chain)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info("CORS middleware enabled")

    # Add request ID middleware
    app.add_middleware(RequestIdMiddleware)
    logger.info("Request ID middleware enabled")

    # Add security headers middleware
    if settings.enable_security_headers:
        app.add_middleware(SecurityHeadersMiddleware)
        logger.info("Security headers middleware enabled")

    # Configure rate limiting
    if settings.rate_limit_enabled:
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
        logger.info(f"Rate limiting enabled: {settings.rate_limit_per_minute} requests/minute")


# Configure middleware on import
configure_middleware()


# ============================================================================
# Pydantic Models
# ============================================================================


class SubtitleEntryModel(BaseModel):
    """A single subtitle entry with timing and text."""

    start: str = Field(..., description="Start timestamp in VTT format (HH:MM:SS.mmm)")
    end: str = Field(..., description="End timestamp in VTT format (HH:MM:SS.mmm)")
    text: str = Field(..., description="The subtitle text content")

    model_config = {"json_schema_extra": {"example": {"start": "00:00:00.000", "end": "00:00:03.500", "text": "Hello world"}}}


class VideoMetadataResponse(BaseModel):
    """Video metadata response model."""

    video_id: str = Field(..., description="YouTube video ID (11 characters)")
    title: str = Field(..., description="Video title")
    description: str | None = Field(None, description="Video description")
    duration: int | None = Field(None, description="Video duration in seconds")
    duration_formatted: str | None = Field(None, description="Human-readable duration (HH:MM:SS)")
    thumbnail: str | None = Field(None, description="URL to video thumbnail")
    channel: str | None = Field(None, description="Channel name")
    channel_id: str | None = Field(None, description="Channel ID")
    upload_date: str | None = Field(None, description="Upload date (YYYYMMDD)")
    view_count: int | None = Field(None, description="Number of views")
    like_count: int | None = Field(None, description="Number of likes")
    tags: list[str] = Field(default_factory=list, description="Video tags")
    categories: list[str] = Field(default_factory=list, description="Video categories")
    webpage_url: str | None = Field(None, description="Full video URL")
    extractor: str = Field(default="youtube", description="Source extractor")


class SubtitleResponse(BaseModel):
    """Response model for subtitle data in JSON format."""

    video_id: str = Field(..., description="YouTube video ID (11 characters)")
    language: str = Field(..., description="Language code of the subtitles")
    subtitle_count: int = Field(..., description="Number of subtitle entries")
    subtitles: list[SubtitleEntryModel] = Field(..., description="List of subtitle entries")
    metadata: VideoMetadataResponse | None = Field(None, description="Video metadata")

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
                "metadata": {
                    "video_id": "dQw4w9WgXcQ",
                    "title": "Example Video",
                    "duration": 300,
                    "duration_formatted": "05:00",
                    "channel": "Example Channel",
                    "thumbnail": "https://img.youtube.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
                },
            }
        }
    }


class SubtitleTextResponse(BaseModel):
    """Response model for subtitle data in TEXT format (combined text only)."""

    video_id: str = Field(..., description="YouTube video ID (11 characters)")
    language: str = Field(..., description="Language code of the subtitles")
    text: str = Field(..., description="Combined subtitle text content")
    metadata: VideoMetadataResponse | None = Field(None, description="Video metadata")

    model_config = {
        "json_schema_extra": {
            "example": {
                "video_id": "dQw4w9WgXcQ",
                "language": "en",
                "text": "Hello world This is a test",
                "metadata": {
                    "video_id": "dQw4w9WgXcQ",
                    "title": "Example Video",
                    "duration": 300,
                    "duration_formatted": "05:00",
                    "channel": "Example Channel",
                },
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
    text = "text"


# ============================================================================
# Additional Pydantic Models for New Endpoints
# ============================================================================


class LanguageInfo(BaseModel):
    """Information about an available subtitle language."""

    code: str = Field(..., description="ISO 639-1 language code")
    name: str = Field(..., description="Language name")
    auto_generated: bool = Field(..., description="Whether subtitle is auto-generated")
    formats: list[str] = Field(default_factory=list, description="Available subtitle formats")


class LanguagesResponse(BaseModel):
    """Response model for available languages endpoint."""

    video_id: str = Field(..., description="YouTube video ID")
    languages: list[LanguageInfo] = Field(..., description="Available subtitle languages")


class BatchVideoRequest(BaseModel):
    """Request model for a single video in batch extraction."""

    video_url: str = Field(..., max_length=500, description="YouTube video URL or ID")
    lang: str = Field(default="en", description="Language code")
    format: str = Field(default="json", description="Output format")


class BatchRequest(BaseModel):
    """Request model for batch subtitle extraction."""

    videos: list[BatchVideoRequest] = Field(
        ..., max_length=10, description="List of video requests (max 10)"
    )


class BatchResponseItem(BaseModel):
    """Response item for batch extraction."""

    video_url: str = Field(..., description="The requested video URL")
    success: bool = Field(..., description="Whether extraction succeeded")
    video_id: str | None = Field(None, description="YouTube video ID if successful")
    data: dict | None = Field(None, description="Subtitle data if successful")
    error: str | None = Field(None, description="Error message if failed")


class HealthResponse(BaseModel):
    """Response model for enhanced health check."""

    status: str = Field(..., description="Service status")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    timestamp: float = Field(..., description="Current Unix timestamp")
    uptime_seconds: float = Field(..., description="Service uptime in seconds")
    cache: dict = Field(default_factory=dict, description="Cache statistics")
    rate_limiting: dict = Field(default_factory=dict, description="Rate limiting status")
    database: dict = Field(default_factory=dict, description="Database status")


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
    """
    Handle Pydantic validation errors with detailed feedback.

    Includes specific field and error information to help developers
    understand what went wrong with their request.
    """
    errors = exc.errors()
    logger.warning(f"Validation error: {errors}")

    # Format error details for better developer experience
    error_details = []
    for error in errors:
        loc = " -> ".join(str(x) for x in error["loc"])
        error_details.append(f"{loc}: {error["msg"]}")

    error_response = ErrorResponse(
        error="validation_error",
        message="Invalid request parameters",
        detail="; ".join(error_details),
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
    response_model=None,
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
    request: Request,
    video_url: str = Query(
        ...,
        max_length=500,
        description="YouTube video URL (e.g., https://www.youtube.com/watch?v=xxx)",
    ),
    lang: str = Query(
        "en",
        pattern=r"^[a-z]{2}(-[A-Z]{2})?$",
        max_length=10,
        description="Language code for subtitles (e.g., en, es, en-US)",
    ),
    format: OutputFormat = Query(
        OutputFormat.json, description="Output format: json, vtt, or text"
    ),
) -> SubtitleResponse | SubtitleTextResponse | PlainTextResponse:
    """
    Extract subtitles from a YouTube video.

    This endpoint downloads and returns subtitles for the specified video.
    It implements anti-bot detection strategies to bypass YouTube's rate limiting.

    **Parameters:**
    - **video_url**: Full YouTube URL or video ID
    - **lang**: Language code (default: "en")
    - **format**: Response format - "json" for structured data with timestamps, "vtt" for raw WebVTT, "text" for combined text only

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

    # TEXT format (combined text, no timestamps)
    curl "http://localhost:8000/api/v1/subtitles?video_url=https://www.youtube.com/watch?v=dQw4w9WgXcQ&lang=en&format=text"
    ```

    **Response Codes:**
    - 200: Success
    - 400: Invalid URL or parameters
    - 404: Subtitles not found for the video/language
    - 429: Too many requests (rate limit exceeded)
    - 503: YouTube rate limit detected (retry after 60 seconds)
    """
    from app.config import settings

    # Apply rate limiting if enabled
    if settings.rate_limit_enabled:
        client_ip = get_remote_address_proxied(request)
        if not await _check_rate_limit(client_ip, settings.rate_limit_per_minute):
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Maximum {settings.rate_limit_per_minute} requests per minute.",
            )

    # Validate URL
    if not is_valid_youtube_url(video_url):
        logger.warning(f"Invalid URL provided: {sanitize_for_log(video_url)}")
        raise HTTPException(
            status_code=400,
            detail="Invalid YouTube URL. Expected format: https://www.youtube.com/watch?v=VIDEO_ID",
        )

    # Check cache if enabled - try database first, then in-memory
    if settings.cache_enabled:
        # Check database cache first (persistent across restarts)
        db_entry = await db_engine.get_cached_subtitle(video_url, lang, format.value)
        if db_entry is not None:
            logger.info(f"DB cache hit for {sanitize_for_log(video_url)}")
            cached_data = db_entry.subtitle_data
            if format == OutputFormat.vtt:
                return PlainTextResponse(
                    content=cached_data,
                    headers={
                        "Content-Type": "text/vtt; charset=utf-8",
                        "X-Video-ID": db_entry.video_id,
                        "X-Cache": "HIT",
                    },
                )
            elif format == OutputFormat.text:
                return SubtitleTextResponse.model_validate_json(cached_data)
            else:
                return SubtitleResponse.model_validate_json(cached_data)

        # Check in-memory cache
        cached_data = await cache.get(video_url, lang, format.value)
        if cached_data is not None:
            logger.info(f"Memory cache hit for {sanitize_for_log(video_url)}")
            # Return cached response based on format
            if format == OutputFormat.vtt:
                # VTT format caches as {"video_id": ..., "vtt": "..."}
                return PlainTextResponse(
                    content=cast(str, cached_data["vtt"]),
                    headers={
                        "Content-Type": "text/vtt; charset=utf-8",
                        "X-Video-ID": cached_data.get("video_id", ""),
                        "X-Cache": "HIT",
                    },
                )
            elif format == OutputFormat.text:
                return SubtitleTextResponse(**cached_data)
            else:
                return SubtitleResponse(**cached_data)

    # Get extractor and run in thread pool (yt-dlp is blocking)
    extractor = get_extractor()

    try:
        # Use run_in_threadpool to avoid blocking the event loop
        # yt-dlp operations are synchronous and CPU-intensive
        from starlette.concurrency import run_in_threadpool

        video_id, subtitle_data, metadata = await run_in_threadpool(
            extractor.extract_subtitles, video_url, lang, format.value
        )

        # Convert metadata to response model
        metadata_dict = metadata_to_response_dict(metadata)
        metadata_response = VideoMetadataResponse(**metadata_dict)

        # Prepare response based on requested format
        response_data = None
        if format == OutputFormat.vtt:
            # Return raw VTT content
            response_data = {
                "content": cast(str, subtitle_data),
                "headers": {
                    "Content-Type": "text/vtt; charset=utf-8",
                    "X-Video-ID": video_id,
                    "X-Cache": "MISS",
                },
            }
            # Cache the VTT content
            if settings.cache_enabled:
                await cache.set(video_url, lang, format.value, {"video_id": video_id, "vtt": subtitle_data})
                # Persist to database with TTL
                ttl_hours = settings.cache_ttl // 3600 or None
                await db_engine.set_cached_subtitle(
                    video_url, video_id, lang, format.value, subtitle_data, ttl_hours=ttl_hours
                )
            return PlainTextResponse(
                content=response_data["content"],
                headers=response_data["headers"],
            )
        elif format == OutputFormat.text:
            # Combine all subtitle text into single string
            combined_text = " ".join(entry.text for entry in cast(list[SubtitleEntry], subtitle_data))
            # Normalize whitespace
            combined_text = re.sub(r"\s+", " ", combined_text).strip()
            text_response = SubtitleTextResponse(
                video_id=video_id,
                language=lang,
                text=combined_text,
                metadata=metadata_response,
            )
            # Cache the text response
            if settings.cache_enabled:
                await cache.set(video_url, lang, format.value, text_response.model_dump())
                # Persist to database with TTL
                ttl_hours = settings.cache_ttl // 3600 or None
                await db_engine.set_cached_subtitle(
                    video_url, video_id, lang, format.value, text_response.model_dump_json(), ttl_hours=ttl_hours
                )
            return text_response
        else:
            # Convert SubtitleEntry objects to Pydantic models (json format with timestamps)
            subtitle_models = [
                SubtitleEntryModel(start=entry.start, end=entry.end, text=entry.text)
                for entry in cast(list[SubtitleEntry], subtitle_data)
            ]

            json_response = SubtitleResponse(
                video_id=video_id,
                language=lang,
                subtitle_count=len(subtitle_models),
                subtitles=subtitle_models,
                metadata=metadata_response,
            )
            # Cache the JSON response
            if settings.cache_enabled:
                await cache.set(video_url, lang, format.value, json_response.model_dump())
                # Persist to database with TTL
                ttl_hours = settings.cache_ttl // 3600 or None
                await db_engine.set_cached_subtitle(
                    video_url, video_id, lang, format.value, json_response.model_dump_json(), ttl_hours=ttl_hours
                )
            return json_response

    except ValueError as e:
        # No subtitles found or parsing error
        logger.warning(f"Value error during extraction: {sanitize_for_log(str(e))}")
        raise HTTPException(status_code=404, detail=str(e))
    except yt_dlp.utils.DownloadError as e:
        # Let the global handler handle this
        raise e


@app.get(
    "/api/v1/subtitles/languages",
    response_model=LanguagesResponse,
    responses={
        200: {"description": "Available languages retrieved"},
        400: {"model": ErrorResponse, "description": "Invalid URL"},
        404: {"model": ErrorResponse, "description": "Video not found"},
    },
    summary="List available subtitle languages for a video",
)
async def list_languages(
    request: Request,
    video_url: str = Query(..., max_length=500, description="YouTube video URL"),
) -> LanguagesResponse:
    """
    Get list of available subtitle languages for a video.

    Returns all available subtitle languages including manual and auto-generated
    subtitles with their formats.

    **Example:**
    ```bash
    curl "http://localhost:8000/api/v1/subtitles/languages?video_url=dQw4w9WgXcQ"
    ```
    """
    from app.config import settings

    # Apply rate limiting if enabled
    if settings.rate_limit_enabled:
        client_ip = get_remote_address_proxied(request)
        if not await _check_rate_limit(client_ip, settings.rate_limit_per_minute):
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Maximum {settings.rate_limit_per_minute} requests per minute.",
            )

    # Validate URL
    if not is_valid_youtube_url(video_url):
        logger.warning(f"Invalid URL provided: {sanitize_for_log(video_url)}")
        raise HTTPException(
            status_code=400,
            detail="Invalid YouTube URL. Expected format: https://www.youtube.com/watch?v=VIDEO_ID",
        )

    # Get languages
    extractor = get_extractor()
    from starlette.concurrency import run_in_threadpool

    try:
        video_id, languages = await run_in_threadpool(
            extractor.list_available_languages, video_url
        )
        return LanguagesResponse(
            video_id=video_id,
            languages=[LanguageInfo(**lang) for lang in languages],
        )
    except (ValueError, yt_dlp.utils.DownloadError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post(
    "/api/v1/subtitles/batch",
    response_model=list[BatchResponseItem],
    responses={
        200: {"description": "Batch extraction completed"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
        429: {"model": ErrorResponse, "description": "Too many requests"},
    },
    summary="Extract subtitles for multiple videos in one request",
)
async def batch_extract_subtitles(
    request: Request,
    batch: BatchRequest,
) -> list[BatchResponseItem]:
    """
    Extract subtitles for multiple videos in one request.

    **Limits:**
    - Maximum 10 videos per batch
    - 30 requests per minute per IP (higher than single endpoint)

    **Example:**
    ```bash
    curl -X POST "http://localhost:8000/api/v1/subtitles/batch" \\
      -H "Content-Type: application/json" \\
      -d '{"videos": [{"video_url": "dQw4w9WgXcQ", "lang": "en", "format": "json"}]}'
    ```
    """
    from app.config import settings

    # Apply rate limiting (higher limit for batch)
    if settings.rate_limit_enabled:
        client_ip = get_remote_address_proxied(request)
        # Use 3x the normal limit for batch requests
        batch_limit = settings.rate_limit_per_minute * 3
        if not await _check_rate_limit(client_ip, batch_limit):
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Maximum {batch_limit} requests per minute.",
            )

    results = []
    extractor = get_extractor()

    for video_req in batch.videos:
        video_url = video_req.video_url
        lang = video_req.lang
        format = video_req.format

        try:
            if not is_valid_youtube_url(video_url):
                results.append(
                    BatchResponseItem(
                        video_url=video_url, success=False, error="Invalid YouTube URL"
                    )
                )
                continue

            # Check cache - try database first, then in-memory
            if settings.cache_enabled:
                # Check database cache
                db_entry = await db_engine.get_cached_subtitle(video_url, lang, format)
                if db_entry is not None:
                    cached = db_entry.subtitle_data
                    # Parse from JSON to dict
                    import json
                    cached_dict = json.loads(cached)
                    results.append(
                        BatchResponseItem(
                            video_url=video_url,
                            success=True,
                            video_id=db_entry.video_id,
                            data=cached_dict,
                        )
                    )
                    continue

                # Check in-memory cache
                cached = await cache.get(video_url, lang, format)
                if cached is not None:
                    results.append(
                        BatchResponseItem(
                            video_url=video_url,
                            success=True,
                            video_id=cached.get("video_id"),
                            data=cached,
                        )
                    )
                    continue

            # Extract subtitles
            from starlette.concurrency import run_in_threadpool

            video_id, subtitle_data, metadata = await run_in_threadpool(
                extractor.extract_subtitles, video_url, lang, format
            )

            # Build metadata dict using helper
            metadata_dict = metadata_to_response_dict(metadata)

            # Prepare response data
            if format == "json":
                data = {
                    "video_id": video_id,
                    "language": lang,
                    "subtitle_count": len(subtitle_data),
                    "subtitles": [
                        {"start": s.start, "end": s.end, "text": s.text}
                        for s in subtitle_data
                    ],
                    "metadata": metadata_dict,
                }
            elif format == "text":
                combined = " ".join(s.text for s in subtitle_data)
                combined = re.sub(r"\s+", " ", combined).strip()
                data = {
                    "video_id": video_id,
                    "language": lang,
                    "text": combined,
                    "metadata": metadata_dict,
                }
            else:  # vtt
                data = {"video_id": video_id, "vtt": subtitle_data}

            # Cache result
            if settings.cache_enabled:
                await cache.set(video_url, lang, format, data)
                # Persist to database with TTL
                import json
                ttl_hours = settings.cache_ttl // 3600 or None
                await db_engine.set_cached_subtitle(
                    video_url, video_id, lang, format, json.dumps(data), ttl_hours=ttl_hours
                )

            results.append(
                BatchResponseItem(
                    video_url=video_url, success=True, video_id=video_id, data=data
                )
            )

        except Exception as e:
            logger.error(f"Batch extraction error for {video_url}: {e}")
            results.append(
                BatchResponseItem(
                    video_url=video_url, success=False, error=str(e)[:200]
                )
            )

    return results


@app.get("/", summary="Simple health check")
async def root() -> dict[str, str]:
    """Simple health check endpoint."""
    from app import __version__
    return {"status": "healthy", "service": "ytdlp-microservice", "version": __version__}


@app.get("/health", response_model=HealthResponse, summary="Enhanced health check")
async def health() -> HealthResponse:
    """
    Enhanced health check with service metrics.

    Returns service status, uptime, cache statistics, and database status.
    """
    from app import __version__
    from app.config import settings

    cache_stats = await cache.get_stats() if settings.cache_enabled else {"enabled": False}
    db_status = await db_engine.health_check()

    # Determine overall status
    overall_status = "healthy" if db_status.get("status") == "healthy" else "degraded"

    return HealthResponse(
        status=overall_status,
        service="ytdlp-microservice",
        version=__version__,
        timestamp=time.time(),
        uptime_seconds=time.time() - _app_start_time,
        cache=cache_stats,
        rate_limiting={
            "enabled": settings.rate_limit_enabled,
            "per_minute": settings.rate_limit_per_minute,
        },
        database=db_status,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
