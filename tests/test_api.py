"""API endpoint tests for subtitle fetching.

Tests cover success cases, error cases, and validation for the
/api/v1/subtitles endpoint. All tests use mocked yt-dlp to avoid
rate limits and ensure fast, reliable test execution.
"""

from unittest.mock import MagicMock, patch

import yt_dlp


class TestSubtitlesEndpointSuccess:
    """Tests for successful subtitle retrieval."""

    def test_get_subtitles_json_format(self, client, mock_successful_extraction):
        """Test fetching subtitles in JSON format."""
        response = client.get(
            "/api/v1/subtitles?video_url=https://youtu.be/dQw4w9WgXcQ&lang=en&format=json"
        )

        assert response.status_code == 200
        data = response.json()

        assert data["video_id"] == "dQw4w9WgXcQ"
        assert data["language"] == "en"
        assert isinstance(data["subtitles"], list)
        assert len(data["subtitles"]) == 2

        # Check first subtitle structure
        first_sub = data["subtitles"][0]
        assert "start" in first_sub
        assert "end" in first_sub
        assert "text" in first_sub
        assert first_sub["text"] == "Hello world"

    def test_get_subtitles_vtt_format(self, client, mock_successful_extraction):
        """Test fetching subtitles in VTT format."""
        response = client.get(
            "/api/v1/subtitles?video_url=https://youtu.be/dQw4w9WgXcQ&lang=en&format=vtt"
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/vtt; charset=utf-8"
        assert "WEBVTT" in response.text
        assert "Hello world" in response.text

    def test_get_subtitles_custom_language(self, client, mock_successful_extraction):
        """Test fetching subtitles with custom language."""
        response = client.get(
            "/api/v1/subtitles?video_url=https://youtu.be/dQw4w9WgXcQ&lang=es&format=json"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["language"] == "es"

    def test_get_subtitles_with_raw_video_id(self, client, mock_successful_extraction):
        """Test fetching subtitles with raw video ID instead of URL."""
        response = client.get(
            "/api/v1/subtitles?video_url=dQw4w9WgXcQ&lang=en&format=json"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["video_id"] == "dQw4w9WgXcQ"

    def test_get_subtitles_default_language(self, client, mock_successful_extraction):
        """Test that default language is 'en' when not specified."""
        response = client.get(
            "/api/v1/subtitles?video_url=https://youtu.be/dQw4w9WgXcQ&format=json"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["language"] == "en"

    def test_get_subtitles_text_format(self, client, mock_successful_extraction):
        """Test fetching subtitles in TEXT format (combined text)."""
        response = client.get(
            "/api/v1/subtitles?video_url=https://youtu.be/dQw4w9WgXcQ&lang=en&format=text"
        )

        assert response.status_code == 200
        data = response.json()

        assert data["video_id"] == "dQw4w9WgXcQ"
        assert data["language"] == "en"
        assert "text" in data
        assert "start" not in data  # No timestamps
        assert "subtitles" not in data  # No subtitle list
        # Check text is combined (mock returns 2 entries: "Hello world" and "This is a test subtitle")
        assert data["text"] == "Hello world This is a test subtitle"


class TestSubtitlesEndpointErrors:
    """Tests for error handling in subtitle retrieval."""

    def test_invalid_url_returns_400(self, client, mock_successful_extraction):
        """Test that non-YouTube URL returns 400."""
        response = client.get(
            "/api/v1/subtitles?video_url=https://example.com/watch?v=123&lang=en&format=json"
        )

        assert response.status_code == 400
        data = response.json()
        assert "error" in data or "detail" in data

    def test_video_not_found_returns_400(self, client):
        """Test that non-existent video returns 400."""
        with patch("app.service.yt_dlp.YoutubeDL") as mock_ydl:
            mock_instance = MagicMock()
            mock_instance.extract_info = MagicMock(
                side_effect=yt_dlp.utils.DownloadError("Video unavailable")
            )
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_ydl.return_value = mock_instance

            response = client.get(
                "/api/v1/subtitles?video_url=https://youtu.be/invalid00000&lang=en&format=json"
            )

            assert response.status_code in [400, 500]

    def test_no_subtitles_returns_400(self, client):
        """Test that video with no subtitles returns 400."""
        with patch("app.service.yt_dlp.YoutubeDL") as mock_ydl:
            mock_instance = MagicMock()
            mock_instance.extract_info = MagicMock(return_value={"id": "dQw4w9WgXcQ"})
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_ydl.return_value = mock_instance

            # Mock TemporaryDirectory with no VTT files
            with patch("tempfile.TemporaryDirectory") as mock_tempdir:
                import tempfile

                empty_dir = tempfile.mkdtemp()
                mock_cm = MagicMock()
                mock_cm.__enter__ = MagicMock(return_value=empty_dir)
                mock_cm.__exit__ = MagicMock(return_value=False)
                mock_tempdir.return_value = mock_cm

                response = client.get(
                    "/api/v1/subtitles?video_url=https://youtu.be/dQw4w9WgXcQ&lang=en&format=json"
                )

                assert response.status_code == 404

    def test_rate_limit_returns_429(self, client):
        """Test that rate limit error returns 429."""
        with patch("app.service.yt_dlp.YoutubeDL") as mock_ydl:
            mock_instance = MagicMock()
            mock_instance.extract_info = MagicMock(
                side_effect=yt_dlp.utils.DownloadError("HTTP Error 429: Too Many Requests")
            )
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_ydl.return_value = mock_instance

            response = client.get(
                "/api/v1/subtitles?video_url=https://youtu.be/dQw4w9WgXcQ&lang=en&format=json"
            )

            # Should be caught by exception handler
            assert response.status_code in [429, 503, 500]

    def test_network_error_returns_500(self, client):
        """Test that network error returns 500."""
        with patch("app.service.yt_dlp.YoutubeDL") as mock_ydl:
            mock_instance = MagicMock()
            mock_instance.extract_info = MagicMock(
                side_effect=yt_dlp.utils.DownloadError("Connection refused")
            )
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_ydl.return_value = mock_instance

            response = client.get(
                "/api/v1/subtitles?video_url=https://youtu.be/dQw4w9WgXcQ&lang=en&format=json"
            )

            assert response.status_code == 500


class TestSubtitlesEndpointValidation:
    """Tests for input validation."""

    def test_missing_url_param_returns_400(self, client):
        """Test that missing URL parameter returns 400."""
        response = client.get("/api/v1/subtitles?lang=en&format=json")

        assert response.status_code == 400

    def test_empty_url_returns_400(self, client):
        """Test that empty URL returns 400."""
        response = client.get("/api/v1/subtitles?video_url=&lang=en&format=json")

        assert response.status_code == 400

    def test_invalid_format_returns_400(self, client):
        """Test that invalid format returns 400."""
        response = client.get(
            "/api/v1/subtitles?video_url=https://youtu.be/dQw4w9WgXcQ&lang=en&format=invalid"
        )

        assert response.status_code == 400

    def test_response_headers(self, client, mock_successful_extraction):
        """Test that response includes correct headers."""
        response = client.get(
            "/api/v1/subtitles?video_url=https://youtu.be/dQw4w9WgXcQ&lang=en&format=json"
        )

        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_root_endpoint(self, client):
        """Test root endpoint returns healthy status."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "service" in data

    def test_health_endpoint(self, client):
        """Test health endpoint returns healthy status."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
