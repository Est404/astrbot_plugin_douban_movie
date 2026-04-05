"""
Test: ProfileGenerator Logic (API-based)

Tests:
- _extract_prefs_from_stats: parsing collection_stats API response
- _format_profile_from_stats: pure text fallback formatting
- _build_llm_prompt: prompt construction
- generate: full flow with caching, API calls, LLM integration
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_douban_movie.service.profile import ProfileGenerator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_stats(
    nickname: str = "测试用户",
    total_marked: int = 100,
    recent_subjects: list[dict] | None = None,
) -> dict:
    """Build a collection_stats API response."""
    if recent_subjects is None:
        recent_subjects = [
            {
                "title": "电影A",
                "id": "100",
                "year": 2024,
                "rating": {"value": 8.5},
                "genres": [{"name": "剧情"}, {"name": "科幻"}],
                "card_subtitle": "2024 / 美国 / 剧情 / 科幻",
            },
            {
                "title": "电影B",
                "id": "200",
                "year": 2020,
                "rating": {"value": 7.0},
                "genres": [{"name": "喜剧"}],
                "card_subtitle": "2020 / 日本 / 喜剧",
            },
        ]
    return {
        "viewer": {"name": nickname},
        "years": [{"name": "2024", "value": total_marked}],
        "recent_subjects": recent_subjects,
    }


# ===========================================================================
# _extract_prefs_from_stats
# ===========================================================================

class TestExtractPrefs:

    def test_genre_prefs(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        stats = make_stats()
        prefs = gen._extract_prefs_from_stats(stats)
        genre_names = [g for g, _ in prefs["genre_prefs"]]
        assert "剧情" in genre_names
        assert "科幻" in genre_names

    def test_region_prefs(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        stats = make_stats()
        prefs = gen._extract_prefs_from_stats(stats)
        region_names = [r for r, _ in prefs["region_prefs"]]
        assert "美国" in region_names

    def test_decade_prefs(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        stats = make_stats()
        prefs = gen._extract_prefs_from_stats(stats)
        decade_names = [d for d, _ in prefs["decade_prefs"]]
        assert "2020s" in decade_names

    def test_total_marked(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        stats = make_stats(total_marked=500)
        prefs = gen._extract_prefs_from_stats(stats)
        assert prefs["total_marked"] == 500

    def test_empty_recent_subjects(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        stats = make_stats(recent_subjects=[])
        prefs = gen._extract_prefs_from_stats(stats)
        assert prefs["genre_prefs"] == []
        assert prefs["region_prefs"] == []
        assert prefs["total_marked"] == 100

    def test_genre_limited_to_top5(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        subjects = [
            {
                "title": f"M{i}",
                "id": str(i),
                "year": 2020,
                "genres": [{"name": f"类型{i}"}],
                "card_subtitle": "2020 / 美国",
            }
            for i in range(10)
        ]
        stats = make_stats(recent_subjects=subjects)
        prefs = gen._extract_prefs_from_stats(stats)
        assert len(prefs["genre_prefs"]) <= 5

    def test_region_limited_to_top3(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        subjects = [
            {
                "title": f"M{i}",
                "id": str(i),
                "year": 2020,
                "genres": [],
                "card_subtitle": f"2020 / 地区{i}",
            }
            for i in range(10)
        ]
        stats = make_stats(recent_subjects=subjects)
        prefs = gen._extract_prefs_from_stats(stats)
        assert len(prefs["region_prefs"]) <= 3


# ===========================================================================
# _format_profile_from_stats
# ===========================================================================

class TestFormatProfile:

    def test_contains_nickname(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = {
            "total_marked": 100,
            "genre_prefs": [("剧情", 50)],
            "region_prefs": [("美国", 30)],
            "decade_prefs": [("2020s", 40)],
        }
        text = gen._format_profile_from_stats(prefs, nickname="Est")
        assert "Est" in text

    def test_contains_total_marked(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = {"total_marked": 917, "genre_prefs": [], "region_prefs": [], "decade_prefs": []}
        text = gen._format_profile_from_stats(prefs)
        assert "917" in text

    def test_genre_prefs_displayed(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = {
            "total_marked": 100,
            "genre_prefs": [("剧情", 50), ("科幻", 30)],
            "region_prefs": [],
            "decade_prefs": [],
        }
        text = gen._format_profile_from_stats(prefs)
        assert "剧情" in text
        assert "科幻" in text

    def test_empty_prefs_no_crash(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = {"total_marked": 0, "genre_prefs": [], "region_prefs": [], "decade_prefs": []}
        text = gen._format_profile_from_stats(prefs)
        assert "0" in text


# ===========================================================================
# _build_llm_prompt
# ===========================================================================

class TestBuildLLMPrompt:

    def test_contains_system_instruction(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = {"total_marked": 50, "genre_prefs": [], "region_prefs": [], "decade_prefs": []}
        prompt = gen._build_llm_prompt(prefs, "测试用户")
        assert "观影统计" in prompt

    def test_contains_nickname(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = {"total_marked": 50, "genre_prefs": [], "region_prefs": [], "decade_prefs": []}
        prompt = gen._build_llm_prompt(prefs, "Est")
        assert "Est" in prompt

    def test_contains_genre_info(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = {
            "total_marked": 100,
            "genre_prefs": [("剧情", 50)],
            "region_prefs": [],
            "decade_prefs": [],
        }
        prompt = gen._build_llm_prompt(prefs)
        assert "剧情" in prompt

    def test_word_limit(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = {"total_marked": 50, "genre_prefs": [], "region_prefs": [], "decade_prefs": []}
        prompt = gen._build_llm_prompt(prefs)
        assert "200字" in prompt


# ===========================================================================
# generate (full flow)
# ===========================================================================

class TestGenerate:

    async def test_no_bind_returns_error(self, db, mock_client):
        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("nonexistent")
        assert "绑定" in text

    async def test_api_failure_returns_error(self, db, mock_client):
        await db.bind_user("u1", "111", "测试")
        mock_client.fetch_collection_stats = AsyncMock(return_value=None)
        mock_client.cookie_expired = False

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1")
        assert "获取观影数据失败" in text

    async def test_cookie_expired_returns_error(self, db, mock_client):
        await db.bind_user("u1", "111", "测试")
        mock_client.fetch_collection_stats = AsyncMock(return_value=None)
        mock_client.cookie_expired = True

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1")
        assert "Cookie" in text

    async def test_successful_generation(self, db, mock_client):
        await db.bind_user("u1", "111", "Est")
        stats = make_stats(nickname="Est", total_marked=200)
        mock_client.fetch_collection_stats = AsyncMock(return_value=stats)

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1")
        assert "Est" in text
        assert "200" in text

    async def test_profile_cached(self, db, mock_client):
        """After generation, profile is cached in DB."""
        await db.bind_user("u1", "111", "Est")
        stats = make_stats(nickname="Est", total_marked=100)
        mock_client.fetch_collection_stats = AsyncMock(return_value=stats)

        gen = ProfileGenerator(db, mock_client)
        await gen.generate("u1")

        profile = await db.get_profile("u1")
        assert profile is not None
        assert profile["total_marked"] == 100

    async def test_uses_cached_profile(self, db, mock_client):
        """If cache is fresh (< 24h), uses cached profile."""
        await db.bind_user("u1", "111", "Est")
        await db.save_profile("u1", "缓存的画像", {}, [], [], [], 50)

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1")
        assert text == "缓存的画像"

    async def test_llm_integration_success(self, db, mock_client):
        await db.bind_user("u1", "111", "Est")
        stats = make_stats(nickname="Est")
        mock_client.fetch_collection_stats = AsyncMock(return_value=stats)

        # Delete any cached profile first
        await db._conn.execute("DELETE FROM user_profile WHERE astrbot_uid = 'u1'")
        await db._conn.commit()

        mock_context = MagicMock()
        mock_resp = MagicMock()
        mock_resp.completion_text = "你是一位资深影迷"
        mock_context.llm_generate = AsyncMock(return_value=mock_resp)

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1", persona_text="你是佩丽卡", context=mock_context, provider_id="test")
        assert "你是一位资深影迷" in text

        # Verify persona was passed as system_prompt
        call_kwargs = mock_context.llm_generate.call_args
        assert call_kwargs.kwargs.get("system_prompt") == "你是佩丽卡"

    async def test_llm_failure_falls_back(self, db, mock_client):
        await db.bind_user("u1", "111", "Est")
        stats = make_stats(nickname="Est")
        mock_client.fetch_collection_stats = AsyncMock(return_value=stats)

        # Delete cache
        await db._conn.execute("DELETE FROM user_profile WHERE astrbot_uid = 'u1'")
        await db._conn.commit()

        mock_context = MagicMock()
        mock_context.llm_generate = AsyncMock(side_effect=RuntimeError("fail"))

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1", context=mock_context, provider_id="test")
        assert "Est" in text  # Falls back to formatted text

    async def test_update_last_profile_called(self, db, mock_client):
        await db.bind_user("u1", "111", "Est")
        stats = make_stats(nickname="Est")
        mock_client.fetch_collection_stats = AsyncMock(return_value=stats)

        # Delete cache
        await db._conn.execute("DELETE FROM user_profile WHERE astrbot_uid = 'u1'")
        await db._conn.commit()

        gen = ProfileGenerator(db, mock_client)
        await gen.generate("u1")

        bind = await db.get_bind("u1")
        assert bind["last_profile"] is not None
