"""
Caching implementation for subtitle responses.

This module provides an in-memory cache with TTL (time-to-live) support
for caching subtitle extraction results to reduce load on YouTube's API.
"""

import asyncio
import hashlib
import logging
import time
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


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
