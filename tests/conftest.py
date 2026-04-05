"""
Shared test fixtures and mock setup for the Douban Movie plugin test suite.

This module:
1. Mocks astrbot.api so plugin modules can be imported without the real framework.
2. Adds the plugin's parent directory to sys.path so the plugin can be imported
   as a package (simulating AstrBot's plugin loading).
3. Provides reusable pytest fixtures for Database, DoubanClient, ProfileGenerator,
   and Recommender with in-memory SQLite and mocked network calls.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path setup: make the plugin importable as a package
# ---------------------------------------------------------------------------
PLUGIN_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PLUGIN_DIR.parent.parent.parent  # E:\AstrBot

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# The plugin's parent dir so `import astrbot_plugin_douban_movie` works
if str(PLUGIN_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR.parent))

# ---------------------------------------------------------------------------
# Mock astrbot.api before importing any plugin code
# ---------------------------------------------------------------------------
_mock_api = MagicMock()
_mock_api.logger = MagicMock()
_mock_api.AstrBotConfig = dict

_mock_event = MagicMock()
_mock_event.filter = MagicMock()

_mock_star = MagicMock()
_mock_star.Context = MagicMock
_mock_star.Star = type("Star", (), {"__init__": lambda self, ctx: None})
_mock_star.StarTools = MagicMock()

sys.modules.setdefault("astrbot", MagicMock())
sys.modules.setdefault("astrbot.api", _mock_api)
sys.modules.setdefault("astrbot.api.event", _mock_event)
sys.modules.setdefault("astrbot.api.star", _mock_star)

# ---------------------------------------------------------------------------
# Now import the plugin modules safely
# ---------------------------------------------------------------------------
import aiosqlite
import sqlite3

from astrbot_plugin_douban_movie.db.database import Database
from astrbot_plugin_douban_movie.service.douban_client import DoubanClient
from astrbot_plugin_douban_movie.service.profile import ProfileGenerator
from astrbot_plugin_douban_movie.service.recommender import Recommender


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def event_loop():
    """Provide a fresh event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db():
    """Provide an in-memory Database with tables created."""
    database = Database(":memory:")
    # Bypass init() mkdir logic for in-memory DB
    database._conn = await aiosqlite.connect(":memory:")
    database._conn.row_factory = sqlite3.Row
    await database._create_tables()
    yield database
    await database.close()


@pytest.fixture
def mock_client():
    """Provide a DoubanClient with all network methods mocked."""
    client = DoubanClient(interval_min=0.0, interval_max=0.0, max_retries=1)
    client._request = AsyncMock(return_value=None)
    client._delay = AsyncMock()
    return client


@pytest.fixture
def plugin_dir():
    """Return the plugin root directory as a Path."""
    return PLUGIN_DIR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_top250_movie(
    movie_id: str = "1000000",
    title: str = "Test Movie",
    year: int = 2020,
    avg_rating: float = 9.0,
    genres: str = "剧情",
    regions: str = "美国",
    quote: str = "",
) -> dict:
    """Helper to build a Top250-style movie dict."""
    return {
        "douban_movie_id": movie_id,
        "title": title,
        "year": year,
        "avg_rating": avg_rating,
        "genres": genres,
        "regions": regions,
        "quote": quote,
    }


def make_collection_movie(
    movie_id: str = "1000000",
    title: str = "Test Movie",
    status: str = "collect",
    user_rating: float | None = 4.0,
    genres: str = "",
    regions: str = "",
    year: int | None = 2020,
    marked_at: str | None = "2024-06-01",
) -> dict:
    """Helper to build a user-collection-style movie dict."""
    return {
        "douban_movie_id": movie_id,
        "title": title,
        "status": status,
        "user_rating": user_rating,
        "genres": genres,
        "regions": regions,
        "year": year,
        "marked_at": marked_at,
    }
