# YouTube Subtitle Microservice

A FastAPI microservice for extracting YouTube subtitles with advanced anti-bot detection strategies.

## Features

- Extract subtitles in **JSON**, **VTT**, or **TEXT** formats
- Anti-bot detection bypass (browser impersonation, request throttling, client source spoofing)
- Response caching for improved performance
- Rate limiting for API protection
- Batch subtitle extraction (multiple videos in one request)
- List available subtitle languages for any video
- Security headers middleware
- Docker support for easy deployment

## Quick Start

### Using uv (Recommended)

```bash
# Clone repository
git clone <repo-url>
cd ytdlp-microservice

# Install dependencies
uv sync --all-extras

# Start server
uv run uvicorn app.main:app --reload
```

The service will be available at `http://localhost:8000`

### Using Docker

```bash
# Build and run with docker-compose
docker-compose up -d

# Or build and run manually
docker build -t ytdlp-microservice .
docker run -p 8000:8000 ytdlp-microservice
```

## Configuration

Configuration is done via environment variables. See `.env.example` for all options.

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | 0.0.0.0 | Server host |
| `PORT` | 8000 | Server port |
| `LOG_LEVEL` | info | Logging level |
| `YTDLP_SLEEP_SECONDS` | 60 | Sleep between requests (anti-bot) |
| `YTDLP_IMPERSONATE_TARGET` | chrome | Browser to impersonate |
| `YTDLP_TEMP_DIR` | /tmp/ytdlp | Temporary directory for downloads |
| `YTDLP_REQUEST_TIMEOUT` | 120 | Request timeout in seconds |
| `CACHE_ENABLED` | true | Enable response caching |
| `CACHE_TTL` | 3600 | Cache TTL in seconds |
| `CACHE_MAXSIZE` | 1000 | Maximum cache entries |
| `RATE_LIMIT_ENABLED` | true | Enable rate limiting |
| `RATE_LIMIT_PER_MINUTE` | 10 | Requests per minute per IP |
| `ENABLE_SECURITY_HEADERS` | true | Enable security headers |

## API Reference

### Get Subtitles

Extract subtitles from a YouTube video.

```http
GET /api/v1/subtitles?video_url={url}&lang={code}&format={format}
```

**Parameters:**
- `video_url`: YouTube video URL or 11-character video ID (required)
- `lang`: Language code (default: `en`, validated as ISO 639-1)
- `format`: Response format - `json`, `vtt`, or `text` (default: `json`)

**Example:**
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
    {"start": "00:00:00.000", "end": "00:00:03.500", "text": "Hello world"},
    {"start": "00:00:03.500", "end": "00:00:07.000", "text": "This is a test"}
  ]
}
```

### List Available Languages

Get all available subtitle languages for a video.

```http
GET /api/v1/subtitles/languages?video_url={url}
```

**Example:**
```bash
curl "http://localhost:8000/api/v1/subtitles/languages?video_url=dQw4w9WgXcQ"
```

**Response:**
```json
{
  "video_id": "dQw4w9WgXcQ",
  "languages": [
    {"code": "en", "name": "English", "auto_generated": false, "formats": ["vtt"]},
    {"code": "es", "name": "Spanish", "auto_generated": true, "formats": ["vtt"]}
  ]
}
```

### Batch Extract

Extract subtitles for multiple videos in one request.

```http
POST /api/v1/subtitles/batch
```

**Request Body:**
```json
{
  "videos": [
    {"video_url": "dQw4w9WgXcQ", "lang": "en", "format": "json"},
    {"video_url": "anotherId", "lang": "es", "format": "text"}
  ]
}
```

**Example:**
```bash
curl -X POST "http://localhost:8000/api/v1/subtitles/batch" \
  -H "Content-Type: application/json" \
  -d '{"videos": [{"video_url": "dQw4w9WgXcQ", "lang": "en", "format": "json"}]}'
```

**Response:**
```json
[
  {
    "video_url": "dQw4w9WgXcQ",
    "success": true,
    "video_id": "dQw4w9WgXcQ",
    "data": {...}
  }
]
```

### Health Check

Get service health and metrics.

```http
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "service": "ytdlp-microservice",
  "version": "0.2.0",
  "timestamp": 1737624000.0,
  "uptime_seconds": 123.45,
  "cache": {"size": 10, "hits": 50, "misses": 20, "hit_rate": 0.714},
  "rate_limiting": {"enabled": true, "per_minute": 10}
}
```

## Anti-Bot Strategies

This service implements multiple strategies to bypass YouTube's bot detection:

1. **Browser Impersonation**: TLS fingerprint spoofing to mimic Chrome browser
2. **Request Throttling**: Configurable sleep interval between requests
3. **Client Source Spoofing**: Uses non-web client to bypass PO Token requirement
4. **Error Fallbacks**: Graceful degradation on partial failures

## Deployment

### Docker

```bash
# Build image
docker build -t ytdlp-microservice .

# Run container
docker run -p 8000:8000 \
  -e CACHE_ENABLED=true \
  -e RATE_LIMIT_PER_MINUTE=20 \
  ytdlp-microservice
```

### Docker Compose

```bash
docker-compose up -d
```

### Environment Variables

Create a `.env` file for configuration:

```bash
cp .env.example .env
# Edit .env with your settings
```

## Development

```bash
# Install with dev dependencies
uv sync --all-extras

# Run tests
pytest -v --cov=app

# Run with auto-reload
uv run uvicorn app.main:app --reload
```

## API Documentation

Interactive API documentation is available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Security

- Input validation with max length limits
- URL validation with strict scheme and host checking
- Log injection prevention
- HTML sanitization with bleach
- Rate limiting per IP
- Security headers middleware

## License

MIT
