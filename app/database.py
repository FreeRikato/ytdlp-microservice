"""
Async database module for SQLite using SQLModel.

This module provides async database connectivity with lifecycle management
for the YouTube subtitle extraction microservice.
"""

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from sqlmodel import SQLModel, select, delete, text

from app.models import SubtitleCache, utcnow, get_expires_at

logger = logging.getLogger(__name__)


def get_database_url(database_path: str | None = None) -> str:
    """
    Get the database URL, converting relative paths to absolute.

    Args:
        database_path: Path to database file (relative or absolute). If None, uses settings.

    Returns:
        SQLite database URL with absolute path
    """
    if database_path is None:
        from app.config import settings
        database_path = settings.database_path

    if not Path(database_path).is_absolute():
        # Make path relative to the app directory
        app_dir = Path(__file__).parent.parent
        database_path = str(app_dir / database_path)
    return f"sqlite+aiosqlite:///{database_path}"


class DatabaseEngine:
    """
    Async database engine manager with session factory.

    Provides async database connectivity for SQLite with proper
    lifecycle management for FastAPI applications.
    """

    def __init__(self, database_url: str | None = None, echo: bool = False):
        """
        Initialize the database engine.

        Args:
            database_url: SQLAlchemy database URL for async SQLite. If None, uses settings.
            echo: Whether to echo SQL statements (for debugging)
        """
        self._engine = None
        self._session_factory = None
        self._database_url = database_url
        self._echo = echo
        self._lock = threading.Lock()

    @property
    def database_url(self) -> str:
        """Get the database URL, resolving from settings if not set."""
        if self._database_url is None:
            from app.config import settings
            self._database_url = get_database_url(settings.database_path)
        return self._database_url

    @property
    def engine(self):
        """Get or create the async engine."""
        if self._engine is None:
            with self._lock:
                # Double-check after acquiring lock
                if self._engine is None:
                    self._engine = create_async_engine(
                        self.database_url,
                        echo=self._echo,
                        connect_args={"check_same_thread": False},
                        poolclass=NullPool,  # Better for SQLite
                        isolation_level="autocommit",  # Reduces locking issues with concurrent writes
                    )
                    logger.info(f"Created async database engine: {self.database_url}")
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Get or create the async session factory."""
        if self._session_factory is None:
            self._session_factory = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            logger.info("Created async session factory")
        return self._session_factory

    async def init_db(self) -> None:
        """
        Initialize database tables.

        Creates all tables defined in SQLModel metadata.
        This should be called on application startup.
        """
        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        logger.info("Database tables initialized")

    async def close(self) -> None:
        """Close the database engine and cleanup resources."""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("Database engine closed")

    async def get_expired_entries(self) -> list["SubtitleCache"]:
        """
        Get all expired cache entries.

        Returns:
            List of cache entries that have expired
        """
        async with self.session_factory() as session:
            now = utcnow()
            result = await session.execute(
                select(SubtitleCache).where(
                    SubtitleCache.expires_at.isnot(None),
                    SubtitleCache.expires_at < now
                )
            )
            return list(result.scalars().all())

    async def cleanup_expired(self) -> int:
        """
        Delete all expired cache entries.

        Returns:
            Number of entries deleted
        """
        async with self.session_factory() as session:
            now = utcnow()
            result = await session.execute(
                delete(SubtitleCache).where(
                    SubtitleCache.expires_at.isnot(None),
                    SubtitleCache.expires_at < now
                )
            )
            await session.commit()
            deleted_count = result.rowcount
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} expired cache entries")
            return deleted_count or 0

    async def get_cached_subtitle(
        self, video_url: str, language: str, output_format: str
    ) -> "SubtitleCache | None":
        """
        Get a cached subtitle entry from the database.

        Args:
            video_url: YouTube video URL or ID
            language: Language code
            output_format: Output format (json, vtt, text)

        Returns:
            SubtitleCache entry if found and not expired, None otherwise
        """
        async with self.session_factory() as session:
            result = await session.execute(
                select(SubtitleCache).where(
                    SubtitleCache.video_url == video_url,
                    SubtitleCache.language == language,
                    SubtitleCache.output_format == output_format,
                )
            )
            entry = result.scalars().first()
            if entry is None:
                return None

            # Check expiration
            if entry.expires_at is not None and entry.expires_at < utcnow():
                # Entry has expired, delete it
                await session.delete(entry)
                await session.commit()
                return None

            return entry

    async def set_cached_subtitle(
        self,
        video_url: str,
        video_id: str,
        language: str,
        output_format: str,
        subtitle_data: str,
        ttl_hours: int | None = None,
    ) -> "SubtitleCache":
        """
        Store a subtitle entry in the database cache.

        Args:
            video_url: YouTube video URL or ID
            video_id: YouTube video ID
            language: Language code
            output_format: Output format (json, vtt, text)
            subtitle_data: Serialized subtitle data
            ttl_hours: Time-to-live in hours (uses DEFAULT_CACHE_TTL_HOURS if None)

        Returns:
            Created SubtitleCache entry
        """
        async with self.session_factory() as session:
            # Check for existing entry
            result = await session.execute(
                select(SubtitleCache).where(
                    SubtitleCache.video_url == video_url,
                    SubtitleCache.language == language,
                    SubtitleCache.output_format == output_format,
                )
            )
            existing = result.scalars().first()

            expires_at = get_expires_at(ttl_hours) if ttl_hours else None

            if existing:
                # Update existing entry
                existing.subtitle_data = subtitle_data
                existing.expires_at = expires_at
                await session.commit()
                return existing

            # Create new entry
            entry = SubtitleCache(
                video_url=video_url,
                video_id=video_id,
                language=language,
                output_format=output_format,
                subtitle_data=subtitle_data,
                expires_at=expires_at,
            )
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
            return entry

    async def health_check(self) -> dict[str, str]:
        """
        Check database health.

        Returns:
            Dictionary with status and message
        """
        try:
            async with self.session_factory() as session:
                # Execute a simple query to check connectivity
                await session.execute(text("SELECT 1"))
            return {"status": "healthy", "database": "connected"}
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {"status": "unhealthy", "database": str(e)}


# Global database engine instance
db_engine = DatabaseEngine()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get an async database session.

    This is a FastAPI dependency that provides a session per request.
    The session is automatically closed after the request completes.

    Yields:
        AsyncSession: An async database session
    """
    async with db_engine.session_factory() as session:
        yield session


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get an async database session as a context manager.

    This is useful for non-request code that needs database access.

    Yields:
        AsyncSession: An async database session
    """
    async with db_engine.session_factory() as session:
        yield session


class DatabaseLifecycle:
    """
    Database lifecycle manager for FastAPI applications.

    Handles startup and shutdown events for database initialization
    and cleanup.
    """

    def __init__(self, engine: DatabaseEngine | None = None, cleanup_interval_hours: int = 1):
        """
        Initialize the lifecycle manager.

        Args:
            engine: Database engine to manage (uses global instance if None)
            cleanup_interval_hours: Interval for background cleanup task in hours
        """
        self._engine = engine or db_engine
        self._cleanup_interval_hours = cleanup_interval_hours
        self._cleanup_task = None
        self._shutdown_event = None

    async def startup(self) -> None:
        """Initialize database on application startup."""
        logger.info("Initializing database...")
        await self._engine.init_db()
        logger.info("Database initialized successfully")
        # Start background cleanup task
        await self.start_background_cleanup()

    async def shutdown(self) -> None:
        """Cleanup database on application shutdown."""
        logger.info("Shutting down database...")
        # Stop background cleanup task first
        await self.stop_background_cleanup()
        await self._engine.close()
        logger.info("Database shutdown complete")

    async def start_background_cleanup(self) -> None:
        """Start the background cleanup task for expired cache entries."""
        from app.config import settings

        self._shutdown_event = asyncio.Event()
        # Use configurable poll interval from settings
        poll_interval = settings.cache_poll_interval

        async def cleanup_loop():
            """Background task that periodically cleans up expired entries."""
            logger.info("Started background cache cleanup task")
            cancelled = False
            try:
                while not self._shutdown_event.is_set():
                    try:
                        await self._engine.cleanup_expired()
                    except Exception as e:
                        logger.error(f"Error during cache cleanup: {e}")

                    # Wait for next poll interval or until shutdown
                    # Using shorter poll interval for responsive shutdown
                    try:
                        await asyncio.wait_for(
                            self._shutdown_event.wait(),
                            timeout=poll_interval
                        )
                        break  # Shutdown was signaled
                    except asyncio.TimeoutError:
                        continue  # Continue to next cleanup cycle
            except asyncio.CancelledError:
                cancelled = True
                logger.debug("Background cache cleanup task cancelled")
                raise
            except Exception as e:
                logger.error(f"Background cleanup task error: {e}")
            finally:
                if cancelled:
                    logger.debug("Background cache cleanup task stopped (cancelled)")
                else:
                    logger.info("Background cache cleanup task stopped")

        try:
            self._cleanup_task = asyncio.create_task(cleanup_loop())
            logger.info(f"Background cleanup task started (poll interval: {poll_interval}s, cleanup every {self._cleanup_interval_hours}h)")
        except Exception as e:
            logger.error(f"Failed to start background cleanup task: {e}")
            raise

    async def stop_background_cleanup(self) -> None:
        """Stop the background cleanup task."""
        if self._cleanup_task is not None:
            logger.info("Stopping background cache cleanup task...")
            if self._shutdown_event is not None:
                self._shutdown_event.set()
            try:
                await asyncio.wait_for(self._cleanup_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._cleanup_task.cancel()
                logger.warning("Background cleanup task did not stop in time, cancelled")
            self._cleanup_task = None
            self._shutdown_event = None
            logger.info("Background cache cleanup task stopped")


# Global lifecycle instance
db_lifecycle = DatabaseLifecycle()
