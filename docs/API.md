# YouTube Subtitle Microservice - API Documentation

Version: 0.2.0

Base URL: `http://localhost:8000`

## Table of Contents

1. [Endpoints](#endpoints)
2. [Response Formats](#response-formats)
3. [Error Codes](#error-codes)
4. [Rate Limiting](#rate-limiting)
5. [Security](#security)

---

## Endpoints

### 1. Get Subtitles

Extract subtitles from a YouTube video in various formats.

**Endpoint:** `GET /api/v1/subtitles`

**Parameters:**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `video_url` | string | Yes | - | YouTube video URL or 11-character video ID |
| `lang` | string | No | `en` | Language code (ISO 639-1, e.g., en, es, en-US) |
| `format` | string | No | `json` | Output format: `json`, `vtt`, or `text` |

**Example Request:**

```bash
curl "http://localhost:8000/api/v1/subtitles?video_url=dQw4w9WgXcQ&lang=en&format=json"
```

**Response (JSON format):**

```json
{
  "video_id": "dQw4w9WgXcQ",
  "language": "en",
  "subtitle_count": 2,
  "subtitles": [
    {
      "start": "00:00:00.000",
      "end": "00:00:03.500",
      "text": "Never gonna give you up"
    },
    {
      "start": "00:00:03.500",
      "end": "00:00:07.000",
      "text": "Never gonna let you down"
    }
  ]
}
```

**Response (VTT format):**

```http
HTTP/1.1 200 OK
Content-Type: text/vtt; charset=utf-8
X-Video-ID: dQw4w9WgXcQ
X-Cache: MISS

WEBVTT

00:00:00.000 --> 00:00:03.500
Never gonna give you up

00:00:03.500 --> 00:00:07.000
Never gonna let you down
```

**Response (TEXT format):**

```json
{
  "video_id": "dQw4w9WgXcQ",
  "language": "en",
  "text": "Never gonna give you up Never gonna let you down"
}
```

---

### 2. List Available Languages

Get all available subtitle languages for a video, including manual and auto-generated subtitles.

**Endpoint:** `GET /api/v1/subtitles/languages`

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `video_url` | string | Yes | YouTube video URL or 11-character video ID |

**Example Request:**

```bash
curl "http://localhost:8000/api/v1/subtitles/languages?video_url=dQw4w9WgXcQ"
```

**Response:**

```json
{
  "video_id": "dQw4w9WgXcQ",
  "languages": [
    {
      "code": "en",
      "name": "English",
      "auto_generated": false,
      "formats": ["vtt", "json"]
    },
    {
      "code": "es",
      "name": "Spanish",
      "auto_generated": true,
      "formats": ["vtt"]
    }
  ]
}
```

---

### 3. Batch Extract

Extract subtitles for multiple videos in a single request.

**Endpoint:** `POST /api/v1/subtitles/batch`

**Limits:**
- Maximum 10 videos per batch
- 30 requests per minute per IP

**Request Body:**

```json
{
  "videos": [
    {
      "video_url": "dQw4w9WgXcQ",
      "lang": "en",
      "format": "json"
    },
    {
      "video_url": "anotherVideoId",
      "lang": "es",
      "format": "text"
    }
  ]
}
```

**Example Request:**

```bash
curl -X POST "http://localhost:8000/api/v1/subtitles/batch" \
  -H "Content-Type: application/json" \
  -d '{
    "videos": [
      {"video_url": "dQw4w9WgXcQ", "lang": "en", "format": "json"}
    ]
  }'
```

**Response:**

```json
[
  {
    "video_url": "dQw4w9WgXcQ",
    "success": true,
    "video_id": "dQw4w9WgXcQ",
    "data": {
      "video_id": "dQw4w9WgXcQ",
      "language": "en",
      "subtitle_count": 100,
      "subtitles": [...]
    }
  }
]
```

---

### 4. Health Check

Get service health status and metrics.

**Endpoint:** `GET /health`

**Example Request:**

```bash
curl "http://localhost:8000/health"
```

**Response:**

```json
{
  "status": "healthy",
  "service": "ytdlp-microservice",
  "version": "0.2.0",
  "timestamp": 1737624000.123,
  "uptime_seconds": 3600.5,
  "cache": {
    "size": 150,
    "hits": 500,
    "misses": 150,
    "hit_rate": 0.769
  },
  "rate_limiting": {
    "enabled": true,
    "per_minute": 10
  }
}
```

---

### 5. Simple Health Check

Quick health check without metrics.

**Endpoint:** `GET /`

**Response:**

```json
{
  "status": "healthy",
  "service": "ytdlp-microservice",
  "version": "0.2.0"
}
```

---

## Response Formats

### JSON Format

Structured subtitle data with timestamps. Best for programmatic processing.

**Fields:**
- `video_id`: YouTube video ID
- `language`: Language code
- `subtitle_count`: Number of subtitle entries
- `subtitles`: Array of subtitle entries with `start`, `end`, and `text`

### VTT Format

WebVTT format for video players. Returns raw VTT file content.

**Headers:**
- `Content-Type: text/vtt; charset=utf-8`
- `X-Video-ID: {video_id}`
- `X-Cache: HIT|MISS`

### TEXT Format

Combined subtitle text without timestamps. Best for text analysis.

**Fields:**
- `video_id`: YouTube video ID
- `language`: Language code
- `text`: Combined subtitle text

---

## Error Codes

| Code | Description | Example |
|------|-------------|---------|
| 400 | Bad Request - Invalid URL or parameters | Invalid YouTube URL |
| 404 | Not Found - No subtitles available | No subtitles found for this video |
| 429 | Too Many Requests - Rate limit exceeded | Rate limit exceeded |
| 500 | Internal Server Error - Download failed | Failed to download subtitles |
| 503 | Service Unavailable - YouTube rate limit | Upstream rate limit detected |

**Error Response Format:**

```json
{
  "error": "validation_error",
  "message": "Invalid request parameters",
  "detail": "video_url: Field required; lang: String does not match regex '^[a-z]{2}(-[A-Z]{2})?$'"
}
```

---

## Rate Limiting

The API implements per-IP rate limiting to prevent abuse.

**Default Limits:**
- Single subtitle endpoint: 10 requests/minute
- Batch endpoint: 30 requests/minute
- Languages endpoint: 20 requests/minute

**Rate Limit Response:**

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json

{
  "error": "rate_limit_exceeded",
  "message": "Rate limit exceeded. Maximum 10 requests per minute.",
  "detail": "..."
}
```

**Configuration:**

Rate limiting can be disabled or adjusted via environment variables:
- `RATE_LIMIT_ENABLED=true/false`
- `RATE_LIMIT_PER_MINUTE=10`

---

## Security

### Input Validation

- `video_url`: Maximum 500 characters, validated URL format
- `lang`: ISO 639-1 format (e.g., `en`, `es`, `en-US`)
- Batch requests: Maximum 10 videos per batch

### Security Headers

All responses include security headers:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Content-Security-Policy: default-src 'self'
X-XSS-Protection: 1; mode=block
```

### HTML Sanitization

Subtitle text is sanitized using the `bleach` library to prevent XSS attacks. All HTML/XML tags are stripped from subtitle content.

### Log Injection Prevention

User input is sanitized before logging to prevent log injection attacks.

---

## Interactive Documentation

Interactive API documentation is available when running the service:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

These provide try-it-out functionality directly from your browser.
