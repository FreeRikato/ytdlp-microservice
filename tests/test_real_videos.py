"""Smoke tests with real YouTube videos.

These tests make actual network calls to YouTube and should be run
sparingly to avoid rate limiting. Mark with @pytest.mark.slow to
skip during normal development.

Run with: pytest -m slow
Skip slow tests: pytest -m "not slow"
"""

import pytest

# Use a popular, reliable video with subtitles
# "Me at the zoo" - the first YouTube video
TEST_VIDEO_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
TEST_VIDEO_ID = "jNQXAC9IVRw"


@pytest.mark.slow
def test_real_video_fetch_subtitles_json():
    """Test fetching JSON subtitles from a real YouTube video."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    response = client.get(
        f"/api/v1/subtitles?video_url={TEST_VIDEO_URL}&lang=en&format=json"
    )

    # Should succeed
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()

    # Check response structure
    assert data["video_id"] == TEST_VIDEO_ID
    assert data["language"] == "en"
    assert isinstance(data["subtitles"], list)
    assert len(data["subtitles"]) > 0, "Expected at least one subtitle"

    # Check subtitle entry structure
    first_sub = data["subtitles"][0]
    assert "start" in first_sub
    assert "end" in first_sub
    assert "text" in first_sub
    assert len(first_sub["text"]) > 0, "Subtitle text should not be empty"


@pytest.mark.slow
def test_real_video_fetch_subtitles_vtt():
    """Test fetching VTT subtitles from a real YouTube video."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    response = client.get(
        f"/api/v1/subtitles?video_url={TEST_VIDEO_URL}&lang=en&format=vtt"
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    assert response.headers["content-type"] == "text/vtt; charset=utf-8"
    assert "WEBVTT" in response.text

    # VTT should have some content
    lines = response.text.strip().split("\n")
    assert len(lines) > 5, "VTT file should have multiple lines"


@pytest.mark.slow
def test_real_video_with_raw_id():
    """Test fetching subtitles using raw video ID instead of URL."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    response = client.get(
        f"/api/v1/subtitles?video_url={TEST_VIDEO_ID}&lang=en&format=json"
    )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()

    assert data["video_id"] == TEST_VIDEO_ID
    assert len(data["subtitles"]) > 0
