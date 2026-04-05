import asyncio
import random
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from astrbot.api import logger

# 用户评分星级 → 数值的映射
_RATING_CLASS_MAP = {
    "rating1-t": 1.0,
    "rating2-t": 2.0,
    "rating3-t": 3.0,
    "rating4-t": 4.0,
    "rating5-t": 5.0,
}

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

_BASE_HEADERS = {
    "User-Agent": _DEFAULT_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class DoubanClient:
    """豆瓣页面抓取与解析客户端。"""

    def __init__(
        self,
        interval_min: float = 1.0,
        interval_max: float = 3.0,
        max_retries: int = 3,
    ):
        self._interval_min = interval_min
        self._interval_max = interval_max
        self._max_retries = max_retries

    # ── 基础请求 ────────────────────────────────────────────

    async def _request(
        self, url: str, max_retries: int | None = None
    ) -> Optional[str]:
        retries = max_retries if max_retries is not None else self._max_retries

        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(
                    headers=_BASE_HEADERS, follow_redirects=True, timeout=15.0
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

    # ── UID 验证 ─────────────────────────────────────────

    async def validate_uid(self, douban_uid: str) -> Optional[dict]:
        """验证豆瓣主页 ID 是否有效，返回 {uid, nickname}。"""
        html = await self._request(f"https://www.douban.com/people/{douban_uid}/")
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")

        # 提取昵称
        nickname = ""
        title_elem = soup.select_one("title")
        if title_elem:
            text = title_elem.get_text(strip=True)
            # 页面标题通常是 "昵称的豆瓣主页" 或类似格式
            nickname = re.sub(r"的豆瓣.*$", "", text).strip()

        return {"uid": douban_uid, "nickname": nickname}

    # ── 片单抓取 ────────────────────────────────────────────

    async def fetch_collection_page(
        self, uid: str, status: str, start: int = 0
    ) -> tuple[list[dict], bool]:
        """抓取一页片单，返回 (movies, has_more)。"""
        url = (
            f"https://movie.douban.com/people/{uid}/{status}"
            f"?start={start}&sort=time&rating=all&filter=all&mode=grid"
        )
        html = await self._request(url)
        if not html:
            return [], False

        soup = BeautifulSoup(html, "html.parser")
        items = soup.select(".article .grid-view .item") or soup.select(".item")

        movies = []
        for item in items:
            movie = self._parse_collection_item(item, status)
            if movie:
                movies.append(movie)

        has_more = soup.select_one("a.next") is not None
        return movies, has_more

    @staticmethod
    def _parse_collection_item(item, status: str) -> Optional[dict]:
        try:
            link_elem = item.select_one("a[href*='/subject/']")
            if not link_elem:
                return None

            href = link_elem.get("href", "")
            id_match = re.search(r"/subject/(\d+)/", href)
            if not id_match:
                return None

            movie_id = id_match.group(1)

            # 标题
            title = link_elem.get("title", "") or link_elem.get_text(strip=True)
            if not title:
                t = item.select_one(".title a")
                title = t.get_text(strip=True) if t else ""

            # 用户评分
            user_rating: float | None = None
            for cls, val in _RATING_CLASS_MAP.items():
                if item.select_one(f"[class*='{cls}']"):
                    user_rating = val
                    break

            # 标记日期
            date_elem = item.select_one(".date")
            marked_at = date_elem.get_text(strip=True) if date_elem else None

            # 用户标签
            tags_elem = item.select_one(".tags")
            tags = tags_elem.get_text(strip=True) if tags_elem else ""
            tags = re.sub(r"^标签:\s*", "", tags)

            return {
                "douban_movie_id": movie_id,
                "title": title,
                "user_rating": user_rating,
                "genres": tags,
                "status": status,
                "marked_at": marked_at,
            }
        except Exception as exc:
            logger.warning(f"解析片单条目失败: {exc}")
            return None

    async def fetch_all_collections(
        self,
        uid: str,
        last_sync_time: Optional[str] = None,
    ) -> dict[str, list[dict]]:
        """抓取全部片单（想看/在看/看过），支持增量。"""
        results: dict[str, list[dict]] = {"wish": [], "do": [], "collect": []}

        for status in ("wish", "do", "collect"):
            start = 0
            while True:
                await self._delay()
                movies, has_more = await self.fetch_collection_page(
                    uid, status, start
                )
                if not movies:
                    break

                if last_sync_time:
                    new_movies = []
                    for m in movies:
                        if m.get("marked_at") and m["marked_at"] > last_sync_time:
                            new_movies.append(m)
                        else:
                            has_more = False
                            break
                    movies = new_movies

                results[status].extend(movies)

                if not has_more:
                    break
                start += 15  # grid 模式每页 15 条

        return results

    # ── 电影详情 ────────────────────────────────────────────

    async def fetch_movie_detail(self, movie_id: str) -> Optional[dict]:
        """抓取电影详情页，提取类型/地区/年份。"""
        await self._delay()
        html = await self._request(f"https://movie.douban.com/subject/{movie_id}/")
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        try:
            title = ""
            t = soup.select_one("span[property='v:itemreviewed']")
            if t:
                title = t.get_text(strip=True)

            year: int | None = None
            y = soup.select_one(".year")
            if y:
                m = re.search(r"(\d{4})", y.get_text())
                if m:
                    year = int(m.group(1))

            avg_rating: float | None = None
            r = soup.select_one("strong.rating_num") or soup.select_one(
                "[property='v:average']"
            )
            if r:
                try:
                    avg_rating = float(r.get_text(strip=True))
                except ValueError:
                    pass

            genres = [
                g.get_text(strip=True) for g in soup.select("span[property='v:genre']")
            ]

            regions: list[str] = []
            info = soup.select_one("#info")
            if info:
                rm = re.search(r"制片国家/地区:\s*(.+?)(?:\n|$)", info.get_text())
                if rm:
                    regions = [
                        s.strip()
                        for s in re.split(r"[/,，、]", rm.group(1).strip())
                        if s.strip()
                    ]

            return {
                "douban_movie_id": movie_id,
                "title": title,
                "year": year,
                "avg_rating": avg_rating,
                "genres": ",".join(genres),
                "regions": ",".join(regions),
            }
        except Exception as exc:
            logger.warning(f"解析电影详情 {movie_id} 失败: {exc}")
            return None

    # ── Top 250 ─────────────────────────────────────────────

    async def fetch_top250(self) -> list[dict]:
        """抓取豆瓣 Top 250 列表。"""
        movies: list[dict] = []

        for start in range(0, 250, 25):
            await self._delay()
            html = await self._request(
                f"https://movie.douban.com/top250?start={start}&filter="
            )
            if not html:
                break

            soup = BeautifulSoup(html, "html.parser")
            for item in soup.select("ol.grid_view > li"):
                try:
                    movie = self._parse_top250_item(item)
                    if movie:
                        movies.append(movie)
                except Exception as exc:
                    logger.warning(f"解析 Top250 条目失败: {exc}")

        logger.info(f"已抓取 {len(movies)} 部 Top 250 影片")
        return movies

    @staticmethod
    def _parse_top250_item(item) -> Optional[dict]:
        link = item.select_one("a[href*='/subject/']")
        if not link:
            return None

        href = link.get("href", "")
        id_match = re.search(r"/subject/(\d+)/", href)
        if not id_match:
            return None
        movie_id = id_match.group(1)

        # 标题
        title = ""
        t = item.select_one(".title")
        if t:
            title = t.get_text(strip=True)

        # 豆瓣评分
        rating: float | None = None
        r = item.select_one(".rating_num")
        if r:
            try:
                rating = float(r.get_text(strip=True))
            except ValueError:
                pass

        # 一句话评价
        quote = ""
        q = item.select_one(".inq")
        if q:
            quote = q.get_text(strip=True)

        # 从简介行解析 年份 / 地区 / 类型
        year: int | None = None
        regions = ""
        genres = ""

        bd = item.select_one(".bd")
        if bd:
            p = bd.select_one("p")
            if p:
                text = p.get_text()
                ym = re.search(r"(\d{4})", text)
                if ym:
                    year = int(ym.group(1))

                lines = text.strip().split("\n")
                if len(lines) >= 2:
                    parts = [s.strip() for s in lines[-1].split("/")]
                    if len(parts) >= 2:
                        # 地区可能在中间多个部分（如 "美国 / 英国"）
                        region_parts = parts[1:-1]
                        regions = ",".join(r.strip() for r in region_parts if r.strip())
                    if len(parts) >= 3:
                        # genres 始终在最后一个部分
                        genres = re.sub(r"\s+", ",", parts[-1].strip())

        return {
            "douban_movie_id": movie_id,
            "title": title,
            "year": year,
            "avg_rating": rating,
            "genres": genres,
            "regions": regions,
            "quote": quote,
        }
