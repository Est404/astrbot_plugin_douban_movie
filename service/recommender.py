from __future__ import annotations

from astrbot.api import logger

from db.database import Database
from service.douban_client import DoubanClient


class Recommender:
    """基于用户画像从豆瓣 Top 250 筛选推荐。"""

    def __init__(self, db: Database, client: DoubanClient):
        self.db = db
        self.client = client
        self._top250_cache: list[dict] | None = None

    async def _ensure_top250(self) -> list[dict]:
        if self._top250_cache is None:
            self._top250_cache = await self.client.fetch_top250()
        return self._top250_cache

    async def recommend(self, astrbot_uid: str, genre_filter: str = "") -> list[dict]:
        bind = await self.db.get_bind(astrbot_uid)
        if not bind:
            return []

        # 已看过 / 想看的影片 ID 集合
        watched_ids = await self.db.get_all_collected_movie_ids(astrbot_uid)

        # 用户类型偏好
        movies = await self.db.get_movies_by_status(astrbot_uid, "collect")
        genre_prefs: dict[str, int] = {}
        user_regions: set[str] = set()
        for m in movies:
            if m.get("genres"):
                for g in m["genres"].split(","):
                    g = g.strip()
                    if g:
                        genre_prefs[g] = genre_prefs.get(g, 0) + 1
            if m.get("regions"):
                for r in m["regions"].split(","):
                    r = r.strip()
                    if r:
                        user_regions.add(r)

        top_genres = {
            g
            for g, _ in sorted(genre_prefs.items(), key=lambda x: x[1], reverse=True)[
                :5
            ]
        }

        top250 = await self._ensure_top250()

        candidates: list[dict] = []
        for movie in top250:
            # 排除已标记的
            if movie["douban_movie_id"] in watched_ids:
                continue

            # 评分门槛
            if not movie.get("avg_rating") or movie["avg_rating"] < 8.0:
                continue

            # 解析影片类型集合
            movie_genres: set[str] = set()
            if movie.get("genres"):
                movie_genres = {g.strip() for g in movie["genres"].split(",")}

            # 类型筛选
            if genre_filter and genre_filter not in movie_genres:
                continue

            # ── 打分 ──
            matched = top_genres & movie_genres
            score = len(matched) * 10 + (movie.get("avg_rating") or 0)

            # 地区加分
            movie_regions_str = movie.get("regions", "")
            if movie_regions_str:
                for ur in user_regions:
                    if ur in movie_regions_str:
                        score += 5
                        break

            candidates.append({**movie, "score": score, "matched_genres": matched})

        candidates.sort(key=lambda x: x["score"], reverse=True)
        results = candidates[:5]

        # 生成推荐理由
        for r in results:
            reasons: list[str] = []
            if r["matched_genres"]:
                reasons.append(f"匹配你喜欢的{'/'.join(r['matched_genres'])}类型")
            if r.get("avg_rating") and r["avg_rating"] >= 9.0:
                reasons.append(f"豆瓣评分高达{r['avg_rating']}")
            if r.get("quote"):
                reasons.append(f"「{r['quote']}」")
            r["reason"] = "，".join(reasons) if reasons else "高分佳作推荐"

        logger.info(
            f"为用户 {astrbot_uid} 推荐 {len(results)} 部影片"
            + (f"（筛选：{genre_filter}）" if genre_filter else "")
        )
        return results
