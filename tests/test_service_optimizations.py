"""Quick tests for service optimizations."""
import time
from unittest.mock import MagicMock, patch

import pytest
import yt_dlp

from app.service import SubtitleExtractor


class TestRetryLogic:
    """Tests for retry logic with exponential backoff."""

    def test_retry_on_transient_error(self, tmp_path):
        """Test that transient errors trigger retry."""
        extractor = SubtitleExtractor()

        # Create a mock VTT file
        vtt_content = """WEBVTT

00:00:00.000 --> 00:00:03.500
Hello world
"""
        vtt_file = tmp_path / "dQw4w9WgXcQ.en.vtt"
        vtt_file.write_text(vtt_content, encoding="utf-8")

        # Mock yt-dlp to fail twice with 429, then succeed
        call_count = 0
        def mock_extract_info(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise yt_dlp.utils.DownloadError("HTTP Error 429: Too Many Requests")
            return {"id": "dQw4w9WgXcQ"}

        with patch("app.service.yt_dlp.YoutubeDL") as mock_ydl:
            mock_instance = MagicMock()
            mock_instance.extract_info = mock_extract_info
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_ydl.return_value = mock_instance

            with patch("tempfile.TemporaryDirectory") as mock_tempdir:
                mock_cm = MagicMock()
                mock_cm.__enter__ = MagicMock(return_value=str(tmp_path))
                mock_cm.__exit__ = MagicMock(return_value=False)
                mock_tempdir.return_value = mock_cm

                # Patch time.sleep to avoid waiting
                with patch("app.service.time.sleep") as mock_sleep:
                    video_id, result, metadata = extractor.extract_subtitles(
                        "https://youtu.be/dQw4w9WgXcQ", "en", "json"
                    )

        assert call_count == 3  # 2 failures + 1 success
        assert video_id == "dQw4w9WgXcQ"
        assert mock_sleep.call_count == 2  # Slept between retries

    def test_no_retry_on_non_transient_error(self, tmp_path):
        """Test that non-transient errors don't trigger retry."""
        extractor = SubtitleExtractor()

        # Mock yt-dlp to fail with a non-transient error
        with patch("app.service.yt_dlp.YoutubeDL") as mock_ydl:
            mock_instance = MagicMock()
            mock_instance.extract_info = MagicMock(
                side_effect=yt_dlp.utils.DownloadError("Video unavailable")
            )
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_ydl.return_value = mock_instance

            with patch("tempfile.TemporaryDirectory") as mock_tempdir:
                mock_cm = MagicMock()
                mock_cm.__enter__ = MagicMock(return_value=str(tmp_path))
                mock_cm.__exit__ = MagicMock(return_value=False)
                mock_tempdir.return_value = mock_cm

                with patch("app.service.time.sleep") as mock_sleep:
                    with pytest.raises(yt_dlp.utils.DownloadError, match="unavailable"):
                        extractor.extract_subtitles(
                            "https://youtu.be/dQw4w9WgXcQ", "en", "json"
                        )

        # Should not have retried
        mock_sleep.assert_not_called()


class TestLanguageCache:
    """Tests for language list caching."""

    def test_language_list_caching(self):
        """Test that language lists are cached."""
        extractor = SubtitleExtractor()

        # Mock _fetch_languages to track calls
        with patch.object(extractor, "_fetch_languages") as mock_fetch:
            mock_fetch.return_value = [
                {"code": "en", "name": "English", "auto_generated": False, "formats": ["vtt"]}
            ]

            # First call should fetch (use valid 11-char video ID)
            video_id1, langs1 = extractor.list_available_languages("https://youtu.be/dQw4w9WgXcQ")
            assert mock_fetch.call_count == 1

            # Second call should use cache
            video_id2, langs2 = extractor.list_available_languages("https://youtu.be/dQw4w9WgXcQ")
            assert mock_fetch.call_count == 1  # Still 1, not 2
            assert langs1 == langs2

    def test_language_cache_expiration(self):
        """Test that language cache entries expire."""
        extractor = SubtitleExtractor()
        extractor._language_cache_ttl = 0.1  # 100ms for testing

        with patch.object(extractor, "_fetch_languages") as mock_fetch:
            mock_fetch.return_value = [
                {"code": "en", "name": "English", "auto_generated": False, "formats": ["vtt"]}
            ]

            # First call (use valid 11-char video ID)
            extractor.list_available_languages("https://youtu.be/dQw4w9WgXcQ")
            assert mock_fetch.call_count == 1

            # Wait for cache to expire
            time.sleep(0.15)

            # Second call should fetch again
            extractor.list_available_languages("https://youtu.be/dQw4w9WgXcQ")
            assert mock_fetch.call_count == 2

    def test_clear_language_cache(self):
        """Test clearing language cache."""
        extractor = SubtitleExtractor()

        with patch.object(extractor, "_fetch_languages") as mock_fetch:
            mock_fetch.return_value = [
                {"code": "en", "name": "English", "auto_generated": False, "formats": ["vtt"]}
            ]

            # First call (use valid 11-char video ID)
            extractor.list_available_languages("https://youtu.be/dQw4w9WgXcQ")
            assert mock_fetch.call_count == 1

            # Clear cache (use the video_id extracted from the URL)
            extractor.clear_language_cache("dQw4w9WgXcQ")

            # Second call should fetch again
            extractor.list_available_languages("https://youtu.be/dQw4w9WgXcQ")
            assert mock_fetch.call_count == 2


class TestVTTStreaming:
    """Tests for VTT streaming parser."""

    def test_streaming_parser_for_large_files(self):
        """Test that large files use streaming parser."""
        extractor = SubtitleExtractor()

        # Create a large VTT content (>1MB)
        vtt_lines = ["WEBVTT", ""]
        for i in range(20000):
            vtt_lines.extend([
                f"00:{i//3600:02d}:{(i//60)%60:02d}.{i%60:03d} --> 00:{i//3600:02d}:{(i//60)%60:02d}.{(i%60)+1:03d}",
                f"Subtitle line {i}",
                ""
            ])
        vtt_content = "\n".join(vtt_lines)

        # Should use streaming parser
        assert len(vtt_content) > 1_000_000
        entries = extractor._parse_vtt_to_json(vtt_content)
        assert len(entries) == 20000

    def test_regular_parser_for_small_files(self):
        """Test that small files use regular parser."""
        extractor = SubtitleExtractor()

        vtt_content = """WEBVTT

00:00:00.000 --> 00:00:03.500
Hello world

00:00:03.500 --> 00:00:07.000
Second line
"""
        entries = extractor._parse_vtt_to_json(vtt_content)
        assert len(entries) == 2
        assert entries[0].text == "Hello world"
        assert entries[1].text == "Second line"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
