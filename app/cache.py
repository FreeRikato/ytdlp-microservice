"""
Caching implementation for subtitle responses.

This module provides an in-memory cache with TTL (time-to-live) support
for caching subtitle extraction results to reduce load on YouTube's API.
Also provides Redis cache backend for distributed deployments.
"""

import asyncio
import hashlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Protocol

from app.config import settings

if TYPE_CHECKING:
    import redis.asyncio as redis

logger = logging.getLogger(__name__)


class CacheProtocol(Protocol):
    """Protocol for cache implementations."""

    async def get(self, video_url: str, lang: str, format: str) -> Any | None: ...
    async def set(self, video_url: str, lang: str, format: str, data: Any) -> None: ...
    async def clear(self) -> None: ...
    async def get_stats(self) -> dict[str, Any]: ...
    async def disconnect(self) -> None: ...


class SubtitleCache:
    """
    In-memory cache for subtitle data with TTL support.

    This cache stores extracted subtitle data with a configurable TTL.
    When the cache reaches maximum size, oldest entries are evicted first.
    Cache keys are generated as SHA-256 hashes of the request parameters.

    Async-safe: All cache operations are protected by a lock.
    """

    def __init__(self):
        """Initialize cache with settings from configuration."""
        self._cache: dict[str, tuple[Any, float]] = {}
        self._hits = 0
        self._misses = 0
        self.ttl = settings.cache_ttl
        self.maxsize = settings.cache_maxsize
        self._lock = asyncio.Lock()

    def _generate_key(self, video_url: str, lang: str, format: str) -> str:
        """
        Generate a cache key from request parameters.

        Args:
            video_url: YouTube video URL or ID
            lang: Language code
            format: Output format (json, vtt, text)

        Returns:
            SHA-256 hash of the combined parameters
        """
        key_data = f"{video_url}:{lang}:{format}"
        return hashlib.sha256(key_data.encode()).hexdigest()

    async def get(self, video_url: str, lang: str, format: str) -> Any | None:
        """
        Get cached subtitle data if available and not expired.

        Args:
            video_url: YouTube video URL or ID
            lang: Language code
            format: Output format

        Returns:
            Cached data if found and not expired, None otherwise
        """
        key = self._generate_key(video_url, lang, format)

        async with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            data, timestamp = self._cache[key]

            # Check if entry has expired
            if time.time() - timestamp > self.ttl:
                del self._cache[key]
                self._misses += 1
                return None

            self._hits += 1
            logger.debug(f"Cache hit for key: {key[:8]}...")
            return data

    async def set(self, video_url: str, lang: str, format: str, data: Any) -> None:
        """
        Cache subtitle data with current timestamp.

        If the cache is at maximum capacity, the oldest entry (by timestamp)
        will be evicted to make room for the new entry.

        Args:
            video_url: YouTube video URL or ID
            lang: Language code
            format: Output format
            data: Data to cache
        """
        key = self._generate_key(video_url, lang, format)

        async with self._lock:
            # Evict oldest entry if at capacity and key is not already present
            if len(self._cache) >= self.maxsize and key not in self._cache:
                oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
                logger.debug(f"Cache evicted oldest entry: {oldest_key[:8]}...")

            self._cache[key] = (data, time.time())
            logger.debug(f"Cache set for key: {key[:8]}...")

    async def clear(self) -> None:
        """Clear all cached data."""
        async with self._lock:
            size = len(self._cache)
            self._cache.clear()
            logger.info(f"Cache cleared: {size} entries removed")

    async def get_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache size, hits, misses, and hit rate
        """
        async with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0
            return {
                "size": len(self._cache),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
            }


# Global cache instance - shared across all requests
cache = SubtitleCache()


class RedisCache:
    """
    Redis-based cache for subtitle data with TTL support.

    This cache stores extracted subtitle data in Redis with a configurable TTL.
    Suitable for distributed deployments where multiple instances share cache.

    Attributes:
        ttl: Time-to-live in seconds for cache entries
        _hits: Counter for cache hits
        _misses: Counter for cache misses
    """

    def __init__(self, redis_url: str | None = None):
        """Initialize Redis cache with optional URL."""
        self._redis_url = redis_url or settings.redis_url
        self._client: "redis.Redis | None" = None
        self.ttl = settings.cache_ttl
        self._hits = 0
        self._misses = 0
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Connect to Redis server."""
        import redis.asyncio as redis

        if self._redis_url:
            self._client = redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            logger.info(f"Connected to Redis at {self._redis_url}")

    async def disconnect(self) -> None:
        """Disconnect from Redis server."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Disconnected from Redis")

    def _generate_key(self, video_url: str, lang: str, format: str) -> str:
        """
        Generate a cache key from request parameters.

        Args:
            video_url: YouTube video URL or ID
            lang: Language code
            format: Output format (json, vtt, text)

        Returns:
            SHA-256 hash of the combined parameters
        """
        key_data = f"{video_url}:{lang}:{format}"
        return hashlib.sha256(key_data.encode()).hexdigest()

    async def get(self, video_url: str, lang: str, format: str) -> Any | None:
        """
        Get cached subtitle data if available and not expired.

        Args:
            video_url: YouTube video URL or ID
            lang: Language code
            format: Output format

        Returns:
            Cached data if found and not expired, None otherwise
        """
        if not self._client:
            return None

        key = f"sofia:subtitles:{self._generate_key(video_url, lang, format)}"

        async with self._lock:
            try:
                data = await self._client.get(key)
                if data is None:
                    self._misses += 1
                    return None

                # Check if entry has expired (Redis handles TTL, but verify)
                ttl = await self._client.ttl(key)
                if ttl == -1:
                    # Key exists but has no TTL - this shouldn't happen
                    await self._client.delete(key)
                    self._misses += 1
                    return None

                self._hits += 1
                logger.debug(f"Redis cache hit for key: {key[:8]}...")
                return json.loads(data)
            except Exception as e:
                logger.error(f"Redis get error: {e}")
                self._misses += 1
                return None

    async def set(self, video_url: str, lang: str, format: str, data: Any) -> None:
        """
        Cache subtitle data with current timestamp and TTL.

        Args:
            video_url: YouTube video URL or ID
            lang: Language code
            format: Output format
            data: Data to cache
        """
        if not self._client:
            return

        key = f"sofia:subtitles:{self._generate_key(video_url, lang, format)}"

        async with self._lock:
            try:
                await self._client.setex(key, self.ttl, json.dumps(data))
                logger.debug(f"Redis cache set for key: {key[:8]}...")
            except Exception as e:
                logger.error(f"Redis set error: {e}")

    async def clear(self) -> None:
        """Clear all cached data."""
        if not self._client:
            return

        async with self._lock:
            try:
                # Only clear keys with our cache prefix to avoid deleting other Redis data
                keys = []
                async for key in self._client.scan_iter(match="sofia:subtitles:*", count=100):
                    keys.append(key)
                if keys:
                    await self._client.delete(*keys)
                    logger.info(f"Redis cache cleared: {len(keys)} entries removed")
            except Exception as e:
                logger.error(f"Redis clear error: {e}")

    async def get_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache size, hits, misses, and hit rate
        """
        async with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0
            return {
                "size": "N/A",  # Redis handles TTL internally, size tracking adds overhead
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
            }
