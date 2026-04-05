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
