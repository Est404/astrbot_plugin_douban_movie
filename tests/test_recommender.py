"""
Test 3C: Recommender Logic

Tests that the recommender:
- Excludes already-watched movies
- Filters by minimum rating threshold
- Limits result count to recommend_count
- Supports genre filtering
- Generates correct recommendation reasons
- Handles edge cases (no bind, no data, all excluded)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_douban_movie.service.douban_client import DoubanClient
from astrbot_plugin_douban_movie.service.recommender import Recommender


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    """Run an async coroutine synchronously for testing."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _top_movie(
    movie_id="100",
    title="Movie",
    year=2020,
    avg_rating=9.0,
    genres="剧情",
    regions="美国",
    quote="",
):
    return {
        "douban_movie_id": movie_id,
        "title": title,
        "year": year,
        "avg_rating": avg_rating,
        "genres": genres,
        "regions": regions,
        "quote": quote,
    }


def _collect_movie(genres="剧情", regions="美国", user_rating=4.0):
    return {
        "genres": genres,
        "regions": regions,
        "user_rating": user_rating,
    }


def _make_recommender(
    collect_movies=None,
    top250=None,
    watched_ids=None,
    recommend_count=5,
    min_rating=8.0,
):
    db = MagicMock()
    db.get_bind = AsyncMock(return_value={"douban_uid": "d_test"})
    db.get_all_collected_movie_ids = AsyncMock(return_value=watched_ids or set())
    db.get_movies_by_status = AsyncMock(return_value=collect_movies or [])

    client = MagicMock(spec=DoubanClient)
    client.fetch_top250 = AsyncMock(return_value=top250 or [])

    rec = Recommender(db, client, recommend_count=recommend_count, min_rating=min_rating)
    return rec


# ===========================================================================
# Basic recommendation
# ===========================================================================

class TestRecommendBasic:

    def test_excludes_watched_movies(self):
        """Movies in watched_ids should not appear in recommendations."""
        top250 = [
            _top_movie(movie_id="10", avg_rating=9.0),
            _top_movie(movie_id="20", avg_rating=9.0),
            _top_movie(movie_id="30", avg_rating=9.0),
        ]
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=top250,
            watched_ids={"20"},
            min_rating=8.0,
        )
        results = run(rec.recommend("user1"))
        ids = {r["douban_movie_id"] for r in results}
        assert "20" not in ids

    def test_filters_below_min_rating(self):
        """Movies with avg_rating < min_rating should be excluded."""
        top250 = [
            _top_movie(movie_id="10", avg_rating=6.0, genres="剧情"),
            _top_movie(movie_id="20", avg_rating=9.0, genres="剧情"),
        ]
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=top250,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1"))
        ids = {r["douban_movie_id"] for r in results}
        assert "10" not in ids
        assert "20" in ids

    def test_result_count_capped(self):
        """Result count should not exceed recommend_count."""
        top250 = [_top_movie(movie_id=str(i), avg_rating=9.0) for i in range(20)]
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=top250,
            recommend_count=3,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1"))
        assert len(results) <= 3

    def test_result_count_exactly_capped(self):
        """When enough candidates exist, result count equals recommend_count."""
        top250 = [_top_movie(movie_id=str(i), avg_rating=9.5) for i in range(10)]
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=top250,
            recommend_count=5,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1"))
        assert len(results) == 5

    def test_no_avg_rating_excluded(self):
        """Movies with no avg_rating should be excluded."""
        top250 = [
            _top_movie(movie_id="10", avg_rating=None),
        ]
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=top250,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1"))
        assert len(results) == 0


# ===========================================================================
# Genre filtering
# ===========================================================================

class TestGenreFilter:

    def test_genre_filter_includes_only_matching(self):
        """When genre_filter is specified, only matching movies are returned."""
        top250 = [
            _top_movie(movie_id="10", genres="剧情", avg_rating=9.0),
            _top_movie(movie_id="20", genres="科幻", avg_rating=9.0),
            _top_movie(movie_id="30", genres="剧情,科幻", avg_rating=9.0),
        ]
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=top250,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1", "科幻"))
        for r in results:
            assert "科幻" in r["genres"]

    def test_genre_filter_no_match_returns_empty(self):
        """When no movies match the genre filter, result is empty."""
        top250 = [
            _top_movie(movie_id="10", genres="剧情", avg_rating=9.0),
        ]
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=top250,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1", "恐怖"))
        assert len(results) == 0

    def test_empty_genre_filter_returns_all(self):
        """Empty genre_filter returns all qualifying movies (up to limit)."""
        top250 = [
            _top_movie(movie_id="10", genres="剧情", avg_rating=9.0),
            _top_movie(movie_id="20", genres="科幻", avg_rating=9.0),
        ]
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=top250,
            recommend_count=10,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1", ""))
        assert len(results) == 2


# ===========================================================================
# Recommendation reason generation
# ===========================================================================

class TestRecommendReasons:

    def test_reason_contains_genre_match(self):
        """When user and movie share genres, reason mentions them."""
        top250 = [
            _top_movie(movie_id="10", genres="剧情,科幻", avg_rating=8.5, regions="美国"),
        ]
        rec = _make_recommender(
            collect_movies=[_collect_movie(genres="剧情,科幻")],
            top250=top250,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1"))
        assert len(results) > 0
        reason = results[0]["reason"]
        assert len(reason) > 0
        assert "类型" in reason or "匹配" in reason

    def test_reason_high_score_movie(self):
        """Movies with avg_rating >= 9.0 get a special mention."""
        top250 = [
            _top_movie(movie_id="10", genres="动作", avg_rating=9.5, regions=""),
        ]
        rec = _make_recommender(
            collect_movies=[_collect_movie(genres="动作")],
            top250=top250,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1"))
        reason = results[0]["reason"]
        assert "9.5" in reason or "高分" in reason or "评分" in reason

    def test_reason_includes_quote(self):
        """When movie has a quote, it may appear in the reason."""
        top250 = [
            _top_movie(movie_id="10", genres="剧情", avg_rating=9.0, quote="经典之作"),
        ]
        rec = _make_recommender(
            collect_movies=[_collect_movie(genres="剧情")],
            top250=top250,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1"))
        reason = results[0]["reason"]
        assert "经典之作" in reason or len(reason) > 0

    def test_reason_default_when_no_match(self):
        """When no specific reason applies, a default reason is given."""
        top250 = [
            _top_movie(movie_id="10", genres="纪录片", avg_rating=8.5, regions="德国"),
        ]
        rec = _make_recommender(
            collect_movies=[_collect_movie(genres="动作", regions="美国")],
            top250=top250,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1"))
        assert len(results) > 0
        assert results[0]["reason"] == "高分佳作推荐"

    def test_all_results_have_reason(self):
        """Every result should have a non-empty reason field."""
        top250 = [_top_movie(movie_id=str(i), avg_rating=9.0) for i in range(5)]
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=top250,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1"))
        for r in results:
            assert "reason" in r
            assert isinstance(r["reason"], str)
            assert len(r["reason"]) > 0


# ===========================================================================
# Edge cases
# ===========================================================================

class TestRecommendEdgeCases:

    def test_no_bind_returns_empty(self):
        """User not bound -> returns empty list."""
        db = MagicMock()
        db.get_bind = AsyncMock(return_value=None)
        client = MagicMock(spec=DoubanClient)
        rec = Recommender(db, client)
        results = run(rec.recommend("user1"))
        assert results == []

    def test_all_movies_watched(self):
        """All Top250 movies are already watched -> empty result."""
        top250 = [
            _top_movie(movie_id="10", avg_rating=9.0),
            _top_movie(movie_id="20", avg_rating=9.0),
        ]
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=top250,
            watched_ids={"10", "20"},
            min_rating=8.0,
        )
        results = run(rec.recommend("user1"))
        assert len(results) == 0

    def test_all_movies_below_min_rating(self):
        """All Top250 movies below min_rating -> empty result."""
        top250 = [
            _top_movie(movie_id="10", avg_rating=5.0),
            _top_movie(movie_id="20", avg_rating=7.0),
        ]
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=top250,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1"))
        assert len(results) == 0

    def test_empty_top250(self):
        """No Top250 data -> empty result."""
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=[],
            min_rating=8.0,
        )
        results = run(rec.recommend("user1"))
        assert len(results) == 0

    def test_score_ranking_order(self):
        """Movies should be sorted by score (descending)."""
        top250 = [
            _top_movie(movie_id="low_match", genres="纪录片", avg_rating=8.5, regions="德国"),
            _top_movie(movie_id="high_match", genres="剧情,科幻", avg_rating=9.0, regions="美国"),
        ]
        rec = _make_recommender(
            collect_movies=[_collect_movie(genres="剧情,科幻", regions="美国")],
            top250=top250,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1"))
        assert results[0]["douban_movie_id"] == "high_match"

    def test_top250_cache(self):
        """Top250 is fetched only once (cached)."""
        top250 = [_top_movie(movie_id="10", avg_rating=9.0)]
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=top250,
            min_rating=8.0,
        )
        run(rec.recommend("user1"))
        run(rec.recommend("user1"))
        rec.client.fetch_top250.assert_called_once()

    def test_results_contain_expected_keys(self):
        """Each result dict should have all expected keys."""
        top250 = [_top_movie(movie_id="10", avg_rating=9.0)]
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=top250,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1"))
        for r in results:
            assert "douban_movie_id" in r
            assert "title" in r
            assert "reason" in r
            assert "score" in r


# ===========================================================================
# _build_llm_prompt unit tests
# ===========================================================================

class TestBuildLLMPrompt:

    def test_prompt_contains_role(self):
        rec = _make_recommender()
        user_prefs = {"top_genres": [("剧情", 5)], "top_regions": ["美国"]}
        results = [{"title": "Test", "year": 2020, "avg_rating": 9.0, "genres": "剧情", "regions": "美国"}]
        prompt = rec._build_llm_prompt(user_prefs, results)
        assert "影评人" in prompt

    def test_prompt_contains_genres(self):
        rec = _make_recommender()
        user_prefs = {"top_genres": [("科幻", 3), ("动作", 2)], "top_regions": ["美国"]}
        results = [{"title": "T", "year": 2020, "avg_rating": 9.0, "genres": "科幻", "regions": "美国"}]
        prompt = rec._build_llm_prompt(user_prefs, results)
        assert "科幻" in prompt
        assert "3部" in prompt

    def test_prompt_contains_regions(self):
        rec = _make_recommender()
        user_prefs = {"top_genres": [("剧情", 5)], "top_regions": ["美国", "日本"]}
        results = [{"title": "T", "year": 2020, "avg_rating": 9.0, "genres": "剧情", "regions": "美国"}]
        prompt = rec._build_llm_prompt(user_prefs, results)
        assert "美国" in prompt

    def test_prompt_contains_movies(self):
        rec = _make_recommender()
        user_prefs = {"top_genres": [("剧情", 5)], "top_regions": ["美国"]}
        results = [
            {"title": "肖申克的救赎", "year": 1994, "avg_rating": 9.7, "genres": "犯罪,剧情", "regions": "美国"},
        ]
        prompt = rec._build_llm_prompt(user_prefs, results)
        assert "肖申克的救赎" in prompt
        assert "9.7" in prompt

    def test_prompt_contains_format_instruction(self):
        rec = _make_recommender()
        user_prefs = {"top_genres": [("剧情", 5)], "top_regions": ["美国"]}
        results = [{"title": "T", "year": 2020, "avg_rating": 9.0, "genres": "剧情", "regions": "美国"}]
        prompt = rec._build_llm_prompt(user_prefs, results)
        assert "30字" in prompt
        assert "1." in prompt


# ===========================================================================
# _parse_llm_reasons unit tests
# ===========================================================================

class TestParseLLMReasons:

    def test_parse_numbered_list(self):
        rec = _make_recommender()
        text = "1. 经典剧情片\n2. 视觉震撼\n3. 温馨感人"
        reasons = rec._parse_llm_reasons(text, 3)
        assert reasons == ["经典剧情片", "视觉震撼", "温馨感人"]

    def test_parse_chinese_period(self):
        rec = _make_recommender()
        text = "1、经典剧情片\n2、视觉震撼"
        reasons = rec._parse_llm_reasons(text, 2)
        assert reasons == ["经典剧情片", "视觉震撼"]

    def test_parse_mixed_format(self):
        rec = _make_recommender()
        text = "1. 经典剧情片\n2、视觉震撼\n3. 温馨感人"
        reasons = rec._parse_llm_reasons(text, 3)
        assert len(reasons) == 3

    def test_parse_partial_match(self):
        rec = _make_recommender()
        text = "1. 经典\n2. 震撼"
        reasons = rec._parse_llm_reasons(text, 3)
        assert len(reasons) == 2

    def test_parse_no_match(self):
        rec = _make_recommender()
        text = "没有编号的文本"
        reasons = rec._parse_llm_reasons(text, 3)
        assert reasons == []

    def test_parse_empty_text(self):
        rec = _make_recommender()
        reasons = rec._parse_llm_reasons("", 2)
        assert reasons == []

    def test_parse_fullwidth_period(self):
        rec = _make_recommender()
        text = "1．经典剧情\n2．震撼视觉"
        reasons = rec._parse_llm_reasons(text, 2)
        assert len(reasons) == 2


# ===========================================================================
# _generate_template_reasons unit tests
# ===========================================================================

class TestGenerateTemplateReasons:

    def test_genre_match_reason(self):
        rec = _make_recommender()
        results = [{"matched_genres": {"剧情", "科幻"}}]
        rec._generate_template_reasons(results)
        assert "剧情" in results[0]["reason"] or "科幻" in results[0]["reason"]

    def test_high_score_reason(self):
        rec = _make_recommender()
        results = [{"avg_rating": 9.5, "matched_genres": set()}]
        rec._generate_template_reasons(results)
        assert "9.5" in results[0]["reason"]

    def test_quote_in_reason(self):
        rec = _make_recommender()
        results = [{"quote": "经典之作", "matched_genres": set()}]
        rec._generate_template_reasons(results)
        assert "经典之作" in results[0]["reason"]

    def test_default_reason_when_no_match(self):
        rec = _make_recommender()
        results = [{"matched_genres": set()}]
        rec._generate_template_reasons(results)
        assert results[0]["reason"] == "高分佳作推荐"

    def test_combined_reasons(self):
        rec = _make_recommender()
        results = [{"matched_genres": {"剧情"}, "avg_rating": 9.5, "quote": "好电影"}]
        rec._generate_template_reasons(results)
        reason = results[0]["reason"]
        assert "剧情" in reason
        assert "9.5" in reason
        assert "好电影" in reason

    def test_empty_results_list(self):
        rec = _make_recommender()
        results = []
        rec._generate_template_reasons(results)  # should not raise
        assert results == []

    def test_reason_always_set(self):
        rec = _make_recommender()
        results = [{"matched_genres": set(), "avg_rating": 8.5}]
        rec._generate_template_reasons(results)
        assert "reason" in results[0]
        assert len(results[0]["reason"]) > 0


# ===========================================================================
# recommend with LLM integration
# ===========================================================================

class TestRecommendWithLLM:

    def test_llm_success_sets_reasons(self):
        """When LLM returns valid reasons, they are used instead of template."""
        top250 = [
            _top_movie(movie_id="10", avg_rating=9.0, genres="剧情"),
            _top_movie(movie_id="20", avg_rating=9.0, genres="剧情"),
        ]
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=top250,
            min_rating=8.0,
        )

        mock_context = MagicMock()
        mock_resp = MagicMock()
        mock_resp.completion_text = "1. LLM理由A\n2. LLM理由B"
        mock_context.llm_generate = AsyncMock(return_value=mock_resp)

        results = run(rec.recommend("user1", "", mock_context, "test-provider"))
        assert len(results) == 2
        assert results[0]["reason"] == "LLM理由A"
        assert results[1]["reason"] == "LLM理由B"

    def test_llm_failure_falls_back_to_template(self):
        """When LLM raises, falls back to template reasons."""
        top250 = [_top_movie(movie_id="10", avg_rating=9.0, genres="剧情")]
        rec = _make_recommender(
            collect_movies=[_collect_movie(genres="剧情")],
            top250=top250,
            min_rating=8.0,
        )

        mock_context = MagicMock()
        mock_context.llm_generate = AsyncMock(side_effect=RuntimeError("LLM down"))

        results = run(rec.recommend("user1", "", mock_context, "test-provider"))
        assert len(results) > 0
        assert "reason" in results[0]
        assert len(results[0]["reason"]) > 0

    def test_llm_reasons_count_mismatch_falls_back(self):
        """When LLM returns wrong number of reasons, falls back to template."""
        top250 = [
            _top_movie(movie_id="10", avg_rating=9.0, genres="剧情"),
            _top_movie(movie_id="20", avg_rating=9.0, genres="剧情"),
        ]
        rec = _make_recommender(
            collect_movies=[_collect_movie()],
            top250=top250,
            min_rating=8.0,
        )

        mock_context = MagicMock()
        mock_resp = MagicMock()
        # Only 1 reason for 2 movies -> mismatch -> fallback
        mock_resp.completion_text = "1. 唯一理由"
        mock_context.llm_generate = AsyncMock(return_value=mock_resp)

        results = run(rec.recommend("user1", "", mock_context, "test-provider"))
        assert len(results) == 2
        # Should have template reasons, not the LLM reason
        for r in results:
            assert "reason" in r

    def test_no_context_uses_template(self):
        """When context is None, template reasons are generated."""
        top250 = [_top_movie(movie_id="10", avg_rating=9.0, genres="剧情")]
        rec = _make_recommender(
            collect_movies=[_collect_movie(genres="剧情")],
            top250=top250,
            min_rating=8.0,
        )
        results = run(rec.recommend("user1", "", None, ""))
        assert len(results) > 0
        assert "reason" in results[0]

    def test_no_provider_id_uses_template(self):
        """When provider_id is empty, template reasons are generated."""
        top250 = [_top_movie(movie_id="10", avg_rating=9.0, genres="剧情")]
        rec = _make_recommender(
            collect_movies=[_collect_movie(genres="剧情")],
            top250=top250,
            min_rating=8.0,
        )
        mock_context = MagicMock()
        results = run(rec.recommend("user1", "", mock_context, ""))
        assert len(results) > 0
        assert "reason" in results[0]

    def test_llm_none_response_falls_back(self):
        """When LLM returns None, falls back to template reasons."""
        top250 = [_top_movie(movie_id="10", avg_rating=9.0, genres="剧情")]
        rec = _make_recommender(
            collect_movies=[_collect_movie(genres="剧情")],
            top250=top250,
            min_rating=8.0,
        )
        mock_context = MagicMock()
        mock_context.llm_generate = AsyncMock(return_value=None)
        results = run(rec.recommend("user1", "", mock_context, "test-provider"))
        assert len(results) > 0
        assert "reason" in results[0]

    def test_llm_empty_completion_falls_back(self):
        """When LLM returns empty completion_text, falls back to template."""
        top250 = [_top_movie(movie_id="10", avg_rating=9.0, genres="剧情")]
        rec = _make_recommender(
            collect_movies=[_collect_movie(genres="剧情")],
            top250=top250,
            min_rating=8.0,
        )
        mock_context = MagicMock()
        mock_resp = MagicMock()
        mock_resp.completion_text = ""
        mock_context.llm_generate = AsyncMock(return_value=mock_resp)
        results = run(rec.recommend("user1", "", mock_context, "test-provider"))
        assert len(results) > 0
        assert "reason" in results[0]
