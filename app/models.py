"""
SQLModel database models for the YouTube subtitle extraction microservice.

These models define the database schema for persistent caching and
other data storage needs.
"""

from datetime import datetime, timedelta, timezone

from sqlmodel import Field, SQLModel, UniqueConstraint

# Default TTL for cache entries (24 hours)
DEFAULT_CACHE_TTL_HOURS = 24


def utcnow() -> datetime:
    """Return current UTC time as naive datetime for SQLite compatibility.

    SQLite stores datetimes as strings without timezone info. When retrieved,
    they become timezone-naive datetimes. Using naive datetimes consistently
    prevents comparison errors between aware and naive datetimes.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_expires_at(ttl_hours: int = DEFAULT_CACHE_TTL_HOURS) -> datetime:
    """Return expiration time based on TTL.

    Args:
        ttl_hours: Time-to-live in hours

    Returns:
        Expiration datetime
    """
    return utcnow() + timedelta(hours=ttl_hours)


class SubtitleCacheBase(SQLModel):
    """Base model for subtitle cache entries."""

    video_url: str = Field(index=True, max_length=500, description="YouTube video URL or ID")
    video_id: str = Field(index=True, max_length=50, description="YouTube video ID")
    language: str = Field(index=True, max_length=20, description="Language code")
    output_format: str = Field(index=True, max_length=20, description="Output format (json, vtt, text)")
    subtitle_data: str = Field(description="Serialized subtitle data (JSON for json/text, raw VTT for vtt)")
    created_at: datetime = Field(default_factory=utcnow, description="When the entry was cached")


class SubtitleCache(SubtitleCacheBase, table=True):
    """
    Persistent cache table for subtitle extraction results.

    This table stores subtitle extraction results for faster subsequent
    retrieval. It complements the in-memory TTL cache for durability.
    """

    id: int | None = Field(default=None, primary_key=True, description="Unique cache entry ID")
    expires_at: datetime | None = Field(
        default=None,
        index=True,
        description="Optional expiration time",
    )

    __table_args__ = (
        UniqueConstraint("video_url", "language", "output_format", name="uq_subtitle_cache_lookup"),
    )


class SubtitleCacheCreate(SQLModel):
    """Model for creating a new cache entry."""

    video_url: str
    video_id: str
    language: str
    output_format: str
    subtitle_data: str


class SubtitleCacheRead(SubtitleCacheBase):
    """Model for reading a cache entry."""

    id: int
    expires_at: datetime | None = None
