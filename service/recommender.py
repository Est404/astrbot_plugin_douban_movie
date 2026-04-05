from __future__ import annotations

from astrbot.api import logger

from ..db.database import Database
from ..service.douban_client import DoubanClient


class Recommender:
    """基于用户画像从豆瓣 Top 250 筛选推荐。"""

    def __init__(
        self,
        db: Database,
        client: DoubanClient,
        recommend_count: int = 5,
        min_rating: float = 8.0,
    ):
        self.db = db
        self.client = client
        self._recommend_count = recommend_count
        self._min_rating = min_rating
        self._top250_cache: list[dict] | None = None

    async def _ensure_top250(self) -> list[dict]:
        if self._top250_cache is None:
            self._top250_cache = await self.client.fetch_top250()
        return self._top250_cache

    def _build_llm_prompt(self, user_prefs: dict, results: list[dict]) -> str:
        """构造 LLM prompt 用于生成推荐理由。"""
        genre_lines = [f"- {g}：{c}部" for g, c in user_prefs["top_genres"]]
        region_lines = [f"- {r}" for r in user_prefs["top_regions"]]

        movie_lines = []
        for i, r in enumerate(results, 1):
            movie_lines.append(
                f"{i}. 《{r['title']}》({r.get('year', '?')}) "
                f"豆瓣{r.get('avg_rating', '?')}分 "
                f"类型：{r.get('genres', '未知')} "
                f"地区：{r.get('regions', '未知')}"
            )

        return (
            "你是一位专业影评人。请根据用户的观影偏好，为以下推荐影片各写一句简短的推荐理由"
            "（每句不超过30字，说明为什么适合该用户）。\n\n"
            "用户偏好类型：\n" + "\n".join(genre_lines) + "\n\n"
            "用户偏好地区：" + "、".join(region_lines) + "\n\n"
            "推荐影片：\n" + "\n".join(movie_lines) + "\n\n"
            "请按编号逐条输出推荐理由，格式为：\n"
            "1. 推荐理由\n2. 推荐理由\n..."
        )

    def _parse_llm_reasons(self, text: str, count: int) -> list[str]:
        """从 LLM 返回文本中按编号解析推荐理由。"""
        import re

        reasons = []
        for i in range(1, count + 1):
            # 匹配 "1. xxx" 或 "1、xxx" 等格式
            pattern = rf"{i}[.、．]\s*(.+)"
            match = re.search(pattern, text)
            if match:
                reasons.append(match.group(1).strip())
        return reasons

    def _generate_template_reasons(self, results: list[dict]) -> None:
        """用模板逻辑生成推荐理由（LLM 不可用时的回退）。"""
        for r in results:
            reasons: list[str] = []
            if r.get("matched_genres"):
                reasons.append(f"匹配你喜欢的{'/'.join(r['matched_genres'])}类型")
            if r.get("avg_rating") and r["avg_rating"] >= 9.0:
                reasons.append(f"豆瓣评分高达{r['avg_rating']}")
            if r.get("quote"):
                reasons.append(f"「{r['quote']}」")
            r["reason"] = "，".join(reasons) if reasons else "高分佳作推荐"

    async def recommend(
        self,
        astrbot_uid: str,
        genre_filter: str = "",
        context=None,
        provider_id: str = "",
    ) -> list[dict]:
        bind = await self.db.get_bind(astrbot_uid)
        if not bind:
            return []

        watched_ids = await self.db.get_all_collected_movie_ids(astrbot_uid)

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
            if movie["douban_movie_id"] in watched_ids:
                continue

            if not movie.get("avg_rating") or movie["avg_rating"] < self._min_rating:
                continue

            movie_genres: set[str] = set()
            if movie.get("genres"):
                movie_genres = {g.strip() for g in movie["genres"].split(",")}

            if genre_filter and genre_filter not in movie_genres:
                continue

            matched = top_genres & movie_genres
            score = len(matched) * 10 + (movie.get("avg_rating") or 0)

            movie_regions_str = movie.get("regions", "")
            if movie_regions_str:
                for ur in user_regions:
                    if ur in movie_regions_str:
                        score += 5
                        break

            candidates.append({**movie, "score": score, "matched_genres": matched})

        candidates.sort(key=lambda x: x["score"], reverse=True)
        results = candidates[: self._recommend_count]

        if not results:
            return results

        # 尝试 LLM 生成推荐理由
        if context and provider_id:
            try:
                user_prefs = {
                    "top_genres": sorted(
                        genre_prefs.items(), key=lambda x: x[1], reverse=True
                    )[:5],
                    "top_regions": list(user_regions),
                }
                prompt = self._build_llm_prompt(user_prefs, results)
                llm_resp = await context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                )
                if llm_resp and llm_resp.completion_text:
                    llm_reasons = self._parse_llm_reasons(
                        llm_resp.completion_text, len(results)
                    )
                    if len(llm_reasons) == len(results):
                        for r, reason in zip(results, llm_reasons):
                            r["reason"] = reason
                        logger.info(f"用户 {astrbot_uid} 推荐理由由 LLM 生成")
                        return results
            except Exception as exc:
                logger.warning(f"LLM 推荐理由生成失败，回退到模板: {exc}")

        # 回退：模板理由
        self._generate_template_reasons(results)

        logger.info(
            f"为用户 {astrbot_uid} 推荐 {len(results)} 部影片"
            + (f"（筛选：{genre_filter}）" if genre_filter else "")
        )
        return results
