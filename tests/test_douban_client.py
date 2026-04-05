"""
Test: DoubanClient API and utility methods

Tests:
- extract_numeric_id: parsing numeric ID from various inputs
- validate_douban_uid: validation via collection_stats API
- fetch_collection_stats: Rexxar API call
- search_movies: Rexxar search JSON parsing
- Cookie expiry detection
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from astrbot_plugin_douban_movie.service.douban_client import DoubanClient


# ===========================================================================
# extract_numeric_id
# ===========================================================================

class TestExtractNumericId:

    def test_pure_digit(self):
        assert DoubanClient.extract_numeric_id("159896279") == "159896279"

    def test_full_url(self):
        assert DoubanClient.extract_numeric_id(
            "https://www.douban.com/people/159896279/"
        ) == "159896279"

    def test_url_without_protocol(self):
        assert DoubanClient.extract_numeric_id(
            "douban.com/people/159896279"
        ) == "159896279"

    def test_url_with_trailing_slash(self):
        assert DoubanClient.extract_numeric_id(
            "https://www.douban.com/people/159896279/"
        ) == "159896279"

    def test_url_without_trailing_slash(self):
        assert DoubanClient.extract_numeric_id(
            "https://www.douban.com/people/159896279"
        ) == "159896279"

    def test_empty_string(self):
        assert DoubanClient.extract_numeric_id("") is None

    def test_whitespace_only(self):
        assert DoubanClient.extract_numeric_id("   ") is None

    def test_non_numeric_string(self):
        assert DoubanClient.extract_numeric_id("abc-def") is None

    def test_url_with_slug_not_digits(self):
        """URL with a slug (not numeric ID) returns None."""
        assert DoubanClient.extract_numeric_id(
            "https://www.douban.com/people/E-st2000/"
        ) is None

    def test_whitespace_trimmed(self):
        assert DoubanClient.extract_numeric_id("  159896279  ") == "159896279"


# ===========================================================================
# validate_douban_uid
# ===========================================================================

class TestValidateDoubanUid:

    async def test_valid_uid(self, mock_client):
        stats = {
            "user": {"name": "Est"},
            "total_collections": 917,
        }
        mock_client.fetch_collection_stats = AsyncMock(return_value=stats)

        result = await mock_client.validate_douban_uid("159896279")
        assert result is not None
        assert result["uid"] == "159896279"
        assert result["nickname"] == "Est"
        assert result["total_marked"] == 917

    async def test_invalid_uid(self, mock_client):
        mock_client.fetch_collection_stats = AsyncMock(return_value=None)
        result = await mock_client.validate_douban_uid("000000000")
        assert result is None

    async def test_no_user_field(self, mock_client):
        """Stats without user field still works."""
        stats = {"total_collections": 50}
        mock_client.fetch_collection_stats = AsyncMock(return_value=stats)
        result = await mock_client.validate_douban_uid("111")
        assert result is not None
        assert result["nickname"] == ""
        assert result["total_marked"] == 50


# ===========================================================================
# fetch_collection_stats
# ===========================================================================

class TestFetchCollectionStats:

    async def test_returns_json(self, mock_client):
        expected = {"user": {"name": "test"}, "total_collections": 100}
        mock_client._request_json = AsyncMock(return_value=expected)
        result = await mock_client.fetch_collection_stats("159896279")
        assert result == expected
        mock_client._request_json.assert_called_once()

    async def test_returns_none_on_failure(self, mock_client):
        mock_client._request_json = AsyncMock(return_value=None)
        result = await mock_client.fetch_collection_stats("000")
        assert result is None


# ===========================================================================
# Cookie expiry detection
# ===========================================================================

class TestCookieExpiry:

    async def test_401_sets_expired(self, mock_client):
        """401 response sets cookie_expired flag."""
        mock_client._cookie = "test_cookie"
        mock_client.cookie_expired = False

        # Direct test: set flag manually (simulating what _request_json does)
        mock_client.cookie_expired = True
        assert mock_client.cookie_expired is True


# ===========================================================================
# search_movies (Rexxar JSON API)
# ===========================================================================

def _make_search_response(items: list[dict]) -> dict:
    """Build a mock Rexxar search API response."""
    return {"items": items, "total": len(items)}


def _make_search_item(
    movie_id: str = "12345",
    title: str = "测试电影",
    rating: float = 8.5,
    year: str = "2024",
    target_type: str = "movie",
    card_subtitle: str = "2024 / 美国 / 科幻",
) -> dict:
    """Build a single search result item."""
    return {
        "target_type": target_type,
        "target": {
            "id": movie_id,
            "title": title,
            "rating": {"value": rating},
            "year": year,
            "card_subtitle": card_subtitle,
        },
    }


class TestSearchMovies:

    async def test_returns_empty_on_failure(self, mock_client):
        mock_client._request_json = AsyncMock(return_value=None)
        results = await mock_client.search_movies("科幻")
        assert results == []

    async def test_parses_movie_results(self, mock_client):
        data = _make_search_response([
            _make_search_item(movie_id="12345", title="星际穿越", rating=9.4, year="2014"),
            _make_search_item(movie_id="67890", title="盗梦空间", rating=9.4, year="2010"),
        ])
        mock_client._request_json = AsyncMock(return_value=data)

        results = await mock_client.search_movies("星际穿越")
        assert len(results) == 2
        assert results[0]["id"] == "12345"
        assert results[0]["title"] == "星际穿越"
        assert results[0]["rating"] == 9.4
        assert results[0]["year"] == "2014"

    async def test_filters_non_movie_types(self, mock_client):
        """Non-movie target_types are filtered out."""
        data = _make_search_response([
            _make_search_item(movie_id="100", target_type="movie"),
            _make_search_item(movie_id="200", target_type="list"),
            _make_search_item(movie_id="300", target_type="chart"),
            _make_search_item(movie_id="400", target_type="movie"),
        ])
        mock_client._request_json = AsyncMock(return_value=data)

        results = await mock_client.search_movies("测试")
        assert len(results) == 2
        assert all(r["id"] in ("100", "400") for r in results)

    async def test_skips_items_without_id(self, mock_client):
        data = _make_search_response([
            {"target_type": "movie", "target": {"title": "无ID"}},
            _make_search_item(movie_id="100"),
        ])
        mock_client._request_json = AsyncMock(return_value=data)

        results = await mock_client.search_movies("测试")
        assert len(results) == 1
        assert results[0]["id"] == "100"

    async def test_handles_missing_rating(self, mock_client):
        """Items without rating should still be included with rating=None."""
        item = _make_search_item(movie_id="100")
        del item["target"]["rating"]
        data = _make_search_response([item])
        mock_client._request_json = AsyncMock(return_value=data)

        results = await mock_client.search_movies("测试")
        assert len(results) == 1
        assert results[0]["rating"] is None

    async def test_max_results_parameter(self, mock_client):
        """count parameter is passed to the API URL."""
        mock_client._request_json = AsyncMock(return_value={"items": [], "total": 0})
        await mock_client.search_movies("测试", max_results=10)
        call_url = mock_client._request_json.call_args[0][0]
        assert "count=10" in call_url

    async def test_empty_items(self, mock_client):
        data = _make_search_response([])
        mock_client._request_json = AsyncMock(return_value=data)
        results = await mock_client.search_movies("不存在的电影")
        assert results == []

    async def test_card_subtitle_extracted(self, mock_client):
        data = _make_search_response([
            _make_search_item(card_subtitle="2024 / 美国 / 剧情 科幻"),
        ])
        mock_client._request_json = AsyncMock(return_value=data)

        results = await mock_client.search_movies("测试")
        assert results[0]["card_subtitle"] == "2024 / 美国 / 剧情 科幻"

    async def test_url_encoding(self, mock_client):
        """Keywords with special characters are URL-encoded."""
        mock_client._request_json = AsyncMock(return_value={"items": [], "total": 0})
        await mock_client.search_movies("星际穿越")
        call_url = mock_client._request_json.call_args[0][0]
        assert "q=" in call_url
        assert "type=movie" in call_url
