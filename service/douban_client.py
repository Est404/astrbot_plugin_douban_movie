import asyncio
import random
import re
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup
from astrbot.api import logger

_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.5 Mobile/15E148 Safari/604.1"
)

_REXXAR_HEADERS = {
    "User-Agent": _MOBILE_UA,
    "Referer": "https://m.douban.com/",
    "Accept": "application/json",
}

_SEARCH_HEADERS = {
    "User-Agent": _MOBILE_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class DoubanClient:
    """豆瓣 Rexxar API + 移动端搜索客户端。"""

    def __init__(
        self,
        interval_min: float = 1.0,
        interval_max: float = 3.0,
        max_retries: int = 3,
        cookie: str = "",
    ):
        self._interval_min = interval_min
        self._interval_max = interval_max
        self._max_retries = max_retries
        self._cookie = cookie
        self.cookie_expired = False

    # ── 基础请求 ────────────────────────────────────────────

    async def _request_json(
        self, url: str, headers: dict | None = None
    ) -> Optional[dict]:
        """GET 请求返回 JSON，携带 Cookie。检测 Cookie 失效。"""
        retries = self._max_retries

        for attempt in range(retries):
            try:
                req_headers = {**(headers or _REXXAR_HEADERS)}
                if self._cookie:
                    req_headers["Cookie"] = self._cookie

                async with httpx.AsyncClient(
                    headers=req_headers, follow_redirects=False, timeout=15.0
                ) as client:
                    resp = await client.get(url)

                    if resp.status_code in (301, 302):
                        location = resp.headers.get("location", "")
                        if "login" in location or "passport" in location:
                            self.cookie_expired = True
                            logger.warning("豆瓣 Cookie 已失效（重定向到登录页）")
                            return None

                    if resp.status_code == 401:
                        self.cookie_expired = True
                        logger.warning("豆瓣 Cookie 已失效（401）")
                        return None

                    if resp.status_code in (403, 429):
                        wait = random.uniform(2, 5) * (attempt + 1)
                        logger.warning(
                            f"豆瓣反爬 {resp.status_code}，{wait:.1f}s 后重试 "
                            f"({attempt + 1}/{retries})"
                        )
                        await asyncio.sleep(wait)
                        continue

                    if resp.status_code == 200:
                        try:
                            return resp.json()
                        except Exception:
                            logger.warning(f"响应非 JSON: {url}")
                            return None

                    logger.warning(f"请求 {url} 返回 {resp.status_code}")
                    return None
            except httpx.RequestError as exc:
                logger.warning(f"请求 {url} 异常: {exc}")
                if attempt < retries - 1:
                    await asyncio.sleep(random.uniform(1, 3))

        return None

    async def _request_html(
        self, url: str, headers: dict | None = None
    ) -> Optional[str]:
        """GET 请求返回 HTML 文本。"""
        retries = self._max_retries

        for attempt in range(retries):
            try:
                req_headers = {**(headers or _SEARCH_HEADERS)}
                if self._cookie:
                    req_headers["Cookie"] = self._cookie

                async with httpx.AsyncClient(
                    headers=req_headers, follow_redirects=True, timeout=15.0
                ) as client:
                    resp = await client.get(url)

                    if resp.status_code in (403, 429):
                        wait = random.uniform(2, 5) * (attempt + 1)
                        logger.warning(
                            f"豆瓣反爬 {resp.status_code}，{wait:.1f}s 后重试 "
                            f"({attempt + 1}/{retries})"
                        )
                        await asyncio.sleep(wait)
                        continue

                    if resp.status_code == 200:
                        return resp.text

                    logger.warning(f"请求 {url} 返回 {resp.status_code}")
                    return None
            except httpx.RequestError as exc:
                logger.warning(f"请求 {url} 异常: {exc}")
                if attempt < retries - 1:
                    await asyncio.sleep(random.uniform(1, 3))

        return None

    async def _delay(self):
        await asyncio.sleep(random.uniform(self._interval_min, self._interval_max))

    # ── 数字 ID 提取 ───────────────────────────────────────

    @staticmethod
    def extract_numeric_id(raw_input: str) -> Optional[str]:
        """从纯数字或豆瓣主页 URL 中提取数字 ID。

        支持格式：
        - 纯数字：159896279
        - 完整 URL：https://www.douban.com/people/159896279/
        - 短格式：douban.com/people/159896279
        """
        raw_input = raw_input.strip()
        if not raw_input:
            return None

        # 纯数字
        if raw_input.isdigit():
            return raw_input

        # 从 URL 提取
        m = re.search(r"/people/(\d+)", raw_input)
        if m:
            return m.group(1)

        return None

    # ── 用户验证 ─────────────────────────────────────────

    async def validate_douban_uid(self, douban_uid: str) -> Optional[dict]:
        """验证豆瓣数字 ID 是否有效。返回 {uid, nickname, total_marked}。"""
        stats = await self.fetch_collection_stats(douban_uid)
        if not stats:
            return None

        viewer = stats.get("viewer") or {}
        nickname = viewer.get("name", "")

        total_marked = 0
        for year_data in stats.get("years", []):
            total_marked += year_data.get("value", 0)

        return {
            "uid": douban_uid,
            "nickname": nickname,
            "total_marked": total_marked,
        }

    # ── 观影统计 API ──────────────────────────────────────

    async def fetch_collection_stats(self, douban_uid: str) -> Optional[dict]:
        """获取用户观影统计数据。

        API: GET https://m.douban.com/rexxar/api/v2/user/{uid}/collection_stats
        """
        url = (
            f"https://m.douban.com/rexxar/api/v2/user/{douban_uid}/collection_stats"
        )
        return await self._request_json(url)

    # ── 电影搜索 ──────────────────────────────────────────

    async def search_movies(
        self, keyword: str, max_results: int = 40
    ) -> list[dict]:
        """搜索豆瓣电影，返回 [{id, title, rating, year, card_subtitle}]。

        使用移动端搜索页面，解析 HTML。
        """
        encoded_kw = quote_plus(keyword)
        url = f"https://m.douban.com/search/?query={encoded_kw}&type=movie"

        await self._delay()
        html = await self._request_html(url)
        if not html:
            return []

        return self._parse_search_results(html, max_results)

    @staticmethod
    def _parse_search_results(html: str, max_results: int = 40) -> list[dict]:
        """解析移动端搜索结果 HTML。"""
        soup = BeautifulSoup(html, "html.parser")
        results = []

        # 移动端搜索结果通常在 .search-results 或 .result-list 中
        items = soup.select(".search-results .result-item") or \
                soup.select(".result-list .result") or \
                soup.select(".subject-catalog .subject") or \
                soup.select(".search-result")

        if not items:
            # 尝试更宽泛的选择器
            items = soup.select("[data-id]")

        for item in items[:max_results]:
            try:
                movie = DoubanClient._parse_search_item(item)
                if movie:
                    results.append(movie)
            except Exception as exc:
                logger.debug(f"解析搜索条目失败: {exc}")

        return results

    @staticmethod
    def _parse_search_item(item) -> Optional[dict]:
        """解析单个搜索结果条目。"""
        # 提取电影 ID
        movie_id = None

        # data-id 属性
        movie_id = item.get("data-id", "")
        if not movie_id:
            # 从链接提取
            link = item.select_one("a[href*='/subject/']")
            if link:
                href = link.get("href", "")
                m = re.search(r"/subject/(\d+)", href)
                if m:
                    movie_id = m.group(1)

        if not movie_id:
            return None

        # 标题
        title = ""
        title_elem = item.select_one(".title") or item.select_one("h3") or item.select_one("a")
        if title_elem:
            title = title_elem.get_text(strip=True)

        # 评分
        rating = None
        rating_elem = item.select_one(".rating_nums") or item.select_one("[class*='rating']")
        if rating_elem:
            try:
                rating = float(rating_elem.get_text(strip=True))
            except (ValueError, TypeError):
                pass

        # 年份 / 信息行
        year = None
        card_subtitle = ""
        info_elem = item.select_one(".subject-cast") or item.select_one(".meta") or item.select_one(".info")
        if info_elem:
            card_subtitle = info_elem.get_text(strip=True)
            ym = re.search(r"(\d{4})", card_subtitle)
            if ym:
                year = int(ym.group(1))

        return {
            "id": str(movie_id),
            "title": title,
            "rating": rating,
            "year": year,
            "card_subtitle": card_subtitle,
        }

    # ── 电影详情（Rexxar API） ────────────────────────────

    async def fetch_movie_detail(self, movie_id: str) -> Optional[dict]:
        """通过 Rexxar API 获取电影详情。"""
        await self._delay()
        url = f"https://m.douban.com/rexxar/api/v2/movie/{movie_id}"
        data = await self._request_json(url)
        if not data:
            return None

        genres = [g.get("name", "") for g in data.get("genres", []) if g.get("name")]

        return {
            "id": str(movie_id),
            "title": data.get("title", ""),
            "rating": data.get("rating", {}).get("value"),
            "year": data.get("year"),
            "genres": genres,
            "card_subtitle": data.get("card_subtitle", ""),
        }
