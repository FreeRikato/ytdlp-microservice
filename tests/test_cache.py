"""
Tests for cache implementation in app/cache.py.

This module tests the in-memory TTL cache functionality.
"""

import time

import pytest

from app.cache import SubtitleCache


@pytest.fixture
def cache():
    """Provide a fresh cache instance for each test."""
    cache = SubtitleCache()
    cache.clear()
    # Set a short TTL for testing
    cache.ttl = 1.0
    cache.maxsize = 5
    return cache


class TestSubtitleCache:
    """Tests for SubtitleCache class."""

    def test_cache_set_and_get(self, cache):
        """Test basic cache set and get operations."""
        data = {"video_id": "test123", "text": "Sample subtitle"}
        cache.set("https://youtu.be/test123", "en", "json", data)

        retrieved = cache.get("https://youtu.be/test123", "en", "json")
        assert retrieved == data

    def test_cache_miss(self, cache):
        """Test cache miss returns None."""
        result = cache.get("https://youtu.be/missing", "en", "json")
        assert result is None

    def test_cache_key_different_params(self, cache):
        """Test that different parameters create different cache keys."""
        data1 = {"lang": "en", "text": "Hello"}
        data2 = {"lang": "es", "text": "Hola"}

        cache.set("url", "en", "json", data1)
        cache.set("url", "es", "json", data2)
        cache.set("url", "en", "vtt", data1)

        assert cache.get("url", "en", "json") == data1
        assert cache.get("url", "es", "json") == data2
        assert cache.get("url", "en", "vtt") == data1

    def test_cache_expiration(self, cache):
        """Test that cache entries expire after TTL."""
        cache.ttl = 0.1  # 100ms TTL
        data = {"test": "data"}
        cache.set("url", "en", "json", data)

        # Should be cached immediately
        assert cache.get("url", "en", "json") == data

        # Wait for expiration
        time.sleep(0.15)
        assert cache.get("url", "en", "json") is None

    def test_cache_maxsize_eviction(self, cache):
        """Test that oldest entries are evicted when maxsize is reached."""
        cache.maxsize = 3
        cache.ttl = 3600  # Long TTL to test size-based eviction

        # Fill cache
        for i in range(5):
            cache.set(f"url{i}", "en", "json", {"index": i})

        # Should only keep maxsize items
        stats = cache.get_stats()
        assert stats["size"] <= 3

    def test_cache_clear(self, cache):
        """Test clearing the cache."""
        cache.set("url1", "en", "json", {"data": 1})
        cache.set("url2", "en", "json", {"data": 2})

        assert cache.get_stats()["size"] == 2

        cache.clear()
        assert cache.get_stats()["size"] == 0
        assert cache.get("url1", "en", "json") is None

    def test_cache_stats(self, cache):
        """Test cache statistics tracking."""
        # Generate some hits and misses
        cache.get("miss1", "en", "json")
        cache.get("miss2", "en", "json")

        data = {"test": "data"}
        cache.set("hit", "en", "json", data)
        cache.get("hit", "en", "json")
        cache.get("hit", "en", "json")

        stats = cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 2
        assert stats["hit_rate"] == 0.5

    def test_cache_hit_rate_calculation(self, cache):
        """Test hit rate calculation with only hits."""
        data = {"test": "data"}
        cache.set("hit", "en", "json", data)
        cache.get("hit", "en", "json")
        cache.get("hit", "en", "json")

        stats = cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 1.0

    def test_cache_hit_rate_with_only_misses(self, cache):
        """Test hit rate calculation with only misses."""
        cache.get("miss1", "en", "json")
        cache.get("miss2", "en", "json")

        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 2
        assert stats["hit_rate"] == 0.0

    def test_cache_hit_rate_empty(self, cache):
        """Test hit rate when cache is empty."""
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

    def test_cache_update_existing_key(self, cache):
        """Test updating an existing cache entry."""
        cache.set("url", "en", "json", {"version": 1})
        cache.set("url", "en", "json", {"version": 2})

        result = cache.get("url", "en", "json")
        assert result == {"version": 2}

    def test_cache_different_url_formats_create_separate_entries(self, cache):
        """Test that different URL formats for the same video create separate cache entries."""
        # Same video ID but different URL formats create different cache keys
        # This is by design - the cache uses the full URL as part of the key
        data = {"video_id": "dQw4w9WgXcQ", "text": "test"}

        cache.set("https://youtu.be/dQw4w9WgXcQ", "en", "json", data)
        # These should have different cache keys because the full URLs are different
        cache.set("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "en", "json", data)

        # Both should be cached separately since they're different URLs
        stats = cache.get_stats()
        assert stats["size"] == 2
