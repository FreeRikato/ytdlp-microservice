"""Middleware tests for security headers and request ID."""

from unittest.mock import patch, MagicMock



class TestSecurityHeadersMiddleware:
    """Tests for SecurityHeadersMiddleware."""

    def test_security_headers_present(self, client):
        """Test that security headers are present in response."""
        response = client.get("/")

        assert response.status_code == 200
        assert "X-Content-Type-Options" in response.headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "X-Frame-Options" in response.headers
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "Content-Security-Policy" in response.headers

    def test_csp_allows_swagger_ui(self, client):
        """Test that CSP allows scripts for Swagger UI paths."""
        # Test /docs path
        response = client.get("/docs")
        csp = response.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        # Swagger UI needs 'unsafe-inline' for scripts
        assert "'unsafe-inline'" in csp or "script-src" in csp

    def test_csp_restricts_non_swagger_paths(self, client):
        """Test that CSP is more restrictive for non-Swagger paths."""
        response = client.get("/")
        csp = response.headers.get("Content-Security-Policy", "")
        # Regular API paths should have stricter CSP
        assert "default-src 'self'" in csp

    def test_no_x_xss_protection_header(self, client):
        """Test that deprecated X-XSS-Protection header is not present."""
        response = client.get("/")
        assert "X-XSS-Protection" not in response.headers


class TestRequestIdMiddleware:
    """Tests for RequestIdMiddleware."""

    def test_request_id_header_present(self, client):
        """Test that X-Request-ID header is present in response."""
        response = client.get("/")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        # Should be a valid UUID
        request_id = response.headers["X-Request-ID"]
        assert len(request_id) == 36  # UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

    def test_request_id_from_header(self, client):
        """Test that X-Request-ID header from request is used if provided."""
        custom_id = "custom-request-id-12345"
        response = client.get("/", headers={"X-Request-ID": custom_id})

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == custom_id

    def test_request_id_on_health_endpoint(self, client):
        """Test that X-Request-ID is present on health endpoint."""
        response = client.get("/health")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers


class TestMiddlewareIntegration:
    """Integration tests for middleware stack."""

    def test_all_security_headers_on_api_endpoint(self, client):
        """Test that all security headers are present on API endpoint."""
        with patch("app.service.yt_dlp.YoutubeDL") as mock_ydl:
            mock_instance = MagicMock()
            mock_instance.extract_info = MagicMock(
                return_value={"id": "dQw4w9WgXcQ"}
            )
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_ydl.return_value = mock_instance

            # Mock VTT file
            import tempfile
            vtt_content = """WEBVTT

00:00:00.000 --> 00:00:03.500
Hello world
"""
            with tempfile.NamedTemporaryFile(mode='w', suffix='.vtt', delete=False) as f:
                f.write(vtt_content)
                vtt_path = f.name

            import os
            with patch("tempfile.TemporaryDirectory") as mock_tempdir:
                mock_cm = MagicMock()
                mock_cm.__enter__ = MagicMock(return_value=os.path.dirname(vtt_path))
                mock_cm.__exit__ = MagicMock(return_value=False)
                mock_tempdir.return_value = mock_cm

                response = client.get(
                    "/api/v1/subtitles?video_url=https://youtu.be/dQw4w9WgXcQ&lang=en&format=json"
                )

        # Verify security headers
        assert "X-Content-Type-Options" in response.headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "X-Frame-Options" in response.headers
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "Content-Security-Policy" in response.headers
        assert "X-Request-ID" in response.headers

        # Cleanup
        os.unlink(vtt_path)
