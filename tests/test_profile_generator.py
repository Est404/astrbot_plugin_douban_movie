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
    genres: list[dict] | None = None,
    recent_subjects: list[dict] | None = None,
) -> dict:
    """Build a collection_stats API response."""
    if genres is None:
        genres = [{"name": "剧情", "value": 50}, {"name": "科幻", "value": 30}]
    if recent_subjects is None:
        recent_subjects = [
            {
                "title": "测试电影",
                "id": "12345",
                "year": "2024",
                "type": "movie",
                "rating": {"value": 8.5},
                "genres": ["剧情", "科幻"],
                "card_subtitle": "2024 / 美国 / 剧情 / 科幻",
            },
            {
                "title": "测试电影B",
                "id": "67890",
                "year": "2020",
                "type": "tv",
                "rating": {"value": 7.0},
                "genres": ["喜剧"],
                "card_subtitle": "2020 / 日本 / 喜剧",
            },
        ]
    return {
        "total_collections": total_marked,
        "total_spent": float(total_marked) * 2.5,
        "total_cenima": 10,
        "total_comment": 50,
        "total_review": 5,
        "weekly_avg": 1.5,
        "user": {"name": nickname},
        "genres": genres,
        "countries": [
            {"name": "美国", "value": 50},
            {"name": "日本", "value": 30},
            {"name": "中国", "value": 20},
        ],
        "years": [
            {"name": "2020s", "value": 40},
            {"name": "2010s", "value": 60},
        ],
        "collect_years": [
            {"name": "2023", "value": 40},
            {"name": "2024", "value": 60},
        ],
        "directors": [
            {"name": "导演A", "known_for": [{"title": "作品1"}, {"title": "作品2"}]},
        ],
        "actors": [
            {"name": "演员A", "known_for": [{"title": "作品3"}]},
        ],
        "recent_subjects": recent_subjects,
    }


# ===========================================================================
# _extract_prefs_from_stats
# ===========================================================================

class TestExtractPrefs:

    def test_total_marked(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = gen._extract_prefs_from_stats(make_stats(total_marked=200))
        assert prefs["total_marked"] == 200

    def test_total_hours(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = gen._extract_prefs_from_stats(make_stats(total_marked=100))
        assert prefs["total_hours"] == 250.0

    def test_nickname(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = gen._extract_prefs_from_stats(make_stats(nickname="TestNick"))
        assert prefs["nickname"] == "TestNick"

    def test_genre_prefs(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = gen._extract_prefs_from_stats(make_stats(
            genres=[{"name": "剧情", "value": 60}, {"name": "科幻", "value": 40}]
        ))
        assert len(prefs["genre_prefs"]) == 2
        assert prefs["genre_prefs"][0]["name"] == "剧情"
        assert prefs["genre_prefs"][0]["percent"] == 60

    def test_region_prefs(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = gen._extract_prefs_from_stats(make_stats())
        assert len(prefs["country_prefs"]) == 3
        assert prefs["country_prefs"][0]["name"] == "美国"

    def test_decade_prefs(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = gen._extract_prefs_from_stats(make_stats())
        assert len(prefs["decade_prefs"]) == 2

    def test_directors(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = gen._extract_prefs_from_stats(make_stats())
        assert len(prefs["top_directors"]) == 1
        assert prefs["top_directors"][0]["name"] == "导演A"

    def test_actors(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = gen._extract_prefs_from_stats(make_stats())
        assert len(prefs["top_actors"]) == 1
        assert prefs["top_actors"][0]["name"] == "演员A"

    def test_recent_watched(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = gen._extract_prefs_from_stats(make_stats())
        assert len(prefs["recent_watched"]) == 2
        assert prefs["recent_watched"][0]["title"] == "测试电影"

    def test_empty_response(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = gen._extract_prefs_from_stats({})
        assert prefs["total_marked"] == 0
        assert prefs["genre_prefs"] == []
        assert prefs["recent_watched"] == []

    def test_genre_limited_to_6(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        genres = [{"name": f"类型{i}", "value": i} for i in range(15)]
        prefs = gen._extract_prefs_from_stats(make_stats(genres=genres))
        assert len(prefs["genre_prefs"]) <= 6

    def test_country_limited_to_5(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        stats = make_stats()
        stats["countries"] = [{"name": f"地区{i}", "value": i} for i in range(10)]
        prefs = gen._extract_prefs_from_stats(stats)
        assert len(prefs["country_prefs"]) <= 5

    def test_empty_recent_subjects(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = gen._extract_prefs_from_stats(make_stats(recent_subjects=[]))
        assert prefs["recent_watched"] == []

    def test_directors_limited_to_3(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        stats = make_stats()
        stats["directors"] = [{"name": f"导演{i}", "known_for": []} for i in range(10)]
        prefs = gen._extract_prefs_from_stats(stats)
        assert len(prefs["top_directors"]) == 3

    def test_actors_limited_to_3(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        stats = make_stats()
        stats["actors"] = [{"name": f"演员{i}", "known_for": []} for i in range(10)]
        prefs = gen._extract_prefs_from_stats(stats)
        assert len(prefs["top_actors"]) == 3

    def test_known_for_limited_to_2(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        stats = make_stats()
        stats["directors"] = [{"name": "导演A", "known_for": [
            {"title": "作品1"}, {"title": "作品2"}, {"title": "作品3"},
        ]}]
        prefs = gen._extract_prefs_from_stats(stats)
        assert len(prefs["top_directors"][0]["known_for"]) == 2


# ===========================================================================
# _format_profile_from_stats
# ===========================================================================

class TestFormatProfile:

    def _format(self, stats=None):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        if stats is None:
            stats = make_stats()
        prefs = gen._extract_prefs_from_stats(stats)
        return gen._format_profile_from_stats(prefs, prefs.get("nickname", ""))

    def test_contains_nickname(self):
        text = self._format(make_stats(nickname="Est"))
        assert "Est" in text

    def test_contains_total_marked(self):
        text = self._format(make_stats(total_marked=42))
        assert "42" in text

    def test_genre_prefs_displayed(self):
        text = self._format(make_stats(
            genres=[{"name": "剧情", "value": 70}, {"name": "科幻", "value": 30}]
        ))
        assert "剧情" in text
        assert "科幻" in text

    def test_country_prefs_displayed(self):
        text = self._format()
        assert "美国" in text

    def test_director_names_displayed(self):
        text = self._format()
        assert "导演A" in text

    def test_actor_names_displayed(self):
        text = self._format()
        assert "演员A" in text

    def test_recent_watched_displayed(self):
        text = self._format()
        assert "测试电影" in text

    def test_empty_prefs_no_crash(self):
        text = self._format({})
        assert "0" in text  # total_marked = 0


# ===========================================================================
# _build_llm_prompt
# ===========================================================================

class TestBuildLLMPrompt:

    def _prompt(self, stats=None):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        if stats is None:
            stats = make_stats()
        prefs = gen._extract_prefs_from_stats(stats)
        return gen._build_llm_prompt(prefs, prefs.get("nickname", ""))

    def test_contains_analyst_role(self):
        prompt = self._prompt()
        assert "观影分析师" in prompt

    def test_contains_nickname(self):
        prompt = self._prompt(make_stats(nickname="Est"))
        assert "Est" in prompt

    def test_contains_genre_info(self):
        prompt = self._prompt(make_stats(
            genres=[{"name": "剧情", "value": 70}, {"name": "科幻", "value": 30}]
        ))
        assert "剧情" in prompt

    def test_contains_second_person_instruction(self):
        prompt = self._prompt()
        assert "第二人称" in prompt or '"你"' in prompt


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
        mock_client.fetch_collection_stats = AsyncMock(return_value=make_stats(nickname="Est", total_marked=200))

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1")
        assert "Est" in text
        assert "200" in text

    async def test_profile_cached(self, db, mock_client):
        await db.bind_user("u1", "111", "Est")
        mock_client.fetch_collection_stats = AsyncMock(return_value=make_stats())

        gen = ProfileGenerator(db, mock_client)
        await gen.generate("u1")

        profile = await db.get_profile("u1")
        assert profile is not None
        assert profile["total_marked"] == 100

    async def test_uses_cached_profile(self, db, mock_client):
        await db.bind_user("u1", "111", "Est")
        await db.save_profile("u1", "缓存的画像文本", {}, [], [], [], 50)

        mock_client.fetch_collection_stats = AsyncMock(return_value=None)

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1")
        assert text == "缓存的画像文本"
        mock_client.fetch_collection_stats.assert_not_called()

    async def test_llm_integration_success(self, db, mock_client):
        await db.bind_user("u1", "111", "Est")
        await db._conn.execute("DELETE FROM user_profile WHERE astrbot_uid = 'u1'")
        await db._conn.commit()
        mock_client.fetch_collection_stats = AsyncMock(return_value=make_stats(nickname="Est"))

        mock_context = MagicMock()
        mock_resp = MagicMock()
        mock_resp.completion_text = "你是一位资深影迷"
        mock_context.llm_generate = AsyncMock(return_value=mock_resp)

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1", persona_text="你是佩丽卡", context=mock_context, provider_id="test")
        assert "资深影迷" in text
        # Verify persona injected
        call_kwargs = mock_context.llm_generate.call_args
        assert call_kwargs.kwargs.get("system_prompt") == "你是佩丽卡"

    async def test_llm_failure_falls_back(self, db, mock_client):
        await db.bind_user("u1", "111", "Est")
        await db._conn.execute("DELETE FROM user_profile WHERE astrbot_uid = 'u1'")
        await db._conn.commit()
        mock_client.fetch_collection_stats = AsyncMock(return_value=make_stats(nickname="Est"))

        mock_context = MagicMock()
        mock_context.llm_generate = AsyncMock(side_effect=RuntimeError("fail"))

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1", context=mock_context, provider_id="test")
        assert "Est" in text

    async def test_llm_empty_response_falls_back(self, db, mock_client):
        await db.bind_user("u1", "111", "Est")
        await db._conn.execute("DELETE FROM user_profile WHERE astrbot_uid = 'u1'")
        await db._conn.commit()
        mock_client.fetch_collection_stats = AsyncMock(return_value=make_stats(nickname="Est"))

        mock_context = MagicMock()
        mock_resp = MagicMock()
        mock_resp.completion_text = ""
        mock_context.llm_generate = AsyncMock(return_value=mock_resp)

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1", context=mock_context, provider_id="test")
        assert "Est" in text

    async def test_no_context_uses_fallback(self, db, mock_client):
        await db.bind_user("u1", "111", "Est")
        await db._conn.execute("DELETE FROM user_profile WHERE astrbot_uid = 'u1'")
        await db._conn.commit()
        mock_client.fetch_collection_stats = AsyncMock(return_value=make_stats(nickname="Est"))

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1")
        assert "Est" in text

    async def test_update_last_profile_called(self, db, mock_client):
        await db.bind_user("u1", "111", "Est")
        await db._conn.execute("DELETE FROM user_profile WHERE astrbot_uid = 'u1'")
        await db._conn.commit()
        mock_client.fetch_collection_stats = AsyncMock(return_value=make_stats())

        gen = ProfileGenerator(db, mock_client)
        await gen.generate("u1")

        bind = await db.get_bind("u1")
        assert bind["last_profile"] is not None
