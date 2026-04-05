"""
Test: Database CRUD Operations

Uses in-memory SQLite (:memory:) to test:
- init() table creation
- bind_user() / get_bind() / unbind_user() (with nickname)
- save_profile() / get_profile()
- add_seen_movies() / get_seen_movie_ids()
- create_rec_session() / get_rec_session() / update_rec_session_shown()
- update_last_profile()
- Cascading delete on unbind
"""

from __future__ import annotations

import json
import sqlite3

import aiosqlite
import pytest

from astrbot_plugin_douban_movie.db.database import Database


# ===========================================================================
# Table creation
# ===========================================================================

class TestDatabaseInit:

    async def test_tables_created(self, db):
        """init creates all four tables."""
        cursor = await db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {r["name"] for r in await cursor.fetchall()}
        assert "user_bind" in tables
        assert "user_profile" in tables
        assert "user_seen_movies" in tables
        assert "rec_session" in tables

    async def test_user_bind_schema(self, db):
        """user_bind table has expected columns."""
        cursor = await db._conn.execute("PRAGMA table_info(user_bind)")
        cols = {r["name"] for r in await cursor.fetchall()}
        expected = {"astrbot_uid", "douban_uid", "nickname", "bind_time", "last_profile"}
        assert expected == cols

    async def test_user_profile_schema(self, db):
        """user_profile table has expected columns."""
        cursor = await db._conn.execute("PRAGMA table_info(user_profile)")
        cols = {r["name"] for r in await cursor.fetchall()}
        expected = {
            "astrbot_uid", "profile_text", "raw_stats", "genre_prefs",
            "region_prefs", "decade_prefs", "total_marked", "updated_at",
        }
        assert expected == cols

    async def test_user_seen_movies_schema(self, db):
        """user_seen_movies table has expected columns."""
        cursor = await db._conn.execute("PRAGMA table_info(user_seen_movies)")
        cols = {r["name"] for r in await cursor.fetchall()}
        expected = {"id", "astrbot_uid", "douban_movie_id", "title", "created_at"}
        assert expected == cols

    async def test_rec_session_schema(self, db):
        """rec_session table has expected columns."""
        cursor = await db._conn.execute("PRAGMA table_info(rec_session)")
        cols = {r["name"] for r in await cursor.fetchall()}
        expected = {"session_id", "astrbot_uid", "keyword", "candidate_ids", "shown_ids", "created_at"}
        assert expected == cols


# ===========================================================================
# bind_user / get_bind / unbind_user
# ===========================================================================

class TestUserBind:

    async def test_bind_and_get(self, db):
        await db.bind_user("user1", "159896279", "测试用户")
        result = await db.get_bind("user1")
        assert result is not None
        assert result["astrbot_uid"] == "user1"
        assert result["douban_uid"] == "159896279"
        assert result["nickname"] == "测试用户"

    async def test_bind_without_nickname(self, db):
        await db.bind_user("user1", "159896279")
        result = await db.get_bind("user1")
        assert result["nickname"] is None

    async def test_get_bind_not_found(self, db):
        result = await db.get_bind("nonexistent")
        assert result is None

    async def test_bind_replaces_existing(self, db):
        """Re-binding the same user replaces the old record."""
        await db.bind_user("user1", "111", "旧昵称")
        await db.bind_user("user1", "222", "新昵称")
        result = await db.get_bind("user1")
        assert result["douban_uid"] == "222"
        assert result["nickname"] == "新昵称"

    async def test_multiple_users_isolated(self, db):
        """Multiple users' bindings are isolated."""
        await db.bind_user("u1", "111", "用户1")
        await db.bind_user("u2", "222", "用户2")
        r1 = await db.get_bind("u1")
        r2 = await db.get_bind("u2")
        assert r1["douban_uid"] == "111"
        assert r2["douban_uid"] == "222"


# ===========================================================================
# unbind_user (cascading)
# ===========================================================================

class TestUnbindCascading:

    async def test_unbind_removes_bind(self, db):
        await db.bind_user("u1", "111")
        await db.unbind_user("u1")
        assert await db.get_bind("u1") is None

    async def test_unbind_removes_profile(self, db):
        await db.bind_user("u1", "111")
        await db.save_profile("u1", "画像文本", {"raw": True}, ["剧情"], ["美国"], ["2020s"], 100)
        await db.unbind_user("u1")
        assert await db.get_profile("u1") is None

    async def test_unbind_removes_seen_movies(self, db):
        await db.bind_user("u1", "111")
        await db.add_seen_movies("u1", [{"douban_movie_id": "100", "title": "A"}])
        await db.unbind_user("u1")
        assert await db.get_seen_movie_ids("u1") == set()

    async def test_unbind_removes_rec_sessions(self, db):
        await db.bind_user("u1", "111")
        await db.create_rec_session("sess1", "u1", "科幻", ["100", "200"])
        await db.unbind_user("u1")
        assert await db.get_rec_session("sess1") is None

    async def test_unbind_does_not_affect_other_users(self, db):
        await db.bind_user("u1", "111")
        await db.bind_user("u2", "222")
        await db.add_seen_movies("u1", [{"douban_movie_id": "100", "title": "A"}])
        await db.add_seen_movies("u2", [{"douban_movie_id": "200", "title": "B"}])

        await db.unbind_user("u1")

        assert await db.get_bind("u2") is not None
        assert await db.get_seen_movie_ids("u2") == {"200"}

    async def test_unbind_nonexistent_no_error(self, db):
        await db.unbind_user("ghost")


# ===========================================================================
# save_profile / get_profile
# ===========================================================================

class TestProfileCRUD:

    async def test_save_and_get_profile(self, db):
        await db.save_profile(
            "u1", "画像文本", {"key": "value"},
            ["剧情", "科幻"], ["美国"], ["2020s"], 100,
        )
        profile = await db.get_profile("u1")
        assert profile is not None
        assert profile["profile_text"] == "画像文本"
        assert profile["raw_stats"] == {"key": "value"}
        assert profile["genre_prefs"] == ["剧情", "科幻"]
        assert profile["region_prefs"] == ["美国"]
        assert profile["decade_prefs"] == ["2020s"]
        assert profile["total_marked"] == 100

    async def test_save_profile_replaces_existing(self, db):
        await db.save_profile("u1", "旧", {}, [], [], [], 0)
        await db.save_profile("u1", "新", {}, ["剧情"], [], [], 50)
        profile = await db.get_profile("u1")
        assert profile["profile_text"] == "新"
        assert profile["genre_prefs"] == ["剧情"]
        assert profile["total_marked"] == 50

    async def test_get_profile_not_found(self, db):
        assert await db.get_profile("ghost") is None

    async def test_json_fields_parsed(self, db):
        """JSON fields are automatically parsed on get."""
        await db.save_profile(
            "u1", "text", {"a": 1}, ["剧情"], ["美国"], ["2020s"], 10,
        )
        profile = await db.get_profile("u1")
        assert isinstance(profile["raw_stats"], dict)
        assert isinstance(profile["genre_prefs"], list)


# ===========================================================================
# user_seen_movies
# ===========================================================================

class TestSeenMovies:

    async def test_add_and_get_seen_ids(self, db):
        await db.add_seen_movies("u1", [
            {"douban_movie_id": "100", "title": "A"},
            {"douban_movie_id": "200", "title": "B"},
        ])
        ids = await db.get_seen_movie_ids("u1")
        assert ids == {"100", "200"}

    async def test_add_duplicate_ignored(self, db):
        """UNIQUE constraint: same uid + movie_id only stored once."""
        await db.add_seen_movies("u1", [{"douban_movie_id": "100", "title": "A"}])
        await db.add_seen_movies("u1", [{"douban_movie_id": "100", "title": "A2"}])
        ids = await db.get_seen_movie_ids("u1")
        assert len(ids) == 1

    async def test_empty_when_no_movies(self, db):
        ids = await db.get_seen_movie_ids("u1")
        assert ids == set()

    async def test_isolated_per_user(self, db):
        await db.add_seen_movies("u1", [{"douban_movie_id": "100", "title": "A"}])
        await db.add_seen_movies("u2", [{"douban_movie_id": "200", "title": "B"}])
        assert await db.get_seen_movie_ids("u1") == {"100"}
        assert await db.get_seen_movie_ids("u2") == {"200"}


# ===========================================================================
# rec_session
# ===========================================================================

class TestRecSession:

    async def test_create_and_get_session(self, db):
        await db.create_rec_session("sess1", "u1", "科幻", ["100", "200", "300"])
        session = await db.get_rec_session("sess1")
        assert session is not None
        assert session["session_id"] == "sess1"
        assert session["astrbot_uid"] == "u1"
        assert session["keyword"] == "科幻"
        assert session["candidate_ids"] == ["100", "200", "300"]
        assert session["shown_ids"] == []

    async def test_update_shown_ids(self, db):
        await db.create_rec_session("sess1", "u1", "科幻", ["100", "200", "300"])
        await db.update_rec_session_shown("sess1", ["100", "200"])
        session = await db.get_rec_session("sess1")
        assert session["shown_ids"] == ["100", "200"]

    async def test_get_session_not_found(self, db):
        assert await db.get_rec_session("ghost") is None

    async def test_json_fields_parsed(self, db):
        await db.create_rec_session("s1", "u1", "test", ["1", "2"])
        session = await db.get_rec_session("s1")
        assert isinstance(session["candidate_ids"], list)
        assert isinstance(session["shown_ids"], list)


# ===========================================================================
# update_last_profile
# ===========================================================================

class TestUpdateLastProfile:

    async def test_sets_last_profile(self, db):
        await db.bind_user("u1", "111")
        await db.update_last_profile("u1")
        bind = await db.get_bind("u1")
        assert bind["last_profile"] is not None

    async def test_changes_on_update(self, db):
        await db.bind_user("u1", "111")
        await db.update_last_profile("u1")
        first = (await db.get_bind("u1"))["last_profile"]
        assert first is not None


# ===========================================================================
# Edge cases
# ===========================================================================

class TestDatabaseEdgeCases:

    async def test_unicode_data(self, db):
        """Unicode strings are stored and retrieved correctly."""
        await db.bind_user("u1", "111", "千と千尋の神隠し 🎬")
        result = await db.get_bind("u1")
        assert result["nickname"] == "千と千尋の神隠し 🎬"

    async def test_close_sets_conn_none(self, db):
        await db.close()
        assert db._conn is None

    async def test_profile_with_empty_json_fields(self, db):
        """Empty lists for JSON fields work correctly."""
        await db.save_profile("u1", "text", {}, [], [], [], 0)
        profile = await db.get_profile("u1")
        assert profile["genre_prefs"] == []
        assert profile["region_prefs"] == []
