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

from cachetools import TTLCache as CachetoolsTTLCache

from app.config import settings

if TYPE_CHECKING:
    import redis.asyncio as redis

logger = logging.getLogger(__name__)


class CacheProtocol(Protocol):
    """Protocol for cache implementations."""

    async def get(self, video_url: str, lang: str, format: str) -> Any | None: ...
    async def set(self, video_url: str, lang: str, format: str, data: Any) -> None: ...
    async def get_languages(self, video_url: str) -> Any | None: ...
    async def set_languages(self, video_url: str, data: Any) -> None: ...
    async def clear(self) -> None: ...
    async def get_stats(self) -> dict[str, Any]: ...
    async def disconnect(self) -> None: ...


class SubtitleCache:
    """
    In-memory cache for subtitle data with TTL support.

    This cache stores extracted subtitle data with a configurable TTL.
    Uses cachetools.TTLCache for thread-safe operations with automatic
    TTL-based expiration and LRU eviction.

    Cache keys are generated as SHA-256 hashes of the request parameters.
    """

    def __init__(self):
        """Initialize cache with settings from configuration."""
        self._hits = 0
        self._misses = 0
        self._ttl = settings.cache_ttl
        self._maxsize = settings.cache_maxsize
        # cachetools.TTLCache is thread-safe and handles its own locking
        # TTL is in seconds, timer uses time.monotonic
        self._cache: CachetoolsTTLCache = CachetoolsTTLCache(
            maxsize=self._maxsize,
            ttl=self._ttl,
            timer=time.monotonic,
        )

    @property
    def ttl(self) -> float:
        """Get the TTL in seconds."""
        return self._ttl

    @ttl.setter
    def ttl(self, value: float) -> None:
        """Set the TTL and recreate the underlying cache with new TTL."""
        self._ttl = value
        # Recreate cache with new TTL - old entries are lost but that's acceptable for tests
        self._cache = CachetoolsTTLCache(
            maxsize=self._maxsize,
            ttl=value,
            timer=time.monotonic,
        )

    @property
    def maxsize(self) -> int:
        """Get the maximum cache size."""
        return self._maxsize

    @maxsize.setter
    def maxsize(self, value: int) -> None:
        """Set the maximum cache size and recreate the underlying cache."""
        self._maxsize = value
        # Recreate cache with new maxsize - old entries are lost but that's acceptable for tests
        self._cache = CachetoolsTTLCache(
            maxsize=value,
            ttl=self._ttl,
            timer=time.monotonic,
        )

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

        # TTLCache handles its own locking internally
        # Expired entries return None automatically
        data = self._cache.get(key)
        if data is None:
            self._misses += 1
            return None

        self._hits += 1
        logger.debug(f"Cache hit for key: {key[:8]}...")
        return data

    async def set(self, video_url: str, lang: str, format: str, data: Any) -> None:
        """
        Cache subtitle data with current timestamp.

        Args:
            video_url: YouTube video URL or ID
            lang: Language code
            format: Output format
            data: Data to cache
        """
        key = self._generate_key(video_url, lang, format)

        # TTLCache handles its own locking and LRU eviction internally
        # When maxsize is exceeded, least recently used items are evicted
        self._cache[key] = data
        logger.debug(f"Cache set for key: {key[:8]}...")

    async def clear(self) -> None:
        """Clear all cached data."""
        size = len(self._cache)
        self._cache.clear()
        logger.info(f"Cache cleared: {size} entries removed")

    async def get_languages(self, video_url: str) -> Any | None:
        """
        Get cached language list for a video if available and not expired.

        Args:
            video_url: YouTube video URL or ID

        Returns:
            Cached language list data if found and not expired, None otherwise
        """
        key = self._generate_languages_key(video_url)

        # TTLCache handles its own locking internally
        data = self._cache.get(key)
        if data is None:
            self._misses += 1
            return None

        self._hits += 1
        logger.debug(f"Languages cache hit for key: {key[:8]}...")
        return data

    async def set_languages(self, video_url: str, data: Any) -> None:
        """
        Cache language list data for a video.

        Args:
            video_url: YouTube video URL or ID
            data: Language list data to cache
        """
        key = self._generate_languages_key(video_url)

        # TTLCache handles its own locking and eviction internally
        self._cache[key] = data
        logger.debug(f"Languages cache set for key: {key[:8]}...")

    def _generate_languages_key(self, video_url: str) -> str:
        """
        Generate a cache key for language list lookups.

        Args:
            video_url: YouTube video URL or ID

        Returns:
            SHA-256 hash with 'langs:' prefix
        """
        key_data = f"{video_url}:langs"
        return hashlib.sha256(key_data.encode()).hexdigest()

    async def get_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache size, hits, misses, and hit rate
        """
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

# Global Redis connection pool - shared across all RedisCache instances
_redis_pool: "redis.ConnectionPool | None" = None


def _get_redis_pool(redis_url: str | None = None) -> "redis.ConnectionPool":
    """
    Get or create the global Redis connection pool.

    Args:
        redis_url: Redis URL, defaults to settings.redis_url

    Returns:
        Shared ConnectionPool instance
    """
    global _redis_pool
    if _redis_pool is None:
        import redis.asyncio as redis

        url = redis_url or settings.redis_url
        if url:
            _redis_pool = redis.ConnectionPool.from_url(
                url,
                encoding="utf-8",
                decode_responses=True,
                max_connections=20,
            )
            logger.info(f"Created Redis connection pool for {url}")
    return _redis_pool


class RedisCache:
    """
    Redis-based cache for subtitle data with TTL support.

    This cache stores extracted subtitle data in Redis with a configurable TTL.
    Suitable for distributed deployments where multiple instances share cache.

    Uses a shared connection pool for efficient connection reuse.
    Redis operations are atomic, so no additional locking is needed.

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

    async def connect(self) -> None:
        """Connect to Redis server using connection pool."""
        import redis.asyncio as redis

        if self._redis_url:
            pool = _get_redis_pool(self._redis_url)
            if pool:
                self._client = redis.Redis(connection_pool=pool)
                logger.info("Connected to Redis using connection pool")

    async def disconnect(self) -> None:
        """Disconnect from Redis server (returns connection to pool)."""
        if self._client:
            # Just close the client, connection returns to pool
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

        # Redis operations are atomic, no lock needed
        try:
            data = await self._client.get(key)
            if data is None:
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

        # Redis operations are atomic, no lock needed
        try:
            await self._client.setex(key, self.ttl, json.dumps(data))
            logger.debug(f"Redis cache set for key: {key[:8]}...")
        except Exception as e:
            logger.error(f"Redis set error: {e}")

    async def clear(self) -> None:
        """Clear all cached data."""
        if not self._client:
            return

        # Redis operations are atomic, no lock needed
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

    async def get_languages(self, video_url: str) -> Any | None:
        """
        Get cached language list for a video if available and not expired.

        Args:
            video_url: YouTube video URL or ID

        Returns:
            Cached language list data if found and not expired, None otherwise
        """
        if not self._client:
            return None

        key = f"sofia:langs:{self._generate_languages_key(video_url)}"

        # Redis operations are atomic, no lock needed
        try:
            data = await self._client.get(key)
            if data is None:
                self._misses += 1
                return None

            self._hits += 1
            logger.debug(f"Redis languages cache hit for key: {key[:8]}...")
            return json.loads(data)
        except Exception as e:
            logger.error(f"Redis get languages error: {e}")
            self._misses += 1
            return None

    async def set_languages(self, video_url: str, data: Any) -> None:
        """
        Cache language list data for a video.

        Args:
            video_url: YouTube video URL or ID
            data: Language list data to cache
        """
        if not self._client:
            return

        key = f"sofia:langs:{self._generate_languages_key(video_url)}"

        # Redis operations are atomic, no lock needed
        try:
            await self._client.setex(key, self.ttl, json.dumps(data))
            logger.debug(f"Redis languages cache set for key: {key[:8]}...")
        except Exception as e:
            logger.error(f"Redis set languages error: {e}")

    def _generate_languages_key(self, video_url: str) -> str:
        """
        Generate a cache key for language list lookups.

        Args:
            video_url: YouTube video URL or ID

        Returns:
            SHA-256 hash of the video URL
        """
        key_data = f"{video_url}:langs"
        return hashlib.sha256(key_data.encode()).hexdigest()

    async def get_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache size, hits, misses, and hit rate
        """
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0
        return {
            "size": "N/A",  # Redis handles TTL internally, size tracking adds overhead
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
        }
