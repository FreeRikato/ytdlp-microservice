"""
Subtitle extraction service using yt-dlp with anti-bot detection strategies.

This module implements the core logic for extracting YouTube subtitles while
bypassing YouTube's bot detection mechanisms that cause HTTP 429 errors.

References:
    - GitHub Issue #13831: HTTP Error 429 when downloading auto-translated subtitles
    - GitHub Issue #13770: Recent changes to YouTube's bot detection

Anti-Blocking Strategies (in order of priority):
    1. Browser Impersonation: TLS fingerprint spoofing to mimic Chrome
    2. Aggressive Throttling: Sleep between requests to stay under rate limits
    3. Client Source Spoofing: Use non-web client to avoid PO Token requirement
    4. Error Fallbacks: Graceful degradation on partial failures
"""

import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bleach
import yt_dlp
from yt_dlp.networking.impersonate import ImpersonateTarget

from app.config import Settings
from app.utils import extract_video_id

logger = logging.getLogger(__name__)


@dataclass
class SubtitleEntry:
    """
    A single subtitle entry with timing and text.

    Attributes:
        start: Start timestamp in VTT format (HH:MM:SS.mmm)
        end: End timestamp in VTT format (HH:MM:SS.mmm)
        text: The subtitle text content
    """

    start: str
    end: str
    text: str


class SubtitleExtractor:
    """
    Handles YouTube subtitle extraction with anti-bot detection strategies.

    This class configures yt-dlp with specific options to bypass YouTube's
    bot detection and extract auto-generated or manual subtitles.
    """

    # VTT timestamp pattern: HH:MM:SS.mmm --> HH:MM:SS.mmm
    # Also handles MM:SS.mmm format for shorter videos
    # Uses \d+ for hours to handle videos of any length (including >99 hours)
    TIMESTAMP_PATTERN = re.compile(
        r"(\d+:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d+:\d{2}:\d{2}\.\d{3})"
    )
    TIMESTAMP_PATTERN_SHORT = re.compile(
        r"(\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}\.\d{3})"
    )

    # Pattern to remove all HTML/XML-style tags from subtitle text
    # Note: We use bleach for proper HTML sanitization to prevent XSS
    TAG_REMOVAL_PATTERN = re.compile(r"<[^>]*>")

    def __init__(self, config: Settings | None = None):
        """
        Initialize the extractor with configuration.

        Args:
            config: Settings instance. Uses global defaults if None.
        """
        self.config = config or Settings()

    def _build_ydl_options(self, lang: str, out_dir: str) -> dict:
        """
        Build yt-dlp options dictionary with anti-blocking strategies.

        This method constructs the configuration that bypasses YouTube's
        bot detection mechanisms.

        Args:
            lang: Language code for subtitles (e.g., 'en', 'es')
            out_dir: Temporary output directory for subtitle files

        Returns:
            Dictionary of yt-dlp options

        Note:
            Anti-blocking strategies are documented inline below.
        """
        return {
            # ========== Strategy A: Browser Impersonation (Primary Defense) ==========
            # References GitHub issues #13831, #13770
            # YouTube detects Python requests via TLS handshake fingerprinting.
            # By impersonating Chrome, we match the expected TLS fingerprint.
            # This is the MOST effective strategy against 429 errors.
            "impersonate": ImpersonateTarget.from_str(self.config.ytdlp_impersonate_target),
            # ========== Strategy B: Aggressive Throttling ==========
            # YouTube's rate limiting triggers on rapid subtitle requests.
            # Adding a sleep interval keeps us under the detection threshold.
            # 60 seconds is conservative based on community testing in late 2024.
            "sleep_subtitles": self.config.ytdlp_sleep_seconds,
            # ========== Strategy C: Client Source Spoofing ==========
            # The 'web' client now requires a PO Token (Proof of Origin Token).
            # By using 'default,-web', we skip the web client entirely.
            # The '-web' suffix explicitly excludes the web client.
            "extractor_args": {
                "youtube": {
                    "player_client": ["default,-web"]
                }
            },
            # ========== Strategy D: Error Fallbacks ==========
            # Continue extraction even if some streams fail
            "ignoreerrors": True,
            # Enable both manual and auto-generated subtitles
            "writesubtitles": True,
            "writeautomaticsub": True,
            # Only download subtitles for the requested language
            "subtitleslangs": [lang],
            # Don't download video/audio - we only want subtitles
            "skip_download": True,
            # Output configuration
            "outtmpl": f"{out_dir}/%(id)s.%(ext)s",
            "subtitlesformat": "vtt",
            # Keep logging enabled for debugging 429 errors
            "quiet": False,
            "no_warnings": False,
            "logger": logger,
        }

    def _parse_vtt_to_json(self, vtt_content: str) -> list[SubtitleEntry]:
        """
        Parse WebVTT content into structured subtitle entries.

        Args:
            vtt_content: Raw VTT file content as string

        Returns:
            List of SubtitleEntry objects with start, end, and text

        Note:
            Handles standard VTT format with timestamps in HH:MM:SS.mmm format.
            Skips VTT header, style blocks, and empty lines.
        """
        entries = []
        lines = vtt_content.split("\n")

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Skip VTT header, empty lines, and NOTE/STYLE blocks
            if not line or line.startswith("WEBVTT") or line in ("NOTE", "STYLE"):
                i += 1
                continue

            # Try to match timestamp line
            timestamp_match = self.TIMESTAMP_PATTERN.search(line)
            if not timestamp_match:
                # Try short format (MM:SS.mmm)
                timestamp_match = self.TIMESTAMP_PATTERN_SHORT.search(line)
                if timestamp_match:
                    # Convert short format to long format
                    start, end = timestamp_match.groups()
                    start = f"00:{start}"
                    end = f"00:{end}"
                else:
                    i += 1
                    continue
            else:
                start, end = timestamp_match.groups()

            # Collect subtitle text (may span multiple lines)
            text_lines = []
            i += 1
            while i < len(lines) and lines[i].strip():
                text_line = lines[i].strip()
                # First remove angle brackets (for things like <00:00:02.500> timestamps)
                text_line = self.TAG_REMOVAL_PATTERN.sub("", text_line)
                # Then use bleach to sanitize any remaining HTML for security
                text_line = bleach.clean(text_line, tags=[], strip=True)
                if text_line and text_line not in ("NOTE", "STYLE"):
                    text_lines.append(text_line)
                i += 1

            if text_lines:
                text = " ".join(text_lines)
                # Remove duplicate spaces
                text = re.sub(r"\s+", " ", text).strip()
                entries.append(SubtitleEntry(start=start, end=end, text=text))

        return entries

    def extract_subtitles(
        self, video_url: str, lang: str = "en", output_format: str = "json"
    ) -> tuple[str, list[SubtitleEntry] | str]:
        """
        Extract subtitles from a YouTube video.

        Args:
            video_url: YouTube video URL
            lang: Language code for subtitles (default: "en")
            output_format: Either "json" or "vtt"

        Returns:
            Tuple of (video_id, subtitles_data)
            - For JSON: (video_id, list[SubtitleEntry])
            - For VTT: (video_id, raw_vtt_string)

        Raises:
            yt_dlp.utils.DownloadError: If extraction fails
            ValueError: If URL is invalid or no subtitles found

        Note:
            Uses a temporary directory that is automatically cleaned up
            after the function returns, even if an exception occurs.
        """
        video_id = extract_video_id(video_url)
        if video_id is None:
            raise ValueError(f"Could not extract video ID from URL: {video_url}")

        # Create temp directory that auto-cleans
        with tempfile.TemporaryDirectory(dir=self.config.ytdlp_temp_dir) as temp_dir:
            logger.info(f"Extracting subtitles for video {video_id} in language '{lang}'")

            options = self._build_ydl_options(lang, temp_dir)

            with yt_dlp.YoutubeDL(options) as ydl:
                # Run the extraction - this downloads the VTT file to temp_dir
                logger.info(f"Starting yt-dlp extraction with impersonate={self.config.ytdlp_impersonate_target}")
                _ = ydl.extract_info(video_url, download=True)  # Return value intentionally ignored; we read from disk instead

                # Find the downloaded VTT file
                temp_path = Path(temp_dir)
                vtt_files = list(temp_path.glob("*.vtt"))

                if not vtt_files:
                    raise ValueError(
                        f"No subtitles found for video {video_id} in language '{lang}'. "
                        f"The video may not have subtitles in this language."
                    )

                # Use the first VTT file found (prioritizes auto-generated)
                vtt_file = vtt_files[0]
                logger.info(f"Found subtitle file: {vtt_file.name}")

                vtt_content = vtt_file.read_text(encoding="utf-8")

                if not vtt_content.strip():
                    raise ValueError(f"Subtitle file is empty: {vtt_file.name}")

                # Return based on requested format
                if output_format == "vtt":
                    # Clean all HTML/XML-style tags from VTT content
                    # First remove angle brackets, then use bleach for HTML sanitization
                    cleaned_vtt = self.TAG_REMOVAL_PATTERN.sub("", vtt_content)
                    cleaned_vtt = bleach.clean(cleaned_vtt, tags=[], strip=True)
                    return video_id, cleaned_vtt
                else:
                    # Parse VTT to structured JSON
                    entries = self._parse_vtt_to_json(vtt_content)
                    if not entries:
                        raise ValueError(
                            f"Failed to parse subtitles from VTT file. "
                            f"The file may be malformed or use an unsupported format."
                        )
                    logger.info(f"Parsed {len(entries)} subtitle entries")
                    return video_id, entries

    def list_available_languages(self, video_url: str) -> tuple[str, list[dict[str, Any]]]:
        """
        List all available subtitle languages for a video.

        Args:
            video_url: YouTube video URL

        Returns:
            Tuple of (video_id, languages_list) where languages_list contains
            dictionaries with code, name, auto_generated, and formats keys

        Raises:
            ValueError: If URL is invalid or cannot extract video info
            yt_dlp.utils.DownloadError: If extraction fails
        """
        video_id = extract_video_id(video_url)
        if video_id is None:
            raise ValueError(f"Could not extract video ID from URL: {video_url}")

        options = {
            "skip_download": True,
            "listsubtitles": True,
            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(video_url, download=False)

            languages = []
            subs = info.get("subtitles", {})
            automatic_subs = info.get("automatic_captions", {})

            # Manual subtitles
            for lang_code, subs_list in subs.items():
                formats = [s.get("ext", "vtt") for s in subs_list] if isinstance(subs_list, list) else ["vtt"]
                languages.append({
                    "code": lang_code,
                    "name": lang_code,  # Could enhance with language name mapping
                    "auto_generated": False,
                    "formats": formats,
                })

            # Auto-generated subtitles (only if not already present)
            for lang_code, subs_list in automatic_subs.items():
                if lang_code not in [l["code"] for l in languages]:
                    formats = [s.get("ext", "vtt") for s in subs_list] if isinstance(subs_list, list) else ["vtt"]
                    languages.append({
                        "code": lang_code,
                        "name": lang_code,
                        "auto_generated": True,
                        "formats": formats,
                    })

            return video_id, languages


# Global extractor instance - reuses configuration across requests
def get_extractor() -> SubtitleExtractor:
    """
    Get a configured SubtitleExtractor instance.

    This function is used as a FastAPI dependency for dependency injection.
    """
    return SubtitleExtractor()
