# API Design Document: YouTube Subtitle Microservice

## 1. Overview
This service exposes a REST API for extracting subtitles from YouTube videos using `yt-dlp`, with anti-bot safeguards, caching, and batch processing.

Primary use cases:
- Extract subtitles for a single video in `json`, `text`, `vtt`, or `srt`
- Discover available subtitle languages for a video
- Extract subtitles for up to 10 videos in one request
- Retrieve service health and runtime status

## 2. Design Goals
- Provide a simple, predictable HTTP API for subtitle extraction.
- Support multiple output formats for different consumers (human-readable and machine-readable).
- Protect upstream and service resources with rate limiting and concurrency controls.
- Improve latency and reduce upstream calls via cache layers.
- Keep operations observable via request IDs and health endpoints.

## 3. System Architecture
- API Layer: FastAPI endpoints in `app/main.py`.
- Extraction Layer: `SubtitleExtractor` in `app/service.py` wrapping `yt-dlp`.
- Cache Layer:
  - L1: in-memory TTL cache (or Redis if configured) via `cache_manager`
  - L2: SQLite persistent cache via `app/database.py`
- Persistence Layer: SQLModel on SQLite (`SubtitleCache` table).

Request path for single extraction:
1. Validate input (`video_url`, `lang`, `format`).
2. Apply per-IP rate limit (if enabled).
3. Read cache (L1 then L2).
4. On miss, extract via `yt-dlp` in threadpool.
5. Transform response by requested format.
6. Store cache (L1 and L2).
7. Return response.

## 4. API Conventions
- Base URL: `http://<host>:<port>`
- API versioning: path-based (`/api/v1/...`)
- Authentication: none
- Primary content types:
  - `application/json` for JSON payloads
  - `text/vtt; charset=utf-8` for VTT
  - `text/plain; charset=utf-8` for SRT
- Correlation: every response includes `X-Request-ID`
- Interactive docs:
  - `GET /docs`
  - `GET /redoc`
  - `GET /openapi.json`

## 5. Core Data Models

### 5.1 SubtitleEntry
- `start: string` (VTT timestamp)
- `end: string` (VTT timestamp)
- `text: string`

### 5.2 VideoMetadata
- `video_id: string`
- `title: string`
- `description: string | null`
- `duration: int | null`
- `duration_formatted: string | null`
- `thumbnail: string | null`
- `channel: string | null`
- `channel_id: string | null`
- `upload_date: string | null`
- `view_count: int | null`
- `like_count: int | null`
- `tags: string[]`
- `categories: string[]`
- `webpage_url: string | null`
- `extractor: string`

### 5.3 ErrorResponse
- `error: string`
- `message: string`
- `detail: string | null`

## 6. Endpoint Contracts

### 6.1 GET `/api/v1/subtitles`
Extract subtitles for one video.

Query parameters:
- `video_url` (required, max 500 chars)
  - Accepts strict YouTube URL hosts or raw 11-char video ID
- `lang` (optional, default `en`)
  - Regex: `^[a-z]{2}(-[A-Z]{2})?$`
- `format` (optional, default `json`)
  - Enum: `json | text | vtt | srt`

Response behaviors:
- `format=json` -> JSON body:
  - `video_id`, `language`, `subtitle_count`, `subtitles[]`, `metadata`
- `format=text` -> JSON body:
  - `video_id`, `language`, `text`, `metadata`
- `format=vtt` -> plain text VTT body
  - Headers: `X-Video-ID`, `X-Cache`
- `format=srt` -> plain text SRT body
  - Headers: `X-Video-ID`, `X-Cache`, `Content-Disposition: attachment; filename=subtitles.srt`

Status codes:
- `200` success
- `400` invalid URL or validation error
- `404` subtitles not found / parsing failure
- `429` local per-IP rate limit exceeded
- `503` upstream YouTube rate limiting detected (`HTTP 429`)
- `500` generic extraction/download failure

Example:
```http
GET /api/v1/subtitles?video_url=dQw4w9WgXcQ&lang=en&format=json
```

### 6.2 GET `/api/v1/subtitles/languages`
List available subtitle languages for a video.

Query parameters:
- `video_url` (required, max 500 chars)

Success response (`200`):
- `video_id: string`
- `languages: LanguageInfo[]`
  - `code: string`
  - `name: string`
  - `auto_generated: boolean`
  - `formats: string[]`

Status codes:
- `200` success
- `400` invalid URL or validation error
- `404` video/language metadata unavailable
- `429` local per-IP rate limit exceeded

### 6.3 POST `/api/v1/subtitles/batch`
Extract subtitles for multiple videos.

Request body:
- `videos: BatchVideoRequest[]` (max 10)
- `BatchVideoRequest`:
  - `video_url: string` (required, max 500)
  - `lang: string` (default `en`)
  - `format: string` (default `json`)

Response (`200` always for mixed outcomes):
- `BatchResponseItem[]`
  - `video_url: string`
  - `success: boolean`
  - `video_id: string | null`
  - `data: object | null`
  - `error: string | null`

Important runtime behavior:
- Endpoint-level rate limit is `3 * RATE_LIMIT_PER_MINUTE`.
- Per-video extraction runs concurrently with semaphore limit `BATCH_CONCURRENCY`.
- Invalid individual videos return per-item errors; they do not fail the full batch.
- `format` is currently free-form in request model. Runtime mapping is:
  - `json` -> structured JSON
  - `text` -> combined text
  - `srt` -> SRT data
  - any other value -> treated as VTT branch

Status codes:
- `200` batch processed (with mixed per-item results possible)
- `400` request validation error
- `429` local per-IP batch limit exceeded

### 6.4 GET `/`
Simple health response.

Response (`200`):
- `status: "healthy"`
- `service: "ytdlp-microservice"`
- `version: string`

### 6.5 GET `/health`
Enhanced health and runtime metrics.

Response (`200`):
- `status: "healthy" | "degraded"`
- `service: string`
- `version: string`
- `timestamp: float`
- `uptime_seconds: float`
- `cache: object` (size/hits/misses/hit_rate or equivalent)
- `rate_limiting: { enabled: boolean, per_minute: number }`
- `database: object` (health details)

## 7. Error Handling Model
The service uses mixed error shapes depending on source:
- Custom structured errors (`ErrorResponse`) for:
  - validation handler (`400`)
  - `yt-dlp` download errors (`500`/`503`)
- Default FastAPI `HTTPException` payloads (`{"detail": ...}`) for:
  - invalid URL
  - explicit rate limit exceptions
  - not found from endpoint logic

Clients should handle both:
- `error/message/detail` shape
- `detail`-only shape

## 8. Rate Limiting
- Strategy: in-memory per-IP sliding window tracker.
- Key source: `X-Forwarded-For` first hop, else client IP.
- Standard endpoints (`/api/v1/subtitles`, `/api/v1/subtitles/languages`):
  - `RATE_LIMIT_PER_MINUTE` (default `200`)
- Batch endpoint (`/api/v1/subtitles/batch`):
  - `3 * RATE_LIMIT_PER_MINUTE`

## 9. Caching Strategy
- L1 cache: in-memory TTL cache by default (`CACHE_TTL`, `CACHE_MAXSIZE`) or Redis when `REDIS_URL` is configured.
- L2 cache: SQLite table keyed by `(video_url, language, output_format)`.
- Cache coverage:
  - Single extraction endpoint: read/write L1 and L2
  - Batch endpoint: read/write L1 and L2
- Cache indicators:
  - `X-Cache: HIT|MISS` currently emitted for VTT/SRT plain-text responses in single extraction.

## 10. Security and Middleware
- CORS enabled for:
  - `http://127.0.0.1:8000`
  - `chrome-extension://*`
- Security headers (when enabled):
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Content-Security-Policy` (docs paths receive relaxed policy)
  - `Strict-Transport-Security` on HTTPS requests
- GZip middleware enabled (`minimum_size=1000` bytes)

## 11. Configuration Inputs (Key)
- `HOST` (default `0.0.0.0`)
- `PORT` (default `8000`)
- `YTDLP_SLEEP_SECONDS` (default `60`)
- `YTDLP_IMPERSONATE_TARGET` (default `chrome`)
- `YTDLP_REQUEST_TIMEOUT` (default `120`)
- `CACHE_ENABLED` (default `true`)
- `CACHE_TTL` (default `3600`)
- `CACHE_MAXSIZE` (default `1000`)
- `REDIS_URL` (optional)
- `RATE_LIMIT_ENABLED` (default `true`)
- `RATE_LIMIT_PER_MINUTE` (default `200`)
- `ENABLE_SECURITY_HEADERS` (default `true`)
- `BATCH_CONCURRENCY` (default `5`)

## 12. Design Notes and Improvement Opportunities
- Standardize error payloads across all failure paths (avoid mixed `ErrorResponse` vs `detail`).
- Enforce `BatchVideoRequest.format` as enum to align with single-item endpoint behavior.
- Document and/or align service version values exposed in different places.
- Consider exposing cache hit headers consistently for JSON/text responses.
