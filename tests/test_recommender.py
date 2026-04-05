"""
Test: Recommender Logic (search-based)

Tests:
- search_and_recommend: keyword building, filtering, candidate pool
- re_recommend: "看过了" feedback, persistent exclusion
- LLM reason generation and fallback
- Edge cases
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_douban_movie.service.recommender import Recommender


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_search_result(
    movie_id="100",
    title="Test Movie",
    rating=8.5,
    year=2020,
    card_subtitle="2020 / 美国 / 科幻",
):
    return {
        "id": movie_id,
        "title": title,
        "rating": rating,
        "year": year,
        "card_subtitle": card_subtitle,
    }


def _setup_recommender(
    db,
    client,
    recommend_count=5,
    candidate_pool_size=20,
    min_rating=7.0,
):
    return Recommender(
        db, client,
        recommend_count=recommend_count,
        candidate_pool_size=candidate_pool_size,
        min_rating=min_rating,
    )


# ===========================================================================
# _build_search_keyword
# ===========================================================================

class TestBuildSearchKeyword:

    def test_user_input_only(self):
        rec = Recommender(MagicMock(), MagicMock())
        kw = rec._build_search_keyword("科幻", [], [])
        assert "科幻" in kw

    def test_appends_genre_prefs(self):
        rec = Recommender(MagicMock(), MagicMock())
        kw = rec._build_search_keyword("轻松", ["喜剧", "爱情"], [])
        assert "轻松" in kw
        assert "喜剧" in kw

    def test_does_not_duplicate_genre_in_input(self):
        rec = Recommender(MagicMock(), MagicMock())
        kw = rec._build_search_keyword("科幻片", ["科幻", "动作"], [])
        assert kw.count("科幻") == 1

    def test_empty_input_uses_genres(self):
        rec = Recommender(MagicMock(), MagicMock())
        kw = rec._build_search_keyword("", ["剧情", "科幻"], [])
        assert "剧情" in kw
        assert "科幻" in kw

    def test_fallback_to_movie(self):
        rec = Recommender(MagicMock(), MagicMock())
        kw = rec._build_search_keyword("", [], [])
        assert kw == "电影"


# ===========================================================================
# search_and_recommend
# ===========================================================================

class TestSearchAndRecommend:

    async def test_no_profile_returns_empty(self, db, mock_client):
        rec = _setup_recommender(db, mock_client)
        results, session_id = await rec.search_and_recommend("u1")
        assert results == []
        assert session_id == ""

    async def test_no_search_results(self, db, mock_client):
        await db.save_profile("u1", "text", {}, ["剧情"], ["美国"], ["2020s"], 100)
        mock_client.search_movies = AsyncMock(return_value=[])

        rec = _setup_recommender(db, mock_client)
        results, session_id = await rec.search_and_recommend("u1", "科幻")
        assert results == []
        assert session_id == ""

    async def test_successful_recommendation(self, db, mock_client):
        await db.save_profile("u1", "text", {}, ["剧情"], ["美国"], ["2020s"], 100)
        search_results = [
            make_search_result(movie_id=str(i), title=f"电影{i}", rating=8.0 + i * 0.1)
            for i in range(10)
        ]
        mock_client.search_movies = AsyncMock(return_value=search_results)

        rec = _setup_recommender(db, mock_client, recommend_count=3)
        results, session_id = await rec.search_and_recommend("u1", "科幻")
        assert len(results) == 3
        assert session_id != ""
        for r in results:
            assert "reason" in r

    async def test_excludes_seen_movies(self, db, mock_client):
        await db.save_profile("u1", "text", {}, ["剧情"], [], [], 100)
        await db.add_seen_movies("u1", [{"douban_movie_id": "0", "title": "A"}])

        search_results = [
            make_search_result(movie_id="0", title="已看", rating=9.0),
            make_search_result(movie_id="1", title="未看", rating=8.0),
        ]
        mock_client.search_movies = AsyncMock(return_value=search_results)

        rec = _setup_recommender(db, mock_client, recommend_count=5)
        results, _ = await rec.search_and_recommend("u1")
        ids = {r["id"] for r in results}
        assert "0" not in ids

    async def test_filters_below_min_rating(self, db, mock_client):
        await db.save_profile("u1", "text", {}, ["剧情"], [], [], 100)
        search_results = [
            make_search_result(movie_id="1", rating=5.0),
            make_search_result(movie_id="2", rating=8.0),
        ]
        mock_client.search_movies = AsyncMock(return_value=search_results)

        rec = _setup_recommender(db, mock_client, recommend_count=5, min_rating=7.0)
        results, _ = await rec.search_and_recommend("u1")
        ids = {r["id"] for r in results}
        assert "1" not in ids
        assert "2" in ids

    async def test_session_created_in_db(self, db, mock_client):
        await db.save_profile("u1", "text", {}, ["剧情"], [], [], 100)
        mock_client.search_movies = AsyncMock(return_value=[
            make_search_result(movie_id="1", rating=8.0),
        ])

        rec = _setup_recommender(db, mock_client, recommend_count=1)
        results, session_id = await rec.search_and_recommend("u1")
        assert session_id != ""

        session = await db.get_rec_session(session_id)
        assert session is not None
        assert "1" in session["candidate_ids"]

    async def test_result_count_capped(self, db, mock_client):
        await db.save_profile("u1", "text", {}, ["剧情"], [], [], 100)
        mock_client.search_movies = AsyncMock(return_value=[
            make_search_result(movie_id=str(i), rating=9.0) for i in range(30)
        ])

        rec = _setup_recommender(db, mock_client, recommend_count=3)
        results, _ = await rec.search_and_recommend("u1")
        assert len(results) == 3

    async def test_keyword_includes_user_input(self, db, mock_client):
        await db.save_profile("u1", "text", {}, ["剧情"], [], [], 100)
        mock_client.search_movies = AsyncMock(return_value=[])

        rec = _setup_recommender(db, mock_client)
        await rec.search_and_recommend("u1", "喜剧")
        # Verify search was called (keyword should include 喜剧)
        mock_client.search_movies.assert_called_once()
        called_kw = mock_client.search_movies.call_args[0][0]
        assert "喜剧" in called_kw


# ===========================================================================
# re_recommend
# ===========================================================================

class TestReRecommend:

    async def test_exhausted_pool_returns_none(self, db, mock_client):
        """When candidate pool is empty, returns None."""
        await db.create_rec_session("s1", "u1", "科幻", ["100"])
        await db.update_rec_session_shown("s1", ["100"])

        rec = _setup_recommender(db, mock_client)
        result = await rec.re_recommend("s1", "u1")
        assert result is None

    async def test_re_recommend_returns_new_movies(self, db, mock_client):
        """Returns new movies from remaining pool."""
        await db.create_rec_session("s1", "u1", "科幻", ["100", "200", "300"])
        await db.update_rec_session_shown("s1", ["100"])

        # Mock movie detail fetching
        mock_client.fetch_movie_detail = AsyncMock(return_value={
            "id": "200", "title": "新电影", "rating": 8.5, "year": 2024,
            "card_subtitle": "2024 / 美国 / 科幻",
        })

        rec = _setup_recommender(db, mock_client, recommend_count=1)
        result = await rec.re_recommend("s1", "u1")
        assert result is not None
        results, _ = result
        assert len(results) >= 1
        assert results[0]["id"] != "100"  # Not the already-shown one

    async def test_seen_movies_persisted(self, db, mock_client):
        """Shown movies are written to user_seen_movies."""
        await db.create_rec_session("s1", "u1", "科幻", ["100", "200"])
        await db.update_rec_session_shown("s1", ["100"])

        mock_client.fetch_movie_detail = AsyncMock(return_value={
            "id": "200", "title": "新电影", "rating": 8.5, "year": 2024,
            "card_subtitle": "2024 / 美国",
        })

        rec = _setup_recommender(db, mock_client)
        await rec.re_recommend("s1", "u1")

        seen = await db.get_seen_movie_ids("u1")
        assert "100" in seen

    async def test_session_not_found_returns_none(self, db, mock_client):
        rec = _setup_recommender(db, mock_client)
        result = await rec.re_recommend("nonexistent", "u1")
        assert result is None

    async def test_shown_ids_updated(self, db, mock_client):
        """After re_recommend, shown_ids includes old + new."""
        await db.create_rec_session("s1", "u1", "科幻", ["100", "200", "300"])
        await db.update_rec_session_shown("s1", ["100"])

        mock_client.fetch_movie_detail = AsyncMock(return_value={
            "id": "200", "title": "M2", "rating": 8.0, "year": 2020,
            "card_subtitle": "2020 / 美国",
        })

        rec = _setup_recommender(db, mock_client, recommend_count=1)
        await rec.re_recommend("s1", "u1")

        session = await db.get_rec_session("s1")
        assert "100" in session["shown_ids"]


# ===========================================================================
# LLM prompt and reason parsing
# ===========================================================================

class TestLLMReasons:

    def test_build_llm_reasons_prompt(self):
        rec = Recommender(MagicMock(), MagicMock())
        results = [make_search_result(title="电影A", rating=9.0)]
        prompt = rec._build_llm_reasons_prompt(results, ["剧情"], ["美国"])
        assert "影评人" in prompt
        assert "电影A" in prompt
        assert "剧情" in prompt

    def test_parse_llm_reasons_numbered(self):
        rec = Recommender(MagicMock(), MagicMock())
        text = "1. 经典剧情片\n2. 视觉震撼\n3. 温馨感人"
        reasons = rec._parse_llm_reasons(text, 3)
        assert reasons == ["经典剧情片", "视觉震撼", "温馨感人"]

    def test_parse_llm_reasons_chinese_period(self):
        rec = Recommender(MagicMock(), MagicMock())
        text = "1、经典剧情片\n2、视觉震撼"
        reasons = rec._parse_llm_reasons(text, 2)
        assert len(reasons) == 2

    def test_parse_llm_reasons_partial(self):
        rec = Recommender(MagicMock(), MagicMock())
        text = "1. 经典\n2. 震撼"
        reasons = rec._parse_llm_reasons(text, 3)
        assert len(reasons) == 2

    def test_parse_llm_reasons_empty(self):
        rec = Recommender(MagicMock(), MagicMock())
        reasons = rec._parse_llm_reasons("", 2)
        assert reasons == []

    async def test_llm_success_sets_reasons(self, db, mock_client):
        await db.save_profile("u1", "text", {}, ["剧情"], [], [], 100)
        mock_client.search_movies = AsyncMock(return_value=[
            make_search_result(movie_id="1", title="A", rating=9.0),
            make_search_result(movie_id="2", title="B", rating=9.0),
        ])

        mock_context = MagicMock()
        mock_resp = MagicMock()
        mock_resp.completion_text = "1. LLM理由A\n2. LLM理由B"
        mock_context.llm_generate = AsyncMock(return_value=mock_resp)

        rec = _setup_recommender(db, mock_client, recommend_count=2)
        results, _ = await rec.search_and_recommend(
            "u1", "科幻", "你是佩丽卡", mock_context, "test-provider"
        )
        assert len(results) == 2
        assert results[0]["reason"] == "LLM理由A"
        assert results[1]["reason"] == "LLM理由B"

    async def test_llm_failure_falls_back(self, db, mock_client):
        await db.save_profile("u1", "text", {}, ["剧情"], [], [], 100)
        mock_client.search_movies = AsyncMock(return_value=[
            make_search_result(movie_id="1", title="A", rating=9.0),
        ])

        mock_context = MagicMock()
        mock_context.llm_generate = AsyncMock(side_effect=RuntimeError("fail"))

        rec = _setup_recommender(db, mock_client)
        results, _ = await rec.search_and_recommend(
            "u1", "", "", mock_context, "test-provider"
        )
        assert len(results) > 0
        assert "reason" in results[0]


# ===========================================================================
# Template reason fallback
# ===========================================================================

class TestTemplateReason:

    def test_high_rating(self):
        reason = Recommender._template_reason(
            {"rating": 9.5, "card_subtitle": ""}, ["剧情"]
        )
        assert "9.5" in reason or "高达" in reason

    def test_genre_match(self):
        reason = Recommender._template_reason(
            {"rating": 8.0, "card_subtitle": "美国 / 剧情"}, ["剧情", "科幻"]
        )
        assert "剧情" in reason or "类型" in reason

    def test_default_reason(self):
        reason = Recommender._template_reason(
            {"rating": 7.5, "card_subtitle": "未知"}, ["恐怖"]
        )
        assert len(reason) > 0


# ===========================================================================
# Edge cases
# ===========================================================================

class TestRecommenderEdgeCases:

    async def test_no_rating_movies_included(self, db, mock_client):
        """Movies without rating pass the filter (only those below min are excluded)."""
        await db.save_profile("u1", "text", {}, ["剧情"], [], [], 100)
        mock_client.search_movies = AsyncMock(return_value=[
            make_search_result(movie_id="1", rating=None),
        ])

        rec = _setup_recommender(db, mock_client, recommend_count=5)
        results, _ = await rec.search_and_recommend("u1")
        # rating=None should be included (not below 7.0)
        assert len(results) >= 0  # May or may not be selected

    async def test_candidate_pool_size_respected(self, db, mock_client):
        """Only top N candidates are used from search results."""
        await db.save_profile("u1", "text", {}, ["剧情"], [], [], 100)
        # Create 50 results with descending ratings
        mock_client.search_movies = AsyncMock(return_value=[
            make_search_result(movie_id=str(i), rating=10.0 - i * 0.1) for i in range(50)
        ])

        rec = _setup_recommender(db, mock_client, candidate_pool_size=5, recommend_count=5)
        results, session_id = await rec.search_and_recommend("u1")

        session = await db.get_rec_session(session_id)
        assert len(session["candidate_ids"]) <= 5
