"""
Test 3A: DoubanClient HTML Parsing Logic

Tests _parse_collection_item and _parse_top250_item against various HTML
fragments, including edge cases.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from bs4 import BeautifulSoup

from astrbot_plugin_douban_movie.service.douban_client import DoubanClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_collection_item(html_fragment: str):
    """Wrap an HTML fragment in a .item div and return the parsed element."""
    soup = BeautifulSoup(
        f"<div class='item'>{html_fragment}</div>", "html.parser"
    )
    return soup.select_one(".item")


def make_top250_item(html_fragment: str):
    """Wrap an HTML fragment in a Top250 list structure."""
    soup = BeautifulSoup(
        f"<ol class='grid_view'><li>{html_fragment}</li></ol>", "html.parser"
    )
    return soup.select_one("ol.grid_view > li")


# ===========================================================================
# _parse_collection_item
# ===========================================================================

class TestParseCollectionItemBasic:
    """Basic parsing of collection items."""

    def test_parse_basic_collect_item(self):
        """Parse a typical 'collect' entry with all fields."""
        item = make_collection_item("""
            <a href="https://movie.douban.com/subject/1234567/" title="测试电影"></a>
            <span class="rating4-t"></span>
            <span class="date">2024-01-15</span>
            <span class="tags">标签: 科幻 冒险</span>
        """)
        result = DoubanClient._parse_collection_item(item, "collect")

        assert result is not None
        assert result["douban_movie_id"] == "1234567"
        assert result["title"] == "测试电影"
        assert result["status"] == "collect"
        assert result["user_rating"] == 4.0
        assert result["marked_at"] == "2024-01-15"

    def test_parse_wish_status(self):
        """Parse an item with status='wish' (typically no rating)."""
        item = make_collection_item("""
            <a href="https://movie.douban.com/subject/999/" title="Wishlist Movie"></a>
            <span class="date">2024-03-20</span>
        """)
        result = DoubanClient._parse_collection_item(item, "wish")

        assert result is not None
        assert result["status"] == "wish"
        assert result["user_rating"] is None

    def test_parse_do_status(self):
        """Parse an item with status='do'."""
        item = make_collection_item("""
            <a href="https://movie.douban.com/subject/888/" title="Watching"></a>
            <span class="rating3-t"></span>
        """)
        result = DoubanClient._parse_collection_item(item, "do")

        assert result is not None
        assert result["status"] == "do"
        assert result["user_rating"] == 3.0


class TestParseCollectionItemRatings:
    """Test all 5 rating levels."""

    @pytest.mark.parametrize("rating_cls,expected", [
        ("rating1-t", 1.0),
        ("rating2-t", 2.0),
        ("rating3-t", 3.0),
        ("rating4-t", 4.0),
        ("rating5-t", 5.0),
    ])
    def test_rating_class_mapping(self, rating_cls, expected):
        item = make_collection_item(f"""
            <a href="https://movie.douban.com/subject/100/" title="R"></a>
            <span class="{rating_cls}"></span>
        """)
        result = DoubanClient._parse_collection_item(item, "collect")
        assert result["user_rating"] == expected

    def test_no_rating_element(self):
        """No rating span -> user_rating is None."""
        item = make_collection_item("""
            <a href="https://movie.douban.com/subject/100/" title="NR"></a>
        """)
        result = DoubanClient._parse_collection_item(item, "collect")
        assert result["user_rating"] is None


class TestParseCollectionItemEdgeCases:
    """Edge cases for collection item parsing."""

    def test_no_link_returns_none(self):
        """No <a> tag with /subject/ -> returns None."""
        item = make_collection_item("<span>No link here</span>")
        result = DoubanClient._parse_collection_item(item, "collect")
        assert result is None

    def test_link_without_subject_pattern_returns_none(self):
        """Link that doesn't match /subject/ID/ pattern -> returns None."""
        item = make_collection_item("""
            <a href="https://www.douban.com/people/abc/" title="Not a movie"></a>
        """)
        result = DoubanClient._parse_collection_item(item, "collect")
        assert result is None

    def test_no_date_element(self):
        """Missing date -> marked_at is None."""
        item = make_collection_item("""
            <a href="https://movie.douban.com/subject/100/" title="NoDate"></a>
        """)
        result = DoubanClient._parse_collection_item(item, "collect")
        assert result["marked_at"] is None

    def test_tags_prefix_stripped(self):
        """'标签:' prefix should be stripped from tags."""
        item = make_collection_item("""
            <a href="https://movie.douban.com/subject/100/" title="T"></a>
            <span class="tags">标签: 喜剧 动画</span>
        """)
        result = DoubanClient._parse_collection_item(item, "collect")
        assert not result["genres"].startswith("标签:")
        assert "喜剧" in result["genres"]

    def test_no_tags_element(self):
        """Missing tags -> genres is empty string."""
        item = make_collection_item("""
            <a href="https://movie.douban.com/subject/100/" title="T"></a>
        """)
        result = DoubanClient._parse_collection_item(item, "collect")
        assert result["genres"] == ""

    def test_title_from_img_alt(self):
        """When <a> has no title attr, title may come from inner text."""
        item = make_collection_item("""
            <a href="https://movie.douban.com/subject/100/">电影名文本</a>
        """)
        result = DoubanClient._parse_collection_item(item, "collect")
        assert result["title"] == "电影名文本"

    def test_numeric_movie_id(self):
        """Movie ID is extracted as a string of digits."""
        item = make_collection_item("""
            <a href="https://movie.douban.com/subject/25845692/" title="ID Test"></a>
        """)
        result = DoubanClient._parse_collection_item(item, "collect")
        assert result["douban_movie_id"] == "25845692"
        assert result["douban_movie_id"].isdigit()


# ===========================================================================
# _parse_top250_item
# ===========================================================================

class TestParseTop250ItemBasic:
    """Basic Top250 item parsing."""

    def test_parse_full_top250_item(self):
        """Parse a fully populated Top250 entry."""
        item = make_top250_item("""
            <div class="pic">
                <a href="https://movie.douban.com/subject/1292052/">
                    <img alt="肖申克的救赎" />
                </a>
            </div>
            <div class="info">
                <div class="hd">
                    <span class="title">肖申克的救赎</span>
                </div>
                <div class="bd">
                    <p>导演: Frank Darabont&nbsp;&nbsp;&nbsp;主演: Tim Robbins
                    1994&nbsp;/&nbsp;美国&nbsp;/&nbsp;犯罪 剧情</p>
                    <div class="star">
                        <span class="rating_num">9.7</span>
                    </div>
                    <p class="quote"><span class="inq">希望让人自由。</span></p>
                </div>
            </div>
        """)
        result = DoubanClient._parse_top250_item(item)

        assert result is not None
        assert result["douban_movie_id"] == "1292052"
        assert result["title"] == "肖申克的救赎"
        assert result["avg_rating"] == pytest.approx(9.7)
        assert result["year"] == 1994
        assert result["quote"] == "希望让人自由。"
        assert "美国" in result["regions"]
        assert "犯罪" in result["genres"] or "剧情" in result["genres"]

    def test_parse_second_top250_item(self):
        """Parse another Top250 entry to verify multi-item correctness."""
        item = make_top250_item("""
            <div class="pic">
                <a href="https://movie.douban.com/subject/1291546/">
                    <img alt="霸王别姬" />
                </a>
            </div>
            <div class="info">
                <div class="hd">
                    <span class="title">霸王别姬</span>
                </div>
                <div class="bd">
                    <p>导演: 陈凯歌&nbsp;&nbsp;&nbsp;主演: 张国荣
                    1993&nbsp;/&nbsp;中国大陆 香港&nbsp;/&nbsp;剧情 爱情</p>
                    <div class="star">
                        <span class="rating_num">9.6</span>
                    </div>
                    <p class="quote"><span class="inq">风华绝代。</span></p>
                </div>
            </div>
        """)
        result = DoubanClient._parse_top250_item(item)

        assert result is not None
        assert result["douban_movie_id"] == "1291546"
        assert result["title"] == "霸王别姬"
        assert result["avg_rating"] == pytest.approx(9.6)
        assert result["year"] == 1993
        assert result["quote"] == "风华绝代。"


class TestParseTop250ItemEdgeCases:
    """Edge cases for Top250 parsing."""

    def test_no_link_returns_none(self):
        """No subject link -> returns None."""
        item = make_top250_item("<div class='pic'>No link</div>")
        result = DoubanClient._parse_top250_item(item)
        assert result is None

    def test_missing_optional_fields(self):
        """Missing rating, quote, bd -> no crash, values are defaults."""
        item = make_top250_item("""
            <a href="https://movie.douban.com/subject/555/">
                <img alt="Minimal" />
            </a>
            <span class="title">Minimal Movie</span>
        """)
        result = DoubanClient._parse_top250_item(item)

        assert result is not None
        assert result["douban_movie_id"] == "555"
        assert result["title"] == "Minimal Movie"
        assert result["avg_rating"] is None
        assert result["quote"] == ""

    def test_invalid_rating_text(self):
        """Rating element contains non-numeric text -> avg_rating is None."""
        item = make_top250_item("""
            <a href="https://movie.douban.com/subject/666/">
                <img alt="BadRating" />
            </a>
            <span class="title">Bad Rating</span>
            <div class="bd">
                <p>2000 / 美国 / 动作</p>
                <span class="rating_num">N/A</span>
            </div>
        """)
        result = DoubanClient._parse_top250_item(item)
        assert result["avg_rating"] is None

    def test_no_bd_element(self):
        """No .bd element -> year, regions, genres remain defaults."""
        item = make_top250_item("""
            <a href="https://movie.douban.com/subject/777/">
                <img alt="NoBD" />
            </a>
            <span class="title">No BD</span>
        """)
        result = DoubanClient._parse_top250_item(item)
        assert result is not None
        assert result["year"] is None
        assert result["regions"] == ""
        assert result["genres"] == ""

    def test_returned_dict_keys(self):
        """The returned dict always has the expected keys."""
        item = make_top250_item("""
            <a href="https://movie.douban.com/subject/888/">
                <img alt="Keys" />
            </a>
            <span class="title">Keys Test</span>
        """)
        result = DoubanClient._parse_top250_item(item)
        expected_keys = {
            "douban_movie_id", "title", "year", "avg_rating",
            "genres", "regions", "quote",
        }
        assert set(result.keys()) == expected_keys


# ===========================================================================
# validate_uid
# ===========================================================================

class TestValidateUid:

    async def test_validate_uid_returns_uid_and_nickname(self, mock_client):
        """validate_uid extracts uid and nickname from profile page."""
        html = """
        <html><head><title>测试用户的豆瓣主页</title></head><body></body></html>
        """
        mock_client._request = AsyncMock(return_value=html)
        result = await mock_client.validate_uid("test_user")
        assert result is not None
        assert result["uid"] == "test_user"
        assert result["nickname"] == "测试用户"

    async def test_validate_uid_request_failure(self, mock_client):
        """validate_uid returns None when request fails."""
        mock_client._request = AsyncMock(return_value=None)
        result = await mock_client.validate_uid("bad_user")
        assert result is None

    async def test_validate_uid_empty_title(self, mock_client):
        """validate_uid handles page with no title element."""
        html = "<html><head></head><body></body></html>"
        mock_client._request = AsyncMock(return_value=html)
        result = await mock_client.validate_uid("test_user")
        assert result is not None
        assert result["uid"] == "test_user"
        assert result["nickname"] == ""


# ===========================================================================
# fetch_collection_page (no cookie parameter)
# ===========================================================================

class TestFetchCollectionPage:

    async def test_returns_empty_on_failure(self, mock_client):
        """fetch_collection_page returns ([], False) when request fails."""
        mock_client._request = AsyncMock(return_value=None)
        movies, has_more = await mock_client.fetch_collection_page("uid123", "collect")
        assert movies == []
        assert has_more is False

    async def test_no_cookie_param(self, mock_client):
        """fetch_collection_page should be callable without cookie."""
        import inspect
        sig = inspect.signature(mock_client.fetch_collection_page)
        params = list(sig.parameters.keys())
        assert "cookie" not in params


# ===========================================================================
# fetch_all_collections (no cookie parameter)
# ===========================================================================

class TestFetchAllCollections:

    async def test_returns_three_status_keys(self, mock_client):
        """fetch_all_collections returns dict with wish, do, collect keys."""
        mock_client.fetch_collection_page = AsyncMock(return_value=([], False))
        result = await mock_client.fetch_all_collections("uid123")
        assert "wish" in result
        assert "do" in result
        assert "collect" in result

    async def test_no_cookie_param(self, mock_client):
        """fetch_all_collections should be callable without cookie."""
        import inspect
        sig = inspect.signature(mock_client.fetch_all_collections)
        params = list(sig.parameters.keys())
        assert "cookie" not in params
