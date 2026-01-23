"""
Shared utility functions for the ytdlp-microservice.

This module provides common functions used across multiple modules.
"""

import re
from urllib.parse import urlparse


# Pre-compiled regex patterns for performance
YOUTUBE_PATTERN_COMPILED = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})"
)
YOUTUBE_ID_PATTERN_COMPILED = re.compile(r"^([a-zA-Z0-9_-]{11})$")


# YouTube video ID patterns - handles various URL formats including those
# with additional query parameters (e.g., ?t=10, &list=xyz)
YOUTUBE_PATTERNS = [
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})",
    r"^([a-zA-Z0-9_-]{11})$",  # Raw video ID
]


def extract_video_id(url: str) -> str | None:
    """
    Extract video ID from a YouTube URL or return the input if it's a raw ID.

    This function handles various YouTube URL formats:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    - https://www.youtube.com/shorts/VIDEO_ID
    - Raw 11-character video ID
    - URLs with additional query parameters (e.g., ?t=10, &list=xyz)

    Args:
        url: YouTube URL or video ID

    Returns:
        11-character YouTube video ID, or None if not found

    Examples:
        >>> extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        'dQw4w9WgXcQ'
        >>> extract_video_id("https://youtu.be/dQw4w9WgXcQ")
        'dQw4w9WgXcQ'
        >>> extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10")
        'dQw4w9WgXcQ'
        >>> extract_video_id("dQw4w9WgXcQ")
        'dQw4w9WgXcQ'
    """
    # Try full URL pattern first (includes shorts support)
    match = YOUTUBE_PATTERN_COMPILED.search(url)
    if match:
        return match.group(1)

    # Try raw video ID pattern
    match = YOUTUBE_ID_PATTERN_COMPILED.match(url)
    if match:
        return match.group(1)

    return None


def is_valid_youtube_url(url: str) -> bool:
    """
    Validate that a URL is a valid YouTube URL with strict scheme and host validation.

    This function accepts various YouTube URL formats including those with
    additional query parameters, but rejects URLs with invalid schemes or hosts.

    Args:
        url: URL to validate

    Returns:
        True if valid YouTube URL, False otherwise

    Examples:
        >>> is_valid_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        True
        >>> is_valid_youtube_url("https://youtu.be/dQw4w9WgXcQ")
        True
        >>> is_valid_youtube_url("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        True
        >>> is_valid_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10")
        True
        >>> is_valid_youtube_url("dQw4w9WgXcQ")
        True
        >>> is_valid_youtube_url("https://evil.com?ref=youtube.com/watch?v=VIDEO_ID")
        False
        >>> is_valid_youtube_url("ftp://youtube.com/watch?v=dQw4w9WgXcQ")
        False
        >>> is_valid_youtube_url("not-a-url")
        False
    """
    # Allow raw 11-character video IDs
    if YOUTUBE_ID_PATTERN_COMPILED.match(url):
        return True

    # Require http or https scheme
    if not url.startswith(("http://", "https://")):
        return False

    # Parse and validate domain to prevent SSRF/bypass attacks
    try:
        parsed = urlparse(url)
        valid_hosts = {
            "youtube.com",
            "www.youtube.com",
            "youtu.be",
            "m.youtube.com",
        }
        if parsed.netloc not in valid_hosts:
            return False
    except Exception:
        return False

    return extract_video_id(url) is not None
