"""
Test 3B: ProfileGenerator Logic

Tests that the profile generation correctly:
- Aggregates genre preferences (TOP 5)
- Aggregates region preferences (TOP 3)
- Aggregates decade preferences
- Determines rating type (lenient/strict/neutral)
- Handles edge cases (empty data, missing fields)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_douban_movie.service.profile import ProfileGenerator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_movie(
    title: str = "M",
    genres: str = "",
    regions: str = "",
    year: int | None = 2020,
    user_rating: float | None = None,
) -> dict:
    return {
        "title": title,
        "genres": genres,
        "regions": regions,
        "year": year,
        "user_rating": user_rating,
    }


def make_db(movies: list[dict]) -> MagicMock:
    db = MagicMock()
    db.get_movies_by_status = AsyncMock(return_value=movies)
    return db


def run(coro):
    """Run an async coroutine synchronously for testing."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# Profile with data
# ===========================================================================

class TestProfileWithData:

    MOVIES = [
        make_movie("A", "剧情,科幻", "美国,英国", 2020, 4.0),
        make_movie("B", "剧情", "中国", 2015, 3.0),
        make_movie("C", "科幻,动作", "美国", 2010, 5.0),
        make_movie("D", "喜剧", "日本", 2022, 4.0),
        make_movie("E", "剧情,喜剧", "中国,香港", 2018, 3.5),
    ]

    @pytest.fixture
    def profile_text(self):
        db = make_db(self.MOVIES)
        gen = ProfileGenerator(db)
        return run(gen.generate("user1"))

    def test_contains_header(self, profile_text):
        assert "观影画像" in profile_text

    def test_contains_total_count(self, profile_text):
        assert "看过：5 部" in profile_text

    def test_contains_genre_preference(self, profile_text):
        assert "类型偏好" in profile_text
        # 剧情 appears 3 times (A, B, E) -> should be in TOP 5
        assert "剧情" in profile_text

    def test_genre_top5_count(self, profile_text):
        """Genre section should show counts."""
        # 剧情: 3 movies
        assert "3部" in profile_text

    def test_contains_region_preference(self, profile_text):
        assert "地区偏好" in profile_text
        # 美国 appears 2 times (A, C)
        assert "美国" in profile_text

    def test_region_top3(self, profile_text):
        """At most 3 regions listed."""
        assert "地区偏好 TOP 3" in profile_text

    def test_contains_decade_preference(self, profile_text):
        assert "年代偏好" in profile_text

    def test_contains_rating_habit(self, profile_text):
        assert "评分习惯" in profile_text

    def test_rating_type_is_neutral(self, profile_text):
        """Average rating = (4+3+5+4+3.5)/5 = 3.9 -> neutral (between 2.5 and 4.0 exclusive)."""
        assert "中立型" in profile_text

    def test_average_rating_displayed(self, profile_text):
        assert "平均打分" in profile_text


# ===========================================================================
# Rating type classification
# ===========================================================================

class TestRatingTypes:

    def test_lenient_rating(self):
        """avg >= 4.0 -> lenient."""
        movies = [make_movie(user_rating=5.0) for _ in range(3)]
        db = make_db(movies)
        gen = ProfileGenerator(db)
        text = run(gen.generate("u"))
        assert "宽容型" in text

    def test_strict_rating(self):
        """avg <= 2.5 -> strict."""
        movies = [make_movie(user_rating=1.0) for _ in range(3)]
        db = make_db(movies)
        gen = ProfileGenerator(db)
        text = run(gen.generate("u"))
        assert "严厉型" in text

    def test_neutral_rating(self):
        """2.5 < avg < 4.0 -> neutral."""
        movies = [make_movie(user_rating=3.0) for _ in range(3)]
        db = make_db(movies)
        gen = ProfileGenerator(db)
        text = run(gen.generate("u"))
        assert "中立型" in text

    def test_exactly_4_0_is_lenient(self):
        """avg == 4.0 -> lenient (>= 4.0)."""
        movies = [make_movie(user_rating=4.0) for _ in range(3)]
        db = make_db(movies)
        gen = ProfileGenerator(db)
        text = run(gen.generate("u"))
        assert "宽容型" in text

    def test_exactly_2_5_is_strict(self):
        """avg == 2.5 -> strict (<= 2.5)."""
        movies = [make_movie(user_rating=2.5) for _ in range(3)]
        db = make_db(movies)
        gen = ProfileGenerator(db)
        text = run(gen.generate("u"))
        assert "严厉型" in text

    def test_no_ratings_zero_avg(self):
        """Movies without ratings -> avg=0 -> strict."""
        movies = [make_movie(title="NR", genres="剧情", user_rating=None) for _ in range(3)]
        db = make_db(movies)
        gen = ProfileGenerator(db)
        text = run(gen.generate("u"))
        assert "严厉型" in text


# ===========================================================================
# Edge cases
# ===========================================================================

class TestProfileEdgeCases:

    def test_no_data_returns_placeholder(self):
        """Empty movie list -> returns placeholder."""
        db = make_db([])
        gen = ProfileGenerator(db)
        text = run(gen.generate("user1"))
        assert "暂无观影数据" in text

    def test_movies_without_genres(self):
        """Movies with empty genres -> no crash."""
        movies = [make_movie(title="NG", genres="", regions="美国", year=2020, user_rating=4.0)]
        db = make_db(movies)
        gen = ProfileGenerator(db)
        text = run(gen.generate("u"))
        assert "观影画像" in text

    def test_movies_without_regions(self):
        """Movies with empty regions -> no crash."""
        movies = [make_movie(title="NR", genres="剧情", regions="", year=2020, user_rating=4.0)]
        db = make_db(movies)
        gen = ProfileGenerator(db)
        text = run(gen.generate("u"))
        assert "观影画像" in text

    def test_movies_without_year(self):
        """Movies with None year -> no crash."""
        movies = [make_movie(title="NY", genres="剧情", regions="美国", year=None, user_rating=4.0)]
        db = make_db(movies)
        gen = ProfileGenerator(db)
        text = run(gen.generate("u"))
        assert "观影画像" in text

    def test_single_movie(self):
        """Single movie still produces a valid profile."""
        movies = [make_movie(title="S", genres="动作", regions="日本", year=1995, user_rating=5.0)]
        db = make_db(movies)
        gen = ProfileGenerator(db)
        text = run(gen.generate("u"))
        assert "看过：1 部" in text
        assert "动作" in text

    def test_genre_with_extra_commas(self):
        """Genres like '剧情,,科幻,' should not create empty genre entries."""
        movies = [make_movie(title="EC", genres="剧情,,科幻,", regions="", year=2020, user_rating=4.0)]
        db = make_db(movies)
        gen = ProfileGenerator(db)
        text = run(gen.generate("u"))
        assert "观影画像" in text


# ===========================================================================
# _collect_stats unit tests
# ===========================================================================

class TestCollectStats:

    def _collect(self, movies):
        gen = ProfileGenerator(MagicMock())
        return gen._collect_stats(movies)

    def test_total_count(self):
        movies = [make_movie() for _ in range(7)]
        stats = self._collect(movies)
        assert stats["total"] == 7

    def test_empty_movies(self):
        stats = self._collect([])
        assert stats["total"] == 0
        assert stats["top_genres"] == []
        assert stats["avg_rating"] == 0

    def test_genre_counts(self):
        movies = [
            make_movie(genres="剧情,科幻"),
            make_movie(genres="剧情"),
            make_movie(genres="科幻,动作"),
        ]
        stats = self._collect(movies)
        genre_map = {g: s["count"] for g, s in stats["top_genres"]}
        assert genre_map["剧情"] == 2
        assert genre_map["科幻"] == 2
        assert genre_map["动作"] == 1

    def test_genre_limited_to_top5(self):
        movies = [make_movie(genres=f"类型{i}") for i in range(10)]
        stats = self._collect(movies)
        assert len(stats["top_genres"]) <= 5

    def test_genre_ratings_tracked(self):
        movies = [
            make_movie(genres="剧情", user_rating=4.0),
            make_movie(genres="剧情", user_rating=5.0),
        ]
        stats = self._collect(movies)
        drama_entry = [g for g, s in stats["top_genres"] if g == "剧情"]
        assert len(drama_entry) == 1
        ratings = dict(stats["top_genres"])["剧情"]["ratings"]
        assert ratings == [4.0, 5.0]

    def test_region_counts(self):
        movies = [
            make_movie(regions="美国,英国"),
            make_movie(regions="美国"),
            make_movie(regions="中国"),
        ]
        stats = self._collect(movies)
        region_map = dict(stats["top_regions"])
        assert region_map["美国"] == 2
        assert region_map["英国"] == 1

    def test_region_limited_to_top3(self):
        movies = [make_movie(regions=f"地区{i}") for i in range(10)]
        stats = self._collect(movies)
        assert len(stats["top_regions"]) <= 3

    def test_decade_counts(self):
        movies = [
            make_movie(year=1995),
            make_movie(year=1998),
            make_movie(year=2020),
        ]
        stats = self._collect(movies)
        decade_map = dict(stats["top_decades"])
        assert decade_map["1990s"] == 2
        assert decade_map["2020s"] == 1

    def test_avg_rating(self):
        movies = [
            make_movie(user_rating=3.0),
            make_movie(user_rating=5.0),
        ]
        stats = self._collect(movies)
        assert stats["avg_rating"] == pytest.approx(4.0)

    def test_rating_count(self):
        movies = [
            make_movie(user_rating=4.0),
            make_movie(user_rating=None),
            make_movie(user_rating=3.0),
        ]
        stats = self._collect(movies)
        assert stats["rating_count"] == 2

    def test_null_ratings_excluded_from_avg(self):
        movies = [
            make_movie(user_rating=None),
            make_movie(user_rating=None),
        ]
        stats = self._collect(movies)
        assert stats["avg_rating"] == 0
        assert stats["rating_count"] == 0

    def test_returns_expected_keys(self):
        stats = self._collect([make_movie()])
        expected = {"total", "top_genres", "top_regions", "top_decades", "avg_rating", "rating_count"}
        assert set(stats.keys()) == expected


# ===========================================================================
# _format_stats_text unit tests
# ===========================================================================

class TestFormatStatsText:

    def _format(self, movies):
        gen = ProfileGenerator(MagicMock())
        stats = gen._collect_stats(movies)
        return gen._format_stats_text(stats)

    def test_contains_header(self):
        text = self._format([make_movie()])
        assert "观影画像" in text

    def test_contains_total(self):
        text = self._format([make_movie() for _ in range(3)])
        assert "看过：3 部" in text

    def test_lenient_label(self):
        text = self._format([make_movie(user_rating=5.0) for _ in range(3)])
        assert "宽容型" in text

    def test_strict_label(self):
        text = self._format([make_movie(user_rating=1.0) for _ in range(3)])
        assert "严厉型" in text

    def test_neutral_label(self):
        text = self._format([make_movie(user_rating=3.0) for _ in range(3)])
        assert "中立型" in text


# ===========================================================================
# _build_llm_prompt unit tests
# ===========================================================================

class TestBuildLLMPrompt:

    def _prompt(self, movies):
        gen = ProfileGenerator(MagicMock())
        stats = gen._collect_stats(movies)
        return gen._build_llm_prompt(stats)

    def test_contains_system_instruction(self):
        prompt = self._prompt([make_movie()])
        assert "影评分析师" in prompt

    def test_contains_total_count(self):
        prompt = self._prompt([make_movie() for _ in range(5)])
        assert "5 部电影" in prompt

    def test_contains_genre_info(self):
        prompt = self._prompt([make_movie(genres="剧情")])
        assert "类型偏好" in prompt
        assert "剧情" in prompt

    def test_contains_region_info(self):
        prompt = self._prompt([make_movie(regions="美国")])
        assert "地区偏好" in prompt

    def test_contains_decade_info(self):
        prompt = self._prompt([make_movie(year=2020)])
        assert "年代偏好" in prompt

    def test_output_instruction(self):
        prompt = self._prompt([make_movie()])
        assert "200字" in prompt


# ===========================================================================
# generate with LLM integration
# ===========================================================================

class TestGenerateWithLLM:

    def test_llm_success_appends_stats_text(self):
        """When LLM returns a result, the output contains both LLM text and stats text."""
        db = make_db([make_movie(genres="剧情", user_rating=4.0)])
        gen = ProfileGenerator(db)

        mock_context = MagicMock()
        mock_resp = MagicMock()
        mock_resp.completion_text = "你是一位资深影迷"
        mock_context.llm_generate = AsyncMock(return_value=mock_resp)

        text = run(gen.generate("u", context=mock_context, provider_id="test-provider"))
        assert "你是一位资深影迷" in text
        assert "观影画像" in text

    def test_llm_failure_falls_back_to_text(self):
        """When LLM raises an exception, falls back to pure text."""
        db = make_db([make_movie(genres="剧情", user_rating=4.0)])
        gen = ProfileGenerator(db)

        mock_context = MagicMock()
        mock_context.llm_generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        text = run(gen.generate("u", context=mock_context, provider_id="test-provider"))
        assert "观影画像" in text

    def test_llm_empty_response_falls_back(self):
        """When LLM returns empty completion_text, falls back to pure text."""
        db = make_db([make_movie(genres="剧情", user_rating=4.0)])
        gen = ProfileGenerator(db)

        mock_context = MagicMock()
        mock_resp = MagicMock()
        mock_resp.completion_text = ""
        mock_context.llm_generate = AsyncMock(return_value=mock_resp)

        text = run(gen.generate("u", context=mock_context, provider_id="test-provider"))
        assert "观影画像" in text

    def test_llm_none_response_falls_back(self):
        """When LLM returns None, falls back to pure text."""
        db = make_db([make_movie(genres="剧情", user_rating=4.0)])
        gen = ProfileGenerator(db)

        mock_context = MagicMock()
        mock_context.llm_generate = AsyncMock(return_value=None)

        text = run(gen.generate("u", context=mock_context, provider_id="test-provider"))
        assert "观影画像" in text

    def test_no_context_uses_text(self):
        """When context is None, pure text profile is generated."""
        db = make_db([make_movie(genres="剧情", user_rating=4.0)])
        gen = ProfileGenerator(db)
        text = run(gen.generate("u", context=None, provider_id=""))
        assert "观影画像" in text

    def test_no_provider_id_uses_text(self):
        """When provider_id is empty, pure text profile is generated."""
        db = make_db([make_movie(genres="剧情", user_rating=4.0)])
        gen = ProfileGenerator(db)
        mock_context = MagicMock()
        text = run(gen.generate("u", context=mock_context, provider_id=""))
        assert "观影画像" in text
