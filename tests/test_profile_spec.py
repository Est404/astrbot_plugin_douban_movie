"""
Test: Profile generation against REQUIREMENTS.md 2.1/2.2/2.3 spec

Verifies that profile.py correctly:
- Extracts all fields from the real collection_stats API response (2.1)
- Computes percentages for genres/countries/years
- Formats fallback text output matching the spec example (2.3)
- Builds LLM prompt with complete data
- Handles missing/empty fields gracefully
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_douban_movie.service.profile import ProfileGenerator


# ---------------------------------------------------------------------------
# Mock data matching REQUIREMENTS.md 2.1 exact API structure
# ---------------------------------------------------------------------------

MOCK_API_RESPONSE = {
    "total_collections": 917,
    "total_comment": 724,
    "total_review": 13,
    "total_spent": 2288.1,
    "total_cenima": 202,
    "weekly_avg": 1.98,
    "incr_from_last_week": 0.0000031,
    "user": {
        "name": "Est",
        "uid": "E-st2000",
        "id": "159896279",
        "loc": {"name": "洛阳"},
    },
    "genres": [
        {"name": "剧情", "value": 601},
        {"name": "科幻", "value": 189},
        {"name": "爱情", "value": 157},
        {"name": "动作", "value": 155},
        {"name": "惊悚", "value": 151},
        {"name": "悬疑", "value": 130},
        {"name": "喜剧", "value": 120},
        {"name": "冒险", "value": 110},
        {"name": "奇幻", "value": 90},
        {"name": "犯罪", "value": 85},
    ],
    "countries": [
        {"name": "美国", "value": 491},
        {"name": "英国", "value": 178},
        {"name": "日本", "value": 168},
        {"name": "法国", "value": 132},
        {"name": "德国", "value": 78},
        {"name": "中国大陆", "value": 60},
    ],
    "years": [
        {"name": "2010s", "value": 396},
        {"name": "2000s", "value": 213},
        {"name": "2020-2025", "value": 60},
        {"name": "1990s", "value": 198},
        {"name": "1980s", "value": 50},
    ],
    "collect_years": [
        {"name": "2018", "value": 20},
        {"name": "2019", "value": 333},
        {"name": "2020", "value": 150},
        {"name": "2021", "value": 100},
        {"name": "2022", "value": 80},
        {"name": "2023", "value": 120},
        {"name": "2024", "value": 94},
    ],
    "directors": [
        {
            "name": "克里斯托弗·诺兰",
            "id": "1041202",
            "avatar": "https://img.doubanio.com/img/...",
            "known_for": [
                {
                    "id": "3541415",
                    "title": "盗梦空间",
                    "year": "2010",
                    "rating": {"value": 9.4, "count": 2318463},
                    "genres": ["剧情", "科幻", "悬疑"],
                    "directors": [{"name": "克里斯托弗·诺兰"}],
                    "card_subtitle": "2010 / 美国 英国 / 剧情 科幻 悬疑 冒险 / 克里斯托弗·诺兰 / 莱昂纳多·迪卡普里奥",
                },
                {
                    "id": "1851857",
                    "title": "星际穿越",
                    "year": "2014",
                    "rating": {"value": 9.4, "count": 2158630},
                    "genres": ["剧情", "科幻", "冒险"],
                },
                {
                    "id": "other1",
                    "title": "记忆碎片",
                    "year": "2000",
                    "rating": {"value": 8.7},
                },
            ],
        },
        {
            "name": "史蒂文·斯皮尔伯格",
            "id": "1040502",
            "known_for": [
                {"id": "1292321", "title": "辛德勒的名单", "year": "1993"},
                {"id": "1292728", "title": "拯救大兵瑞恩", "year": "1998"},
            ],
        },
        {
            "name": "马丁·斯科塞斯",
            "id": "1045102",
            "known_for": [
                {"id": "1292262", "title": "出租车司机", "year": "1976"},
                {"id": "1299232", "title": "好家伙", "year": "1990"},
            ],
        },
    ],
    "actors": [
        {
            "name": "莱昂纳多·迪卡普里奥",
            "id": "1041022",
            "known_for": [
                {"id": "3541415", "title": "盗梦空间", "year": "2010"},
                {"id": "25845692", "title": "华尔街之狼", "year": "2013"},
            ],
        },
        {
            "name": "布拉德·皮特",
            "id": "1041023",
            "known_for": [
                {"id": "1292262", "title": "搏击俱乐部", "year": "1999"},
                {"id": "1292728", "title": "无耻混蛋", "year": "2009"},
            ],
        },
        {
            "name": "汤姆·汉克斯",
            "id": "1041024",
            "known_for": [
                {"id": "1292064", "title": "阿甘正传", "year": "1994"},
                {"id": "1292321", "title": "拯救大兵瑞恩", "year": "1998"},
            ],
        },
    ],
    "participants": [
        {"name": "莱昂纳多·迪卡普里奥", "roles": ["演员"]},
        {"name": "克里斯托弗·诺兰", "roles": ["导演", "编剧", "制片人"]},
        {"name": "布拉德·皮特", "roles": ["演员", "制片人"]},
        {"name": "史蒂文·斯皮尔伯格", "roles": ["导演", "制片人", "编剧"]},
        {"name": "汤姆·汉克斯", "roles": ["演员", "导演", "制片人"]},
    ],
    "recent_subjects": [
        {
            "id": "36846801",
            "title": "辐射 第二季",
            "type": "tv",
            "subtype": "tv",
            "year": "2025",
            "rating": {"value": 8.2, "count": 19713, "star_count": 4.0},
            "genres": ["剧情", "动作", "科幻"],
            "card_subtitle": "2025 / 美国 / 剧情 动作 科幻 战争 冒险",
            "directors": [{"name": "弗雷德里克·E·O·托耶"}],
            "actors": [{"name": "艾拉·珀内尔"}],
            "cover_url": "https://img.doubanio.com/img/...",
            "url": "https://movie.douban.com/subject/36846801/",
        },
        {
            "id": "1293963",
            "title": "极度空间",
            "type": "movie",
            "year": "1988",
            "rating": {"value": 7.4, "count": 45000},
            "genres": ["喜剧", "科幻", "恐怖"],
            "card_subtitle": "1988 / 美国 / 喜剧 科幻 恐怖",
        },
        {
            "id": "36156235",
            "title": "首尔之春",
            "type": "movie",
            "year": "2023",
            "rating": {"value": 8.8, "count": 230000},
            "genres": ["剧情"],
            "card_subtitle": "2023 / 韩国 / 剧情",
        },
    ],
    "viewer": {},
    "recent_collected": 0,
    "mark_more": "douban://douban.com/delegate/more/",
    "color_scheme": {"is_dark": True, "primary_color": "#4A148C"},
}


# ===========================================================================
# 2.1 Field extraction tests
# ===========================================================================

class TestExtractPrefsFromStats:
    """Verify _extract_prefs_from_stats handles all fields from 2.1 spec."""

    def setup_method(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        self.prefs = gen._extract_prefs_from_stats(MOCK_API_RESPONSE)

    def test_total_marked(self):
        assert self.prefs["total_marked"] == 917

    def test_total_hours(self):
        assert self.prefs["total_hours"] == 2288.1

    def test_total_cinema(self):
        assert self.prefs["total_cinema"] == 202

    def test_total_comments(self):
        assert self.prefs["total_comments"] == 724

    def test_total_reviews(self):
        assert self.prefs["total_reviews"] == 13

    def test_weekly_avg(self):
        assert self.prefs["weekly_avg"] == 1.98

    def test_nickname(self):
        assert self.prefs["nickname"] == "Est"

    # ── Genre extraction & percentage ──

    def test_genre_top6_extracted(self):
        genres = self.prefs["genre_prefs"]
        assert len(genres) == 6

    def test_genre_first_is_drama(self):
        assert self.prefs["genre_prefs"][0]["name"] == "剧情"

    def test_genre_first_value(self):
        assert self.prefs["genre_prefs"][0]["value"] == 601

    def test_genre_first_percent(self):
        """剧情 601/917 ≈ 66%"""
        assert self.prefs["genre_prefs"][0]["percent"] == 66

    def test_genre_second_percent(self):
        """科幻 189/917 ≈ 21%"""
        assert self.prefs["genre_prefs"][1]["percent"] == 21

    def test_genre_percent_bounded(self):
        for g in self.prefs["genre_prefs"]:
            assert 0 <= g["percent"] <= 100

    # ── Country extraction & percentage ──

    def test_country_top5_extracted(self):
        assert len(self.prefs["country_prefs"]) == 5

    def test_country_first_is_usa(self):
        assert self.prefs["country_prefs"][0]["name"] == "美国"

    def test_country_first_percent(self):
        """美国 491/917 ≈ 54%"""
        assert self.prefs["country_prefs"][0]["percent"] == 54

    def test_country_second_percent(self):
        """英国 178/917 ≈ 19%"""
        assert self.prefs["country_prefs"][1]["percent"] == 19

    # ── Decade extraction & percentage ──

    def test_decades_extracted(self):
        assert len(self.prefs["decade_prefs"]) == 5

    def test_decade_first_is_2010s(self):
        assert self.prefs["decade_prefs"][0]["name"] == "2010s"

    def test_decade_first_percent(self):
        """2010s 396/917 ≈ 43%"""
        assert self.prefs["decade_prefs"][0]["percent"] == 43

    # ── Collect years ──

    def test_collect_years_extracted(self):
        cy = self.prefs["collect_years"]
        assert len(cy) == 7

    def test_collect_years_peak(self):
        peak = max(cy["value"] for cy in self.prefs["collect_years"])
        assert peak == 333

    # ── Directors ──

    def test_top_directors_count(self):
        assert len(self.prefs["top_directors"]) == 3

    def test_director_names(self):
        names = [d["name"] for d in self.prefs["top_directors"]]
        assert names == ["克里斯托弗·诺兰", "史蒂文·斯皮尔伯格", "马丁·斯科塞斯"]

    def test_director_known_for_limited_to_2(self):
        """known_for should only take first 2 works."""
        nolan = self.prefs["top_directors"][0]
        assert len(nolan["known_for"]) == 2
        assert "盗梦空间" in nolan["known_for"]
        assert "星际穿越" in nolan["known_for"]
        # 3rd work (记忆碎片) should NOT be included
        assert "记忆碎片" not in nolan["known_for"]

    # ── Actors ──

    def test_top_actors_count(self):
        assert len(self.prefs["top_actors"]) == 3

    def test_actor_names(self):
        names = [a["name"] for a in self.prefs["top_actors"]]
        assert "莱昂纳多·迪卡普里奥" in names

    def test_actor_known_for(self):
        leo = self.prefs["top_actors"][0]
        assert "盗梦空间" in leo["known_for"]
        assert "华尔街之狼" in leo["known_for"]

    # ── Recent watched ──

    def test_recent_watched_extracted(self):
        assert len(self.prefs["recent_watched"]) == 3

    def test_recent_first_title(self):
        assert self.prefs["recent_watched"][0]["title"] == "辐射 第二季"

    def test_recent_first_year(self):
        assert self.prefs["recent_watched"][0]["year"] == "2025"

    def test_recent_first_type(self):
        assert self.prefs["recent_watched"][0]["type"] == "tv"

    def test_recent_first_rating(self):
        assert self.prefs["recent_watched"][0]["rating"] == 8.2

    def test_recent_third_rating(self):
        assert self.prefs["recent_watched"][2]["rating"] == 8.8


# ===========================================================================
# Edge cases — missing/empty fields
# ===========================================================================

class TestExtractPrefsEdgeCases:

    def test_empty_response(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        prefs = gen._extract_prefs_from_stats({})
        assert prefs["total_marked"] == 0
        assert prefs["genre_prefs"] == []
        assert prefs["top_directors"] == []
        assert prefs["recent_watched"] == []

    def test_missing_directors_known_for(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        data = {"total_collections": 10, "directors": [{"name": "某导演"}]}
        prefs = gen._extract_prefs_from_stats(data)
        assert prefs["top_directors"][0]["known_for"] == []

    def test_missing_recent_subjects_rating(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        data = {
            "total_collections": 10,
            "recent_subjects": [{"title": "无评分", "year": "2020", "type": "movie"}],
        }
        prefs = gen._extract_prefs_from_stats(data)
        assert prefs["recent_watched"][0]["rating"] is None

    def test_percent_with_zero_total(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        data = {"total_collections": 0, "genres": [{"name": "剧情", "value": 5}]}
        prefs = gen._extract_prefs_from_stats(data)
        assert prefs["genre_prefs"][0]["percent"] == 0


# ===========================================================================
# 2.3 Fallback text output format
# ===========================================================================

class TestFallbackFormat:

    def setup_method(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        self.prefs = gen._extract_prefs_from_stats(MOCK_API_RESPONSE)
        self.text = gen._format_profile_from_stats(self.prefs, "Est")

    def test_contains_nickname(self):
        assert "Est" in self.text

    def test_contains_total_marked(self):
        assert "917" in self.text

    def test_contains_total_hours(self):
        assert "2288" in self.text

    def test_contains_cinema_count(self):
        assert "202" in self.text

    def test_contains_genre_names(self):
        assert "剧情" in self.text
        assert "科幻" in self.text

    def test_contains_genre_percent(self):
        assert "66%" in self.text

    def test_contains_country_names(self):
        assert "美国" in self.text

    def test_contains_country_percent(self):
        assert "54%" in self.text

    def test_contains_decade(self):
        assert "2010s" in self.text

    def test_contains_director_names(self):
        assert "克里斯托弗·诺兰" in self.text

    def test_contains_actor_names(self):
        assert "莱昂纳多·迪卡普里奥" in self.text

    def test_contains_recent_watched(self):
        assert "辐射 第二季" in self.text

    def test_contains_recent_rating(self):
        assert "8.2" in self.text

    def test_starts_with_movie_emoji(self):
        assert self.text.startswith("🎬")


# ===========================================================================
# LLM prompt construction
# ===========================================================================

class TestLLMPrompt:

    def setup_method(self):
        gen = ProfileGenerator(MagicMock(), MagicMock())
        self.prefs = gen._extract_prefs_from_stats(MOCK_API_RESPONSE)
        self.prompt = gen._build_llm_prompt(self.prefs, "Est")

    def test_contains_nickname(self):
        assert "Est" in self.prompt

    def test_contains_total_marked(self):
        assert "917" in self.prompt

    def test_contains_total_hours(self):
        assert "2288" in self.prompt

    def test_contains_cinema_count(self):
        assert "202" in self.prompt

    def test_contains_genre_data(self):
        assert "剧情" in self.prompt
        assert "科幻" in self.prompt
        assert "66%" in self.prompt

    def test_contains_country_data(self):
        assert "美国" in self.prompt
        assert "54%" in self.prompt

    def test_contains_decade_data(self):
        assert "2010s" in self.prompt

    def test_contains_director_with_known_for(self):
        assert "克里斯托弗·诺兰" in self.prompt
        assert "盗梦空间" in self.prompt

    def test_contains_actor_with_known_for(self):
        assert "莱昂纳多·迪卡普里奥" in self.prompt

    def test_contains_recent_watched(self):
        assert "辐射 第二季" in self.prompt

    def test_contains_peak_year_insight(self):
        """Prompt should detect 2019 as peak year."""
        assert "2019" in self.prompt
        assert "333" in self.prompt

    def test_contains_second_person_instruction(self):
        assert "第二人称" in self.prompt or '"你"' in self.prompt

    def test_contains_analyst_role(self):
        assert "观影分析师" in self.prompt


# ===========================================================================
# Full generate flow
# ===========================================================================

class TestGenerateFlow:

    async def test_generate_with_llm_success(self, db, mock_client):
        await db.bind_user("u1", "159896279", "Est")
        mock_client.fetch_collection_stats = AsyncMock(return_value=MOCK_API_RESPONSE)

        mock_context = MagicMock()
        mock_resp = MagicMock()
        mock_resp.completion_text = "你是一位偏爱剧情与科幻的重度影迷"
        mock_context.llm_generate = AsyncMock(return_value=mock_resp)

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1", persona_text="你是佩丽卡", context=mock_context, provider_id="p")

        assert "偏爱剧情与科幻" in text
        assert "Est" in text

        # Verify persona injected as system_prompt
        call_kwargs = mock_context.llm_generate.call_args
        assert call_kwargs.kwargs.get("system_prompt") == "你是佩丽卡"

        # Verify cache saved
        cached = await db.get_profile("u1")
        assert cached is not None
        assert cached["total_marked"] == 917

    async def test_generate_llm_failure_fallback(self, db, mock_client):
        await db.bind_user("u1", "159896279", "Est")
        mock_client.fetch_collection_stats = AsyncMock(return_value=MOCK_API_RESPONSE)

        mock_context = MagicMock()
        mock_context.llm_generate = AsyncMock(side_effect=RuntimeError("fail"))

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1", context=mock_context, provider_id="p")

        assert "Est" in text
        assert "917" in text

    async def test_generate_uses_cache(self, db, mock_client):
        await db.bind_user("u1", "159896279", "Est")
        await db.save_profile("u1", "缓存的画像文本", {}, [], [], [], 917)

        # Replace with AsyncMock to track calls
        mock_client.fetch_collection_stats = AsyncMock(return_value=None)

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1")
        assert text == "缓存的画像文本"
        mock_client.fetch_collection_stats.assert_not_called()

    async def test_generate_no_bind(self, db, mock_client):
        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("ghost")
        assert "绑定" in text

    async def test_generate_cookie_expired(self, db, mock_client):
        await db.bind_user("u1", "159896279", "Est")
        mock_client.fetch_collection_stats = AsyncMock(return_value=None)
        mock_client.cookie_expired = True

        gen = ProfileGenerator(db, mock_client)
        text = await gen.generate("u1")
        assert "Cookie" in text

    async def test_genre_prefs_saved(self, db, mock_client):
        await db.bind_user("u1", "159896279", "Est")
        await db._conn.execute("DELETE FROM user_profile WHERE astrbot_uid = 'u1'")
        await db._conn.commit()
        mock_client.fetch_collection_stats = AsyncMock(return_value=MOCK_API_RESPONSE)

        gen = ProfileGenerator(db, mock_client)
        await gen.generate("u1")

        profile = await db.get_profile("u1")
        assert "剧情" in profile["genre_prefs"]

    async def test_country_prefs_saved(self, db, mock_client):
        await db.bind_user("u1", "159896279", "Est")
        await db._conn.execute("DELETE FROM user_profile WHERE astrbot_uid = 'u1'")
        await db._conn.commit()
        mock_client.fetch_collection_stats = AsyncMock(return_value=MOCK_API_RESPONSE)

        gen = ProfileGenerator(db, mock_client)
        await gen.generate("u1")

        profile = await db.get_profile("u1")
        assert "美国" in profile["region_prefs"]
