"""Minimal pytest fixtures for subtitle fetching tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yt_dlp
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """FastAPI TestClient for endpoint testing."""
    from app.main import cache_manager

    # Mock rate limiting to always allow during tests
    with patch("app.main._check_rate_limit", return_value=True):
        # Disable cache for tests by mocking the cache instance
        original_cache = cache_manager._cache
        cache_manager._cache = AsyncMock()
        cache_manager._cache.get = AsyncMock(return_value=None)
        cache_manager._cache.set = AsyncMock()
        cache_manager._cache.get_stats = AsyncMock(return_value={"size": 0, "hits": 0, "misses": 0, "hit_rate": 0})
        try:
            with patch("app.main.db_engine.get_cached_subtitle", new_callable=AsyncMock, return_value=None):
                with patch("app.main.db_engine.set_cached_subtitle", new_callable=AsyncMock, return_value=None):
                    yield TestClient(app)
        finally:
            # Restore original cache
            cache_manager._cache = original_cache


@pytest.fixture
def mock_vtt_file(tmp_path):
    """Create a mock VTT file for testing."""
    vtt_content = """WEBVTT

00:00:00.000 --> 00:00:03.500
Hello world

00:00:03.500 --> 00:00:07.000
This is a test subtitle
"""
    vtt_file = tmp_path / "dQw4w9WgXcQ.en.vtt"
    vtt_file.write_text(vtt_content, encoding="utf-8")
    return vtt_file


@pytest.fixture
def mock_successful_extraction(mock_vtt_file):
    """Mock successful yt-dlp extraction."""
    with patch("app.service.yt_dlp.YoutubeDL") as mock_ydl:
        mock_instance = MagicMock()
        mock_instance.extract_info = MagicMock(return_value={"id": "dQw4w9WgXcQ"})
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)
        mock_ydl.return_value = mock_instance

        # Mock TemporaryDirectory to use our temp path
        with patch("tempfile.TemporaryDirectory") as mock_tempdir:
            mock_cm = MagicMock()
            mock_cm.__enter__ = MagicMock(return_value=str(mock_vtt_file.parent))
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_tempdir.return_value = mock_cm

            yield mock_ydl


@pytest.fixture
def mock_429_error():
    """Mock HTTP 429 DownloadError for rate limiting tests."""
    return yt_dlp.utils.DownloadError("HTTP Error 429: Too Many Requests")


@pytest.fixture
def mock_download_error():
    """Mock generic DownloadError."""
    return yt_dlp.utils.DownloadError("Unable to download video: Download failed")
