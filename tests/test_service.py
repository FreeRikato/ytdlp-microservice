"""Service layer tests for subtitle extraction.

Tests cover the core functionality of the SubtitleExtractor class.
All tests use mocked yt-dlp to avoid rate limits.
"""

from unittest.mock import MagicMock, patch

import pytest
import yt_dlp

from app.config import Settings
from app.service import SubtitleExtractor


class TestExtractSubtitlesSuccess:
    """Tests for successful subtitle extraction."""

    def test_extract_subtitles_success(self, tmp_path):
        """Test extracting subtitles successfully with mocked yt-dlp."""
        # Create a mock VTT file
        vtt_content = """WEBVTT

00:00:00.000 --> 00:00:03.500
Hello world

00:00:03.500 --> 00:00:07.000
This is a test subtitle
"""
        vtt_file = tmp_path / "dQw4w9WgXcQ.en.vtt"
        vtt_file.write_text(vtt_content, encoding="utf-8")

        extractor = SubtitleExtractor()

        # Mock yt-dlp
        with patch("app.service.yt_dlp.YoutubeDL") as mock_ydl:
            mock_instance = MagicMock()
            mock_instance.extract_info = MagicMock(return_value={"id": "dQw4w9WgXcQ"})
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_ydl.return_value = mock_instance

            # Mock TemporaryDirectory to use our temp path
            with patch("tempfile.TemporaryDirectory") as mock_tempdir:
                mock_cm = MagicMock()
                mock_cm.__enter__ = MagicMock(return_value=str(tmp_path))
                mock_cm.__exit__ = MagicMock(return_value=False)
                mock_tempdir.return_value = mock_cm

                video_id, result = extractor.extract_subtitles(
                    "https://youtu.be/dQw4w9WgXcQ", "en", "json"
                )

        assert video_id == "dQw4w9WgXcQ"
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].text == "Hello world"
        assert result[1].text == "This is a test subtitle"

    def test_extract_subtitles_vtt_parsing(self, tmp_path):
        """Test VTT parsing to JSON conversion."""
        # Create a VTT file with various features
        vtt_content = """WEBVTT

00:00:00.000 --> 00:00:02.000
First subtitle

00:00:02.000 --> 00:00:05.000
<00:00:02.500>Second <00:00:03.000>subtitle

00:00:05.000 --> 00:00:08.000
Third subtitle
"""
        vtt_file = tmp_path / "dQw4w9WgXcQ.en.vtt"
        vtt_file.write_text(vtt_content, encoding="utf-8")

        extractor = SubtitleExtractor()

        with patch("app.service.yt_dlp.YoutubeDL") as mock_ydl:
            mock_instance = MagicMock()
            mock_instance.extract_info = MagicMock(return_value={"id": "dQw4w9WgXcQ"})
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_ydl.return_value = mock_instance

            with patch("tempfile.TemporaryDirectory") as mock_tempdir:
                mock_cm = MagicMock()
                mock_cm.__enter__ = MagicMock(return_value=str(tmp_path))
                mock_cm.__exit__ = MagicMock(return_value=False)
                mock_tempdir.return_value = mock_cm

                video_id, result = extractor.extract_subtitles(
                    "https://youtu.be/dQw4w9WgXcQ", "en", "json"
                )

        assert len(result) == 3
        # Timestamp tags should be removed
        assert result[1].text == "Second subtitle"

    def test_extract_subtitles_vtt_format(self, tmp_path):
        """Test extracting subtitles in VTT format."""
        vtt_content = """WEBVTT

00:00:00.000 --> 00:00:03.500
Hello world
"""
        vtt_file = tmp_path / "dQw4w9WgXcQ.en.vtt"
        vtt_file.write_text(vtt_content, encoding="utf-8")

        extractor = SubtitleExtractor()

        with patch("app.service.yt_dlp.YoutubeDL") as mock_ydl:
            mock_instance = MagicMock()
            mock_instance.extract_info = MagicMock(return_value={"id": "dQw4w9WgXcQ"})
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_ydl.return_value = mock_instance

            with patch("tempfile.TemporaryDirectory") as mock_tempdir:
                mock_cm = MagicMock()
                mock_cm.__enter__ = MagicMock(return_value=str(tmp_path))
                mock_cm.__exit__ = MagicMock(return_value=False)
                mock_tempdir.return_value = mock_cm

                video_id, result = extractor.extract_subtitles(
                    "https://youtu.be/dQw4w9WgXcQ", "en", "vtt"
                )

        assert video_id == "dQw4w9WgXcQ"
        assert isinstance(result, str)
        assert "WEBVTT" in result
        assert "Hello world" in result


class TestExtractSubtitlesErrors:
    """Tests for error handling in subtitle extraction."""

    def test_extract_subtitles_no_results(self, tmp_path):
        """Test handling when VTT file is empty."""
        # Create an empty VTT file
        vtt_file = tmp_path / "dQw4w9WgXcQ.en.vtt"
        vtt_file.write_text("", encoding="utf-8")

        extractor = SubtitleExtractor()

        with patch("app.service.yt_dlp.YoutubeDL") as mock_ydl:
            mock_instance = MagicMock()
            mock_instance.extract_info = MagicMock(return_value={"id": "dQw4w9WgXcQ"})
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_ydl.return_value = mock_instance

            with patch("tempfile.TemporaryDirectory") as mock_tempdir:
                mock_cm = MagicMock()
                mock_cm.__enter__ = MagicMock(return_value=str(tmp_path))
                mock_cm.__exit__ = MagicMock(return_value=False)
                mock_tempdir.return_value = mock_cm

                with pytest.raises(ValueError, match="empty"):
                    extractor.extract_subtitles(
                        "https://youtu.be/dQw4w9WgXcQ", "en", "json"
                    )

    def test_extract_subtitles_rate_limit(self):
        """Test handling of 429 rate limit errors."""
        extractor = SubtitleExtractor()

        with patch("app.service.yt_dlp.YoutubeDL") as mock_ydl:
            mock_instance = MagicMock()
            mock_instance.extract_info = MagicMock(
                side_effect=yt_dlp.utils.DownloadError("HTTP Error 429: Too Many Requests")
            )
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_ydl.return_value = mock_instance

            with pytest.raises(yt_dlp.utils.DownloadError, match="429"):
                extractor.extract_subtitles(
                    "https://youtu.be/dQw4w9WgXcQ", "en", "json"
                )

    def test_extract_subtitles_network_error(self):
        """Test handling of network errors."""
        extractor = SubtitleExtractor()

        with patch("app.service.yt_dlp.YoutubeDL") as mock_ydl:
            mock_instance = MagicMock()
            mock_instance.extract_info = MagicMock(
                side_effect=yt_dlp.utils.DownloadError("Connection refused")
            )
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_ydl.return_value = mock_instance

            with pytest.raises(yt_dlp.utils.DownloadError, match="Connection"):
                extractor.extract_subtitles(
                    "https://youtu.be/dQw4w9WgXcQ", "en", "json"
                )

    def test_extract_subtitles_invalid_url(self):
        """Test that invalid URL raises ValueError."""
        extractor = SubtitleExtractor()

        with pytest.raises(ValueError, match="Could not extract video ID"):
            extractor.extract_subtitles("https://invalid.com/video", "en", "json")


class TestSubtitleExtractorInit:
    """Tests for SubtitleExtractor initialization."""

    def test_init_with_default_config(self):
        """Test initialization with default configuration."""
        extractor = SubtitleExtractor()
        assert extractor.config is not None
        assert isinstance(extractor.config, Settings)

    def test_init_with_custom_config(self):
        """Test initialization with custom configuration."""
        custom_config = Settings(ytdlp_sleep_seconds=30)
        extractor = SubtitleExtractor(config=custom_config)
        assert extractor.config.ytdlp_sleep_seconds == 30
