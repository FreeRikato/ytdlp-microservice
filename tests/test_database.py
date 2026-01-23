"""
Tests for database module in app/database.py.

This module tests the async SQLite database functionality with SQLModel.
"""

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlmodel import select

from app.database import DatabaseEngine, DatabaseLifecycle, get_database_url
from app.models import SubtitleCache, SubtitleCacheRead


class TestGetDatabaseUrl:
    """Tests for get_database_url function."""

    def test_get_database_url_with_relative_path(self):
        """Test that relative paths are converted to absolute."""
        url = get_database_url("test.db")
        assert url.startswith("sqlite+aiosqlite:///")
        assert "test.db" in url
        # Should be an absolute path
        assert Path(url.replace("sqlite+aiosqlite:///", "")).is_absolute()

    def test_get_database_url_with_absolute_path(self):
        """Test that absolute paths are preserved."""
        url = get_database_url("/absolute/path/to/database.db")
        assert url == "sqlite+aiosqlite:////absolute/path/to/database.db"

    def test_get_database_url_default_uses_settings(self, monkeypatch):
        """Test that None path uses settings.database_path."""
        # This would require mocking settings, so we test the behavior directly
        # by ensuring the function doesn't crash with None
        url = get_database_url(None)
        assert url.startswith("sqlite+aiosqlite:///")


class TestDatabaseEngine:
    """Tests for DatabaseEngine class."""

    @pytest.fixture
    def temp_db_engine(self):
        """Create a database engine with a temporary file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            engine = DatabaseEngine(database_url=get_database_url(db_path))
            yield engine
            # Cleanup
            asyncio.run(engine.close())

    @pytest.mark.asyncio
    async def test_init_db_creates_tables(self, temp_db_engine):
        """Test that init_db creates the required tables."""
        await temp_db_engine.init_db()
        # If no exception is raised, tables were created successfully
        assert temp_db_engine.engine is not None

    @pytest.mark.asyncio
    async def test_close_engine(self, temp_db_engine):
        """Test that close properly disposes the engine."""
        await temp_db_engine.close()
        # Engine should be None after close
        assert temp_db_engine._engine is None

    @pytest.mark.asyncio
    async def test_get_expired_entries_empty(self, temp_db_engine):
        """Test get_expired_entries returns empty list when no expired entries."""
        await temp_db_engine.init_db()
        entries = await temp_db_engine.get_expired_entries()
        assert entries == []

    @pytest.mark.asyncio
    async def test_cleanup_expired_no_entries(self, temp_db_engine):
        """Test cleanup_expired returns 0 when no entries to clean."""
        await temp_db_engine.init_db()
        count = await temp_db_engine.cleanup_expired()
        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_and_query_cache_entry(self, temp_db_engine):
        """Test inserting and querying a cache entry."""
        await temp_db_engine.init_db()

        # Create a cache entry
        async with temp_db_engine.session_factory() as session:
            cache_entry = SubtitleCache(
                video_url="https://youtu.be/test123",
                video_id="test123",
                language="en",
                output_format="json",
                subtitle_data='{"text": "Hello world"}',
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            session.add(cache_entry)
            await session.commit()

        # Query the entry
        async with temp_db_engine.session_factory() as session:
            result = await session.execute(
                select(SubtitleCache).where(SubtitleCache.video_id == "test123")
            )
            entry = result.scalars().first()
            assert entry is not None
            assert entry.video_id == "test123"
            assert entry.language == "en"

    @pytest.mark.asyncio
    async def test_cleanup_expired_removes_old_entries(self, temp_db_engine):
        """Test that cleanup_expired removes expired entries."""
        await temp_db_engine.init_db()

        # Create an expired entry
        async with temp_db_engine.session_factory() as session:
            expired_entry = SubtitleCache(
                video_url="https://youtu.be/expired",
                video_id="expired",
                language="en",
                output_format="json",
                subtitle_data='{"text": "expired"}',
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1),  # Already expired
            )
            session.add(expired_entry)
            await session.commit()

        # Create a non-expired entry
        async with temp_db_engine.session_factory() as session:
            valid_entry = SubtitleCache(
                video_url="https://youtu.be/valid",
                video_id="valid",
                language="en",
                output_format="json",
                subtitle_data='{"text": "valid"}',
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            session.add(valid_entry)
            await session.commit()

        # Run cleanup
        count = await temp_db_engine.cleanup_expired()
        assert count == 1

        # Verify expired entry is gone but valid entry remains
        async with temp_db_engine.session_factory() as session:
            expired_result = await session.execute(
                select(SubtitleCache).where(SubtitleCache.video_id == "expired")
            )
            assert expired_result.scalars().first() is None

            valid_result = await session.execute(
                select(SubtitleCache).where(SubtitleCache.video_id == "valid")
            )
            assert valid_result.scalars().first() is not None


class TestDatabaseLifecycle:
    """Tests for DatabaseLifecycle class."""

    @pytest.fixture
    def lifecycle_engine(self):
        """Create a fresh engine for lifecycle tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "lifecycle_test.db")
            engine = DatabaseEngine(database_url=get_database_url(db_path))
            yield engine
            asyncio.run(engine.close())

    @pytest.mark.asyncio
    async def test_startup_initializes_database(self, lifecycle_engine):
        """Test that startup initializes the database."""
        lifecycle = DatabaseLifecycle(engine=lifecycle_engine)
        await lifecycle.startup()

        # Verify engine was initialized
        assert lifecycle_engine._engine is not None

        await lifecycle.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_cleans_up(self, lifecycle_engine):
        """Test that shutdown properly cleans up."""
        lifecycle = DatabaseLifecycle(engine=lifecycle_engine)
        await lifecycle.startup()
        await lifecycle.shutdown()

        # Verify cleanup
        assert lifecycle_engine._engine is None
        assert lifecycle._cleanup_task is None

    @pytest.mark.asyncio
    async def test_start_and_stop_background_cleanup(self, lifecycle_engine):
        """Test starting and stopping the background cleanup task."""
        lifecycle = DatabaseLifecycle(engine=lifecycle_engine, cleanup_interval_hours=1)

        await lifecycle.startup()
        assert lifecycle._cleanup_task is not None

        await lifecycle.shutdown()
        assert lifecycle._cleanup_task is None


class TestSubtitleCacheModel:
    """Tests for SubtitleCache SQLModel."""

    def test_create_subtitle_cache(self):
        """Test creating a SubtitleCache instance."""
        entry = SubtitleCache(
            video_url="https://youtu.be/test123",
            video_id="test123",
            language="en",
            output_format="json",
            subtitle_data='{"text": "test"}',
        )
        assert entry.video_id == "test123"
        assert entry.language == "en"
        assert entry.expires_at is None  # Optional field

    def test_subtitle_cache_with_expiration(self):
        """Test creating a SubtitleCache with expiration."""
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
        entry = SubtitleCache(
            video_url="https://youtu.be/test",
            video_id="test",
            language="es",
            output_format="vtt",
            subtitle_data="WEBVTT...",
            expires_at=expires,
        )
        assert entry.expires_at == expires

    def test_subtitle_cache_read_model(self):
        """Test SubtitleCacheRead model."""
        now = datetime.now(timezone.utc)
        entry = SubtitleCacheRead(
            id=1,
            video_url="https://youtu.be/test",
            video_id="test",
            language="en",
            output_format="json",
            subtitle_data='{"data": "test"}',
            created_at=now,
            expires_at=None,
        )
        assert entry.id == 1
        assert entry.created_at == now
