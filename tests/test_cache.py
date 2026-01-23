"""
Tests for cache implementation in app/cache.py.

This module tests the in-memory TTL cache functionality.
"""

import time

import pytest
import pytest_asyncio

from app.cache import SubtitleCache


@pytest_asyncio.fixture
async def cache():
    """Provide a fresh cache instance for each test."""
    cache = SubtitleCache()
    await cache.clear()
    # Set a short TTL for testing
    cache.ttl = 1.0
    cache.maxsize = 5
    return cache


class TestSubtitleCache:
    """Tests for SubtitleCache class."""

    @pytest.mark.asyncio
    async def test_cache_set_and_get(self, cache):
        """Test basic cache set and get operations."""
        data = {"video_id": "test123", "text": "Sample subtitle"}
        await cache.set("https://youtu.be/test123", "en", "json", data)

        retrieved = await cache.get("https://youtu.be/test123", "en", "json")
        assert retrieved == data

    @pytest.mark.asyncio
    async def test_cache_miss(self, cache):
        """Test cache miss returns None."""
        result = await cache.get("https://youtu.be/missing", "en", "json")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_key_different_params(self, cache):
        """Test that different parameters create different cache keys."""
        data1 = {"lang": "en", "text": "Hello"}
        data2 = {"lang": "es", "text": "Hola"}

        await cache.set("url", "en", "json", data1)
        await cache.set("url", "es", "json", data2)
        await cache.set("url", "en", "vtt", data1)

        assert await cache.get("url", "en", "json") == data1
        assert await cache.get("url", "es", "json") == data2
        assert await cache.get("url", "en", "vtt") == data1

    @pytest.mark.asyncio
    async def test_cache_expiration(self, cache):
        """Test that cache entries expire after TTL."""
        cache.ttl = 0.1  # 100ms TTL
        data = {"test": "data"}
        await cache.set("url", "en", "json", data)

        # Should be cached immediately
        assert await cache.get("url", "en", "json") == data

        # Wait for expiration
        time.sleep(0.15)
        assert await cache.get("url", "en", "json") is None

    @pytest.mark.asyncio
    async def test_cache_maxsize_eviction(self, cache):
        """Test that oldest entries are evicted when maxsize is reached."""
        cache.maxsize = 3
        cache.ttl = 3600  # Long TTL to test size-based eviction

        # Fill cache
        for i in range(5):
            await cache.set(f"url{i}", "en", "json", {"index": i})

        # Should only keep maxsize items
        stats = await cache.get_stats()
        assert stats["size"] <= 3

    @pytest.mark.asyncio
    async def test_cache_clear(self, cache):
        """Test clearing the cache."""
        await cache.set("url1", "en", "json", {"data": 1})
        await cache.set("url2", "en", "json", {"data": 2})

        stats = await cache.get_stats()
        assert stats["size"] == 2

        await cache.clear()
        stats = await cache.get_stats()
        assert stats["size"] == 0
        assert await cache.get("url1", "en", "json") is None

    @pytest.mark.asyncio
    async def test_cache_stats(self, cache):
        """Test cache statistics tracking."""
        # Generate some hits and misses
        await cache.get("miss1", "en", "json")
        await cache.get("miss2", "en", "json")

        data = {"test": "data"}
        await cache.set("hit", "en", "json", data)
        await cache.get("hit", "en", "json")
        await cache.get("hit", "en", "json")

        stats = await cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 2
        assert stats["hit_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_cache_hit_rate_calculation(self, cache):
        """Test hit rate calculation with only hits."""
        data = {"test": "data"}
        await cache.set("hit", "en", "json", data)
        await cache.get("hit", "en", "json")
        await cache.get("hit", "en", "json")

        stats = await cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_cache_hit_rate_with_only_misses(self, cache):
        """Test hit rate calculation with only misses."""
        await cache.get("miss1", "en", "json")
        await cache.get("miss2", "en", "json")

        stats = await cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 2
        assert stats["hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_cache_hit_rate_empty(self, cache):
        """Test hit rate when cache is empty."""
        stats = await cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_cache_update_existing_key(self, cache):
        """Test updating an existing cache entry."""
        await cache.set("url", "en", "json", {"version": 1})
        await cache.set("url", "en", "json", {"version": 2})

        result = await cache.get("url", "en", "json")
        assert result == {"version": 2}

    @pytest.mark.asyncio
    async def test_cache_different_url_formats_create_separate_entries(self, cache):
        """Test that different URL formats for the same video create separate cache entries."""
        # Same video ID but different URL formats create different cache keys
        # This is by design - the cache uses the full URL as part of the key
        data = {"video_id": "dQw4w9WgXcQ", "text": "test"}

        await cache.set("https://youtu.be/dQw4w9WgXcQ", "en", "json", data)
        # These should have different cache keys because the full URLs are different
        await cache.set("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "en", "json", data)

        # Both should be cached separately since they're different URLs
        stats = await cache.get_stats()
        assert stats["size"] == 2
