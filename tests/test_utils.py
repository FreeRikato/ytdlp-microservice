"""
Tests for utility functions in app/utils.py.

This module tests URL validation and video ID extraction functions.
"""


from app.utils import extract_video_id, is_valid_youtube_url


class TestExtractVideoId:
    """Tests for extract_video_id function."""

    def test_extract_from_watch_url(self):
        """Test extracting video ID from standard watch URL."""
        assert (
            extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            == "dQw4w9WgXcQ"
        )

    def test_extract_from_watch_url_with_params(self):
        """Test extracting video ID from watch URL with additional parameters."""
        assert (
            extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10")
            == "dQw4w9WgXcQ"
        )
        assert (
            extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=xyz")
            == "dQw4w9WgXcQ"
        )

    def test_extract_from_youtu_be(self):
        """Test extracting video ID from youtu.be short URL."""
        assert (
            extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        )

    def test_extract_from_embed(self):
        """Test extracting video ID from embed URL."""
        assert (
            extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ")
            == "dQw4w9WgXcQ"
        )

    def test_extract_from_shorts(self):
        """Test extracting video ID from YouTube Shorts URL."""
        assert (
            extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ")
            == "dQw4w9WgXcQ"
        )

    def test_extract_from_shorts_with_params(self):
        """Test extracting video ID from shorts URL with parameters."""
        assert (
            extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ?feature=share")
            == "dQw4w9WgXcQ"
        )

    def test_extract_raw_video_id(self):
        """Test extracting when input is already a raw video ID."""
        assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_extract_invalid_url(self):
        """Test extracting from invalid URL returns None."""
        assert (
            extract_video_id("https://example.com/watch?v=123") is None
        )
        assert extract_video_id("not-a-url") is None

    def test_extract_empty_string(self):
        """Test extracting from empty string returns None."""
        assert extract_video_id("") is None

    def test_extract_m_short_url(self):
        """Test extracting from mobile URL."""
        assert (
            extract_video_id("https://m.youtube.com/watch?v=dQw4w9WgXcQ")
            == "dQw4w9WgXcQ"
        )


class TestIsValidYoutubeUrl:
    """Tests for is_valid_youtube_url function."""

    def test_valid_watch_url(self):
        """Test validation of standard watch URL."""
        assert (
            is_valid_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            is True
        )

    def test_valid_youtu_be(self):
        """Test validation of youtu.be URL."""
        assert is_valid_youtube_url("https://youtu.be/dQw4w9WgXcQ") is True

    def test_valid_embed(self):
        """Test validation of embed URL."""
        assert (
            is_valid_youtube_url("https://www.youtube.com/embed/dQw4w9WgXcQ")
            is True
        )

    def test_valid_shorts(self):
        """Test validation of shorts URL."""
        assert (
            is_valid_youtube_url("https://www.youtube.com/shorts/dQw4w9WgXcQ")
            is True
        )

    def test_valid_raw_id(self):
        """Test validation of raw 11-character video ID."""
        assert is_valid_youtube_url("dQw4w9WgXcQ") is True

    def test_valid_with_query_params(self):
        """Test validation of URL with query parameters."""
        assert (
            is_valid_youtube_url(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10"
            )
            is True
        )

    def test_invalid_scheme(self):
        """Test that non-HTTP schemes are rejected."""
        assert (
            is_valid_youtube_url("ftp://youtube.com/watch?v=dQw4w9WgXcQ") is False
        )
        assert is_valid_youtube_url("javascript://youtube.com") is False

    def test_invalid_domain(self):
        """Test that non-YouTube domains are rejected."""
        assert (
            is_valid_youtube_url(
                "https://evil.com?ref=youtube.com/watch?v=dQw4w9WgXcQ"
            )
            is False
        )
        assert (
            is_valid_youtube_url("https://fakeyoutube.com/watch?v=dQw4w9WgXcQ")
            is False
        )

    def test_invalid_video_id_length(self):
        """Test that invalid video ID lengths are rejected."""
        assert is_valid_youtube_url("dQw4w9Wg") is False
        assert is_valid_youtube_url("toolongvideoid123") is False

    def test_empty_url(self):
        """Test that empty string is rejected."""
        assert is_valid_youtube_url("") is False

    def test_http_vs_https(self):
        """Test that both HTTP and HTTPS are accepted."""
        assert (
            is_valid_youtube_url("http://youtube.com/watch?v=dQw4w9WgXcQ") is True
        )
        assert (
            is_valid_youtube_url("https://youtube.com/watch?v=dQw4w9WgXcQ") is True
        )

    def test_mobile_url(self):
        """Test that mobile YouTube URLs are accepted."""
        assert (
            is_valid_youtube_url("https://m.youtube.com/watch?v=dQw4w9WgXcQ")
            is True
        )
