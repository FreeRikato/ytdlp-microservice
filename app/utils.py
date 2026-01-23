"""
Shared utility functions for the ytdlp-microservice.

This module provides common functions used across multiple modules.
"""

import re


# YouTube video ID patterns - handles various URL formats including those
# with additional query parameters (e.g., ?t=10, &list=xyz)
YOUTUBE_PATTERNS = [
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})",
    r"^([a-zA-Z0-9_-]{11})$",  # Raw video ID
]


def extract_video_id(url: str) -> str | None:
    """
    Extract video ID from a YouTube URL or return the input if it's a raw ID.

    This function handles various YouTube URL formats:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
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
    for pattern in YOUTUBE_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def is_valid_youtube_url(url: str) -> bool:
    """
    Validate that a URL is a valid YouTube URL.

    This function accepts various YouTube URL formats including those with
    additional query parameters.

    Args:
        url: URL to validate

    Returns:
        True if valid YouTube URL, False otherwise

    Examples:
        >>> is_valid_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        True
        >>> is_valid_youtube_url("https://youtu.be/dQw4w9WgXcQ")
        True
        >>> is_valid_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10")
        True
        >>> is_valid_youtube_url("not-a-url")
        False
    """
    return extract_video_id(url) is not None
