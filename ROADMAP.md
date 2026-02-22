# YTDLP Microservice - Development Roadmap

This document tracks planned features, known issues requiring fixes, and performance optimizations for the YouTube subtitle extraction microservice.

---

## Table of Contents

1. [Features to Implement](#1-features-to-implement)
2. [Fixes to Address](#2-fixes-to-address)
3. [Optimizations to Make](#3-optimizations-to-make)
4. [Summary Statistics](#4-summary-statistics)

---

## 1. Features to Implement

### 1.1 High Priority (Missing Core Functionality)

#### API Authentication & Authorization
- **Description**: Implement API key-based authentication middleware with support for read-only and full-access key tiers
- **Why**: Critical security gap for production deployments - currently relies solely on IP-based rate limiting which fails behind NAT/proxies
- **Technical Considerations**:
  - Add `Authorization: Bearer <api_key>` header validation
  - Store API keys in database with tier (read-only vs full)
  - Different rate limits per tier
  - Admin endpoints for key management

#### Video Info Endpoint
- **Description**: Dedicated endpoint to fetch video metadata without extracting subtitles
- **Endpoint**: `GET /api/v1/video/info?url={youtube_url}`
- **Why**: Useful for validation and checking video availability before extraction
- **Technical Considerations**:
  - Returns: title, duration, channel, view count, upload date, thumbnail, available subtitle languages
  - Should be lightweight and cacheable
  - No yt-dlp download, only info extraction

#### Subtitle Search Within Video
- **Description**: Search for specific text within a video's subtitles with timestamp results
- **Endpoint**: `GET /api/v1/subtitles/search?url={url}&query={text}`
- **Why**: Enables use cases like "find where topic X is discussed"
- **Technical Considerations**:
  - Full-text search with SQLite FTS5 or in-memory indexing
  - Return matching segments with timestamps and surrounding context
  - Case-insensitive search with optional regex support

#### Create schemas.py Module
- **Description**: Move Pydantic models from main.py to a dedicated schemas.py module
- **Why**: Violates separation of concerns; CLAUDE.md mentions schemas.py but it doesn't exist
- **Technical Considerations**:
  - Move all request/response models
  - Update imports across the codebase
  - No functional changes, pure refactoring

### 1.2 Medium Priority (Nice-to-Have Improvements)

#### Prometheus Metrics Endpoint
- **Description**: `/metrics` endpoint for Prometheus scraping with request rates, latency percentiles, cache hit rates, and error rates
- **Why**: Production observability and alerting
- **Technical Considerations**: Use prometheus-client library, add middleware for request tracking

#### Webhook Support for Async Processing
- **Description**: For batch processing, accept a `webhook_url` parameter and POST results asynchronously when complete
- **Why**: Large batches can take minutes; synchronous requests may timeout
- **Technical Considerations**: Background task queue, retry logic for webhook delivery

#### Subtitle Translation Endpoint
- **Description**: Auto-translate subtitles using Google Translate, DeepL, or LibreTranslate APIs
- **Endpoint**: `POST /api/v1/subtitles/translate`
- **Why**: Many videos don't have subtitles in user's preferred language
- **Technical Considerations**: API key management, translation quotas, caching translated results

#### Export to Additional Formats
- **Description**: Support ASS/SSA, SBV, DFXP subtitle formats
- **Why**: Different use cases require different formats (e.g., ASS for styling, SBV for YouTube)
- **Technical Considerations**: Add format converters, update schema enums

#### Batch Job Status Endpoint
- **Description**: Track progress of long-running batch operations
- **Endpoint**: `GET /api/v1/batch/status/{job_id}`
- **Why**: For async batch processing with webhooks
- **Technical Considerations**: Job state in database, progress tracking

#### Configurable Batch Limits per API Key
- **Description**: Allow different batch size limits based on API key tier
- **Why**: Free tier: 5 videos, Pro tier: 50 videos, Enterprise: 100 videos
- **Technical Considerations**: Database schema update for key tiers

### 1.3 Low Priority (Future Enhancements)

#### Subtitle Diff/Comparison
- Compare subtitles between video versions or different language tracks

#### Channel Subscription Webhook
- Subscribe to channels and get notified when new videos are uploaded with subtitles

#### Subtitle Analytics Dashboard
- Web UI showing usage statistics, popular videos, language distribution

#### AI-Powered Subtitle Summarization
- Generate video summaries from subtitle content using LLMs

#### Proxy Rotation Support
- Rotate through multiple proxies for higher throughput

---

## 2. Fixes to Address

### 2.1 High Priority (Bugs, Inconsistencies, Security Issues)

#### Version Inconsistency
- **Issue**: `app/__init__.py` has version "0.1.0" while `app/main.py` and docs show "0.2.0"
- **Fix**: Create a single source of truth (e.g., read from pyproject.toml or a constants file)
- **Files**: `app/__init__.py`, `app/main.py`

#### CORS Security Issue
- **Issue**: CORS allows `chrome-extension://*` which permits any malicious Chrome extension
- **Fix**: Either remove chrome-extension support or whitelist specific extension IDs via config
- **Files**: `app/main.py` (CORS middleware configuration)

#### Rate Limit Documentation Mismatch
- **Issue**: API.md shows 10/min (subtitles), 30/min (batch), 20/min (languages) but implementation uses 200/min for all endpoints
- **Fix**: Update API.md to match actual implementation (200/min default, 600/min for batch)
- **Files**: `docs/API.md`

#### X-XSS-Protection Header Documentation Error
- **Issue**: API.md mentions `X-XSS-Protection: 1; mode=block` but it's not implemented (and shouldn't be - it's deprecated)
- **Fix**: Remove mention from API.md
- **Files**: `docs/API.md`

#### Missing CACHE_POLL_INTERVAL in .env.example
- **Issue**: Config supports `CACHE_POLL_INTERVAL` but it's not documented in .env.example
- **Fix**: Add with default value and description
- **Files**: `.env.example`

#### Database Path Mismatch
- **Issue**: Config defaults to `database.db` but documentation says `data/app.db`
- **Fix**: Update config default to match documented path
- **Files**: `app/config.py`

### 2.2 Medium Priority (Code Organization, Documentation)

#### Missing schemas.py File
- **Issue**: Pydantic models defined directly in main.py (1,148 lines) instead of dedicated schemas module
- **Fix**: Create app/schemas.py and move all request/response models
- **Files**: `app/main.py`, new `app/schemas.py`

#### Outdated "bleach" References in Documentation
- **Issue**: Code uses nh3 library for sanitization, but some docs still mention "bleach"
- **Fix**: Update all documentation to reference nh3
- **Files**: `CLAUDE.md`, `README.md`

#### Docker Health Check Uses Python
- **Issue**: Dockerfile health check uses Python urllib instead of lightweight curl
- **Fix**: Add curl to image and use `curl -f http://localhost:8000/health`
- **Files**: `Dockerfile`

#### Cache Poll Interval vs Cleanup Logic Confusion
- **Issue**: Poll interval is in seconds (60s) but cleanup checks hourly expiration
- **Fix**: Either align intervals or document the intentional mismatch
- **Files**: `app/cache.py`, comments

#### SRT Format Undocumented
- **Issue**: SRT output format is implemented but not documented in API.md
- **Fix**: Add SRT to format parameter documentation
- **Files**: `docs/API.md`

### 2.3 Low Priority (Minor Improvements)

#### Hardcoded Redis Key Prefix
- **Issue**: Redis keys use hardcoded `sofia:subtitles:` prefix
- **Fix**: Make configurable via `REDIS_KEY_PREFIX` environment variable
- **Files**: `app/cache.py`

#### Missing disconnect() Method in SubtitleCache
- **Issue**: SubtitleCache class doesn't implement disconnect() from CacheProtocol
- **Fix**: Add no-op or proper cleanup method
- **Files**: `app/cache.py`

#### Hardcoded Rate Limit in Comment
- **Issue**: Comment mentions "600" requests/min but this may become stale
- **Fix**: Reference the actual config value dynamically
- **Files**: `app/main.py`

#### YTDLP_TEMP_DIR Default Mismatch
- **Issue**: README says /tmp/ytdlp but config defaults to None
- **Fix**: Align documentation with code or vice versa
- **Files**: `README.md`, `app/config.py`

---

## 3. Optimizations to Make

### 3.1 High Priority (Critical Performance Gains)

#### Fix Reverse Cache Lookup Order
- **Current**: L2 (SQLite) cache is checked BEFORE L1 (in-memory) cache
- **Impact**: Adds ~10ms to every cache hit that should be microseconds
- **Fix**: Check L1 cache first, then L2
- **File**: `app/service.py` (around line 150)

#### Add Redis Connection Pooling
- **Current**: Creates new Redis connection for each operation
- **Impact**: Connection overhead under concurrent load
- **Fix**: Use `redis.asyncio.ConnectionPool` with max connections
- **File**: `app/cache.py`

#### Parallelize Batch Processing
- **Current**: Videos in a batch are processed sequentially
- **Impact**: Batch of 10 videos takes 10x time of single video
- **Fix**: Use `asyncio.gather()` or `asyncio.as_completed()` for concurrent processing
- **File**: `app/service.py` (batch endpoint handler)

#### Fix Database N+1 Query Pattern
- **Current**: Cleanup selects expired entries then deletes one by one
- **Impact**: O(n) queries for n expired entries
- **Fix**: Use single DELETE query with WHERE clause
- **File**: `app/database.py`

#### Add Retry Logic with Exponential Backoff
- **Current**: Transient failures (429, 503, network timeouts) fail permanently
- **Impact**: Unnecessary extraction failures
- **Fix**: Implement 3 retries with exponential backoff in SubtitleExtractor
- **File**: `app/service.py`

#### Optimize Cache Lock Contention
- **Current**: All cache operations use a single lock, serializing different keys
- **Impact**: Under high concurrency, cache operations queue up
- **Fix**: Use key-specific locks or concurrent dictionary (e.g., `cachetools.TTLCache`)
- **File**: `app/cache.py`

#### Add Database Index on expires_at
- **Current**: Cache cleanup does full table scan
- **Impact**: O(n) cleanup time where n = total cache entries
- **Fix**: Add index on `expires_at` column
- **File**: `app/models.py` or `app/database.py`

### 3.2 Medium Priority (Moderate Improvements)

#### Reduce Redundant JSON Serialization
- **Current**: Data serialized/deserialized multiple times through cache layers
- **Impact**: CPU overhead, especially for large subtitle files
- **Fix**: Cache parsed objects where possible, use msgpack instead of JSON
- **File**: `app/cache.py`, `app/database.py`

#### Add SQLite Connection Pooling
- **Current**: Uses NullPool which creates new connection per request
- **Impact**: Connection overhead
- **Fix**: Use `AsyncAdaptedQueuePool` with reasonable size (5-10)
- **File**: `app/database.py`

#### Make Background Cleanup Frequency Configurable
- **Current**: Runs every 60 seconds regardless of cache activity
- **Impact**: Unnecessary CPU/disk usage for low-traffic instances
- **Fix**: Configurable interval, or adaptive (run only when cache has activity)
- **File**: `app/cache.py`

#### Add Language List Prefetching/Caching
- **Current**: Language listing endpoint always queries YouTube
- **Impact**: Slow response, unnecessary external calls
- **Fix**: Cache language lists with video_id key
- **File**: `app/service.py`

#### Optimize VTT Parsing
- **Current**: Line-by-line iteration with regex on every line
- **Impact**: CPU overhead for large VTT files
- **Fix**: Use streaming parser, compile regex once
- **File**: `app/service.py`

#### Fix Rate Limit Tracker Memory Growth
- **Current**: Unbounded `defaultdict` stores all IPs until restart (10k+ entries)
- **Impact**: Memory leak under DDoS or high unique IP count
- **Fix**: LRU cache with max size, or Redis-backed storage
- **File**: `app/main.py`

#### Add HTTP Client Session Reuse
- **Current**: New aiohttp/httpx session per extraction
- **Impact**: Connection overhead, no keep-alive
- **Fix**: Use shared session with connection pooling
- **File**: `app/service.py`

#### Add Response Compression
- **Current**: No gzip/brotli compression for JSON responses
- **Impact**: Bandwidth usage, especially for large subtitle payloads
- **Fix**: Add `GZipMiddleware` from fastapi.middleware.gzip
- **File**: `app/main.py`

### 3.3 Low Priority (Micro-optimizations, Code Quality)

#### Cache Video ID Extraction Results
- **Current**: `extract_video_id()` called multiple times for same URL
- **Fix**: Memoize or pass extracted ID through call chain
- **File**: `app/service.py`, `app/utils.py`

#### Optimize Cache Key Generation
- **Current**: SHA-256 hash computed on every cache operation
- **Fix**: Cache key computation, or use simpler hashing for short keys
- **File**: `app/cache.py`

#### Move Imports to Module Level
- **Current**: Some imports inside functions (e.g., `import re`)
- **Impact**: Small overhead per request
- **Fix**: Move to top of file
- **File**: Various

#### Add Type Hints to Hot Paths
- **Current**: Some functions lack type hints causing dynamic dispatch
- **Fix**: Full type annotations on frequently-called functions
- **File**: Various

#### Split main.py into Smaller Modules
- **Current**: 1,148 lines with models, handlers, middleware mixed
- **Fix**: Separate routes/, dependencies/, handlers/ modules
- **File**: `app/main.py` (refactor)

#### Optimize Subtitle Deduplication
- **Current**: Uses `set()` which loses ordering
- **Fix**: Use `dict.fromkeys()` for ordered deduplication (Python 3.7+)
- **File**: `app/service.py`

#### Add Prometheus/StatsD Metrics
- **Current**: Only basic cache stats in health endpoint
- **Fix**: Add counters, histograms, gauges for all operations
- **File**: New metrics module

#### Make Batch Size Limit Runtime Configurable
- **Current**: Hardcoded limit of 10 in code
- **Fix**: Configurable via `BATCH_MAX_VIDEOS` with runtime override option
- **File**: `app/config.py`, `app/main.py`

#### Avoid Redundant Database Writes
- **Current**: Cache always UPDATEs even if data unchanged
- **Fix**: Check if data changed before write, or use INSERT OR IGNORE
- **File**: `app/database.py`

---

## 4. Summary Statistics

| Category | Total | High Priority | Medium Priority | Low Priority |
|----------|-------|---------------|-----------------|--------------|
| Features to Implement | 15 | 4 | 6 | 5 |
| Fixes to Address | 15 | 6 | 5 | 4 |
| Optimizations to Make | 24 | 7 | 8 | 9 |
| **TOTAL** | **54** | **17** | **19** | **18** |

### Priority Distribution

```
High Priority    ████████████████░░░░░░░░░  31% (17 items)
Medium Priority  ██████████████████░░░░░░░  35% (19 items)
Low Priority     █████████████████░░░░░░░░  33% (18 items)
```

### Recommended Next Steps

1. **Immediate (Week 1)**: Address high-priority fixes (version inconsistency, CORS security, rate limit docs)
2. **Short-term (Month 1)**: Implement high-priority optimizations (cache order fix, connection pooling, parallel batch)
3. **Medium-term (Quarter 1)**: Add high-priority features (API auth, video info endpoint, schemas.py)
4. **Ongoing**: Tackle medium and low priority items based on user feedback and usage patterns

---

*Last Updated: 2026-02-07*
*Generated by Claude Code with multi-agent analysis*
