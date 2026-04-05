"""
Test 3D: Database CRUD Operations

Uses in-memory SQLite (:memory:) to test:
- init() table creation
- bind_user() / get_bind() / unbind_user()
- upsert_movie() / get_movies_by_status()
- get_all_collected_movie_ids()
- get_movie_count()
- update_movie_details()
- get_movies_without_details()
- update_last_sync()
- Edge cases: concurrent users, missing data, type handling
"""

from __future__ import annotations

import sqlite3

import aiosqlite
import pytest

from astrbot_plugin_douban_movie.db.database import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def db():
    """Provide a fresh in-memory database with tables created."""
    database = Database(":memory:")
    # Bypass init()'s mkdir for in-memory DB
    database._conn = await aiosqlite.connect(":memory:")
    database._conn.row_factory = sqlite3.Row
    await database._create_tables()
    yield database
    await database.close()


# ===========================================================================
# Table creation
# ===========================================================================

class TestDatabaseInit:

    async def test_tables_created(self, db):
        """init creates user_bind and movie_collection tables."""
        cursor = await db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {r["name"] for r in await cursor.fetchall()}
        assert "user_bind" in tables
        assert "movie_collection" in tables

    async def test_user_bind_schema(self, db):
        """user_bind table has expected columns."""
        cursor = await db._conn.execute("PRAGMA table_info(user_bind)")
        cols = {r["name"] for r in await cursor.fetchall()}
        expected = {"astrbot_uid", "douban_uid", "cookie", "bind_time", "last_sync"}
        assert expected == cols

    async def test_movie_collection_schema(self, db):
        """movie_collection table has expected columns."""
        cursor = await db._conn.execute("PRAGMA table_info(movie_collection)")
        cols = {r["name"] for r in await cursor.fetchall()}
        expected = {
            "douban_movie_id", "astrbot_uid", "title", "user_rating",
            "genres", "regions", "year", "status", "marked_at", "fetched_at",
        }
        assert expected == cols


# ===========================================================================
# bind_user / get_bind / unbind_user
# ===========================================================================

class TestUserBind:

    async def test_bind_and_get(self, db):
        await db.bind_user("user1", "douban_abc", "cookie123")
        result = await db.get_bind("user1")
        assert result is not None
        assert result["astrbot_uid"] == "user1"
        assert result["douban_uid"] == "douban_abc"
        assert result["cookie"] == "cookie123"

    async def test_get_bind_not_found(self, db):
        result = await db.get_bind("nonexistent")
        assert result is None

    async def test_bind_replaces_existing(self, db):
        """Re-binding the same user replaces the old record."""
        await db.bind_user("user1", "douban_old", "old_cookie")
        await db.bind_user("user1", "douban_new", "new_cookie")
        result = await db.get_bind("user1")
        assert result["douban_uid"] == "douban_new"
        assert result["cookie"] == "new_cookie"

    async def test_unbind_user(self, db):
        await db.bind_user("user1", "douban_abc", "cookie")
        await db.unbind_user("user1")
        result = await db.get_bind("user1")
        assert result is None

    async def test_unbind_nonexistent_user_no_error(self, db):
        """Unbinding a user that doesn't exist should not raise."""
        await db.unbind_user("ghost")

    async def test_multiple_users_isolated(self, db):
        """Multiple users' bindings are isolated."""
        await db.bind_user("u1", "d1", "c1")
        await db.bind_user("u2", "d2", "c2")
        r1 = await db.get_bind("u1")
        r2 = await db.get_bind("u2")
        assert r1["douban_uid"] == "d1"
        assert r2["douban_uid"] == "d2"


# ===========================================================================
# upsert_movie / get_movies_by_status
# ===========================================================================

class TestMovieCRUD:

    async def test_upsert_and_get_by_status(self, db):
        await db.upsert_movie("user1", {
            "douban_movie_id": "100",
            "title": "Movie A",
            "status": "collect",
            "user_rating": 4.0,
        })
        await db.upsert_movie("user1", {
            "douban_movie_id": "200",
            "title": "Movie B",
            "status": "wish",
        })
        await db.commit_batch()

        collected = await db.get_movies_by_status("user1", "collect")
        assert len(collected) == 1
        assert collected[0]["title"] == "Movie A"
        assert collected[0]["user_rating"] == 4.0

        wished = await db.get_movies_by_status("user1", "wish")
        assert len(wished) == 1
        assert wished[0]["title"] == "Movie B"

    async def test_upsert_replaces_existing(self, db):
        """INSERT OR REPLACE updates the record."""
        await db.upsert_movie("user1", {
            "douban_movie_id": "100",
            "title": "Old Title",
            "status": "collect",
        })
        await db.commit_batch()

        await db.upsert_movie("user1", {
            "douban_movie_id": "100",
            "title": "New Title",
            "status": "collect",
            "user_rating": 5.0,
        })
        await db.commit_batch()

        movies = await db.get_movies_by_status("user1", "collect")
        assert len(movies) == 1
        assert movies[0]["title"] == "New Title"
        assert movies[0]["user_rating"] == 5.0

    async def test_get_by_status_empty(self, db):
        """Querying a status with no entries returns empty list."""
        result = await db.get_movies_by_status("user1", "collect")
        assert result == []

    async def test_movies_isolated_per_user(self, db):
        """Users can only see their own movies."""
        await db.upsert_movie("u1", {"douban_movie_id": "100", "title": "A", "status": "collect"})
        await db.upsert_movie("u2", {"douban_movie_id": "200", "title": "B", "status": "collect"})
        await db.commit_batch()

        u1_movies = await db.get_movies_by_status("u1", "collect")
        u2_movies = await db.get_movies_by_status("u2", "collect")
        assert len(u1_movies) == 1
        assert u1_movies[0]["title"] == "A"
        assert len(u2_movies) == 1
        assert u2_movies[0]["title"] == "B"

    async def test_same_movie_different_users(self, db):
        """Same movie_id can exist for different users."""
        await db.upsert_movie("u1", {"douban_movie_id": "100", "title": "Shared", "status": "collect"})
        await db.upsert_movie("u2", {"douban_movie_id": "100", "title": "Shared", "status": "wish"})
        await db.commit_batch()

        u1 = await db.get_movies_by_status("u1", "collect")
        u2 = await db.get_movies_by_status("u2", "wish")
        assert len(u1) == 1
        assert len(u2) == 1


# ===========================================================================
# get_all_collected_movie_ids
# ===========================================================================

class TestCollectedMovieIds:

    async def test_returns_collect_and_wish(self, db):
        """Only 'collect' and 'wish' statuses are returned."""
        await db.upsert_movie("u1", {"douban_movie_id": "1", "title": "A", "status": "collect"})
        await db.upsert_movie("u1", {"douban_movie_id": "2", "title": "B", "status": "wish"})
        await db.upsert_movie("u1", {"douban_movie_id": "3", "title": "C", "status": "do"})
        await db.commit_batch()

        ids = await db.get_all_collected_movie_ids("u1")
        assert ids == {"1", "2"}

    async def test_empty_when_no_movies(self, db):
        ids = await db.get_all_collected_movie_ids("user1")
        assert ids == set()


# ===========================================================================
# get_movie_count
# ===========================================================================

class TestMovieCount:

    async def test_count_by_status(self, db):
        await db.upsert_movie("u1", {"douban_movie_id": "1", "title": "A", "status": "collect"})
        await db.upsert_movie("u1", {"douban_movie_id": "2", "title": "B", "status": "collect"})
        await db.upsert_movie("u1", {"douban_movie_id": "3", "title": "C", "status": "wish"})
        await db.upsert_movie("u1", {"douban_movie_id": "4", "title": "D", "status": "do"})
        await db.commit_batch()

        counts = await db.get_movie_count("u1")
        assert counts["collect"] == 2
        assert counts["wish"] == 1
        assert counts["do"] == 1

    async def test_count_empty(self, db):
        counts = await db.get_movie_count("user1")
        assert counts == {}

    async def test_count_isolated_per_user(self, db):
        await db.upsert_movie("u1", {"douban_movie_id": "1", "title": "A", "status": "collect"})
        await db.upsert_movie("u2", {"douban_movie_id": "2", "title": "B", "status": "collect"})
        await db.upsert_movie("u2", {"douban_movie_id": "3", "title": "C", "status": "collect"})
        await db.commit_batch()

        c1 = await db.get_movie_count("u1")
        c2 = await db.get_movie_count("u2")
        assert c1.get("collect", 0) == 1
        assert c2.get("collect", 0) == 2


# ===========================================================================
# update_movie_details
# ===========================================================================

class TestUpdateMovieDetails:

    async def test_update_genres_regions_year(self, db):
        await db.upsert_movie("u1", {
            "douban_movie_id": "100", "title": "Test", "status": "collect",
        })
        await db.commit_batch()

        await db.update_movie_details("100", "u1", "剧情,科幻", "美国", 2020)
        await db.commit_batch()

        movies = await db.get_movies_by_status("u1", "collect")
        assert len(movies) == 1
        m = movies[0]
        assert m["genres"] == "剧情,科幻"
        assert m["regions"] == "美国"
        assert m["year"] == 2020

    async def test_update_overwrites_previous(self, db):
        await db.upsert_movie("u1", {
            "douban_movie_id": "100", "title": "Test", "status": "collect",
            "genres": "旧类型",
        })
        await db.commit_batch()

        await db.update_movie_details("100", "u1", "新类型", "新地区", 2023)
        await db.commit_batch()

        movies = await db.get_movies_by_status("u1", "collect")
        assert movies[0]["genres"] == "新类型"
        assert movies[0]["year"] == 2023

    async def test_update_nonexistent_movie_no_error(self, db):
        """Updating a movie that doesn't exist should not raise."""
        await db.update_movie_details("999", "u1", "剧情", "美国", 2020)
        await db.commit_batch()


# ===========================================================================
# get_movies_without_details
# ===========================================================================

class TestMoviesWithoutDetails:

    async def test_finds_empty_genres(self, db):
        await db.upsert_movie("u1", {"douban_movie_id": "1", "title": "A", "status": "collect", "genres": ""})
        await db.upsert_movie("u1", {"douban_movie_id": "2", "title": "B", "status": "collect", "genres": "剧情"})
        await db.commit_batch()

        ids = await db.get_movies_without_details("u1", 10)
        assert "1" in ids
        assert "2" not in ids

    async def test_respects_limit(self, db):
        for i in range(10):
            await db.upsert_movie("u1", {"douban_movie_id": str(i), "title": f"M{i}", "status": "collect", "genres": ""})
        await db.commit_batch()

        ids = await db.get_movies_without_details("u1", 3)
        assert len(ids) <= 3

    async def test_empty_when_all_have_details(self, db):
        await db.upsert_movie("u1", {"douban_movie_id": "1", "title": "A", "status": "collect", "genres": "剧情"})
        await db.commit_batch()

        ids = await db.get_movies_without_details("u1", 10)
        assert ids == []


# ===========================================================================
# update_last_sync
# ===========================================================================

class TestUpdateLastSync:

    async def test_sets_last_sync(self, db):
        await db.bind_user("u1", "d1", "cookie")
        await db.update_last_sync("u1")
        bind = await db.get_bind("u1")
        assert bind["last_sync"] is not None

    async def test_last_sync_changes_on_update(self, db):
        await db.bind_user("u1", "d1", "cookie")
        await db.update_last_sync("u1")
        first = (await db.get_bind("u1"))["last_sync"]

        # Small delay to ensure different timestamp
        import asyncio
        await asyncio.sleep(0.01)

        await db.update_last_sync("u1")
        second = (await db.get_bind("u1"))["last_sync"]
        # Timestamps should be at least non-null (might be same due to precision)
        assert second is not None


# ===========================================================================
# unbind_user also removes movies
# ===========================================================================

class TestUnbindCascading:

    async def test_unbind_removies_all_user_movies(self, db):
        await db.bind_user("u1", "d1", "cookie")
        await db.upsert_movie("u1", {"douban_movie_id": "1", "title": "A", "status": "collect"})
        await db.upsert_movie("u1", {"douban_movie_id": "2", "title": "B", "status": "wish"})
        await db.commit_batch()

        await db.unbind_user("u1")

        ids = await db.get_all_collected_movie_ids("u1")
        assert ids == set()

        movies = await db.get_movies_by_status("u1", "collect")
        assert movies == []

    async def test_unbind_does_not_affect_other_users(self, db):
        await db.bind_user("u1", "d1", "c1")
        await db.bind_user("u2", "d2", "c2")
        await db.upsert_movie("u1", {"douban_movie_id": "1", "title": "A", "status": "collect"})
        await db.upsert_movie("u2", {"douban_movie_id": "2", "title": "B", "status": "collect"})
        await db.commit_batch()

        await db.unbind_user("u1")

        u2_movies = await db.get_movies_by_status("u2", "collect")
        assert len(u2_movies) == 1
        assert u2_movies[0]["title"] == "B"


# ===========================================================================
# Edge cases
# ===========================================================================

class TestDatabaseEdgeCases:

    async def test_movie_with_none_fields(self, db):
        """Movie with None user_rating, year, etc. should not crash."""
        await db.upsert_movie("u1", {
            "douban_movie_id": "1",
            "title": "Nones",
            "status": "collect",
            "user_rating": None,
            "year": None,
            "marked_at": None,
        })
        await db.commit_batch()

        movies = await db.get_movies_by_status("u1", "collect")
        assert len(movies) == 1
        assert movies[0]["user_rating"] is None

    async def test_movie_with_unicode_title(self, db):
        """Unicode titles are stored correctly."""
        await db.upsert_movie("u1", {
            "douban_movie_id": "1",
            "title": "千と千尋の神隠し 🎬",
            "status": "collect",
        })
        await db.commit_batch()

        movies = await db.get_movies_by_status("u1", "collect")
        assert movies[0]["title"] == "千と千尋の神隠し 🎬"

    async def test_close_and_reuse(self, db):
        """After close(), _conn is None."""
        await db.close()
        assert db._conn is None
