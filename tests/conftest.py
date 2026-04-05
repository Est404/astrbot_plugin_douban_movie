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

_mock_util = MagicMock()

sys.modules.setdefault("astrbot", MagicMock())
sys.modules.setdefault("astrbot.api", _mock_api)
sys.modules.setdefault("astrbot.api.event", _mock_event)
sys.modules.setdefault("astrbot.api.star", _mock_star)
sys.modules.setdefault("astrbot.api.util", _mock_util)

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
    client._delay = AsyncMock()
    return client


@pytest.fixture
def plugin_dir():
    """Return the plugin root directory as a Path."""
    return PLUGIN_DIR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_search_result(
    movie_id: str = "1000000",
    title: str = "Test Movie",
    rating: float = 8.5,
    year: int = 2020,
    card_subtitle: str = "2020 / 美国 / 科幻",
) -> dict:
    """Helper to build a search-result-style movie dict."""
    return {
        "id": movie_id,
        "title": title,
        "rating": rating,
        "year": year,
        "card_subtitle": card_subtitle,
    }


def make_collection_stats(
    nickname: str = "测试用户",
    total_marked: int = 100,
    genres: list[dict] | None = None,
    recent_subjects: list[dict] | None = None,
) -> dict:
    """Helper to build a collection_stats API response."""
    if genres is None:
        genres = [{"name": "剧情"}, {"name": "科幻"}]
    if recent_subjects is None:
        recent_subjects = [
            {
                "title": "测试电影",
                "id": "12345",
                "year": 2024,
                "rating": {"value": 8.5},
                "genres": genres,
                "card_subtitle": "2024 / 美国 / 剧情 / 科幻",
            }
        ]
    return {
        "viewer": {"name": nickname},
        "years": [{"name": "2024", "value": total_marked}],
        "recent_subjects": recent_subjects,
    }
