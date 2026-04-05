from __future__ import annotations

import random
import re
import uuid
from typing import Optional

from astrbot.api import logger

from ..db.database import Database
from ..service.douban_client import DoubanClient


class Recommender:
    """基于豆瓣搜索 + 候选池的电影推荐。"""

    def __init__(
        self,
        db: Database,
        client: DoubanClient,
        recommend_count: int = 5,
        candidate_pool_size: int = 20,
        min_rating: float = 7.0,
    ):
        self.db = db
        self.client = client
        self._recommend_count = recommend_count
        self._candidate_pool_size = candidate_pool_size
        self._min_rating = min_rating

    def _build_search_keyword(
        self,
        user_input: str,
        genre_prefs: list[str],
        region_prefs: list[str],
    ) -> str:
        """合成搜索关键词：用户输入 + 画像偏好。"""
        parts = []

        if user_input.strip():
            parts.append(user_input.strip())

        # 取用户最偏好的类型作为补充（最多 2 个）
        for genre in genre_prefs[:2]:
            if genre not in user_input:
                parts.append(genre)

        return " ".join(parts) if parts else "电影"

    def _build_llm_reasons_prompt(
        self,
        results: list[dict],
        genre_prefs: list[str],
        region_prefs: list[str],
    ) -> str:
        """构造 LLM prompt 用于生成推荐理由。"""
        movie_lines = []
        for i, r in enumerate(results, 1):
            rating_str = f"豆瓣{r.get('rating')}分" if r.get("rating") else ""
            year_str = f"({r.get('year')})" if r.get("year") else ""
            subtitle = r.get("card_subtitle", "")
            movie_lines.append(
                f"{i}. 《{r['title']}》{year_str} {rating_str} {subtitle}"
            )

        genre_str = "、".join(genre_prefs[:5]) if genre_prefs else "未知"
        region_str = "、".join(region_prefs[:3]) if region_prefs else "未知"

        return (
            "你是一位专业影评人。请根据用户的观影偏好，为以下推荐影片各写一句简短的推荐理由"
            "（每句不超过30字，说明为什么适合该用户）。\n\n"
            f"用户偏好类型：{genre_str}\n"
            f"用户偏好地区：{region_str}\n\n"
            "推荐影片：\n" + "\n".join(movie_lines) + "\n\n"
            "请按编号逐条输出推荐理由，格式为：\n"
            "1. 推荐理由\n2. 推荐理由\n..."
        )

    def _parse_llm_reasons(self, text: str, count: int) -> list[str]:
        """从 LLM 返回文本中按编号解析推荐理由。"""
        reasons = []
        for i in range(1, count + 1):
            pattern = rf"{i}[.、．]\s*(.+)"
            match = re.search(pattern, text)
            if match:
                reasons.append(match.group(1).strip())
        return reasons

    async def search_and_recommend(
        self,
        astrbot_uid: str,
        user_description: str = "",
        persona_text: str = "",
        context=None,
        provider_id: str = "",
    ) -> tuple[list[dict], str]:
        """搜索并推荐电影。

        Returns:
            (results, session_id) - 推荐结果列表和会话 ID
        """
        # 获取用户画像
        profile = await self.db.get_profile(astrbot_uid)
        if not profile:
            return [], ""

        genre_prefs = profile.get("genre_prefs") or []
        region_prefs = profile.get("region_prefs") or []

        # 合成搜索关键词
        keyword = self._build_search_keyword(user_description, genre_prefs, region_prefs)
        logger.info(f"用户 {astrbot_uid} 搜索关键词: {keyword}")

        # 搜索
        search_results = await self.client.search_movies(keyword)
        if not search_results:
            return [], ""

        # 获取用户已看过的电影 ID
        seen_ids = await self.db.get_seen_movie_ids(astrbot_uid)

        # 过滤 + 排序
        candidates = []
        for movie in search_results:
            mid = movie.get("id", "")
            if not mid:
                continue
            if mid in seen_ids:
                continue
            rating = movie.get("rating")
            if rating is not None and rating < self._min_rating:
                continue
            candidates.append(movie)

        # 按评分排序（高分在前）
        candidates.sort(
            key=lambda x: x.get("rating") or 0, reverse=True
        )

        # 取候选池
        pool = candidates[: self._candidate_pool_size]
        if not pool:
            return [], ""

        # 随机抽取推荐数量
        count = min(self._recommend_count, len(pool))
        selected = random.sample(pool, count)

        # 创建会话
        session_id = str(uuid.uuid4())
        candidate_ids = [m["id"] for m in pool]
        shown_ids = [m["id"] for m in selected]

        await self.db.create_rec_session(
            session_id, astrbot_uid, keyword, candidate_ids
        )
        await self.db.update_rec_session_shown(session_id, shown_ids)

        # 生成推荐理由
        await self._generate_reasons(
            selected, genre_prefs, region_prefs,
            persona_text, context, provider_id,
        )

        return selected, session_id

    async def re_recommend(
        self,
        session_id: str,
        astrbot_uid: str,
        persona_text: str = "",
        context=None,
        provider_id: str = "",
    ) -> Optional[tuple[list[dict], str]]:
        """用户反馈"看过了"后重新推荐。

        Returns:
            (results, session_id) 或 None（候选池耗尽）
        """
        session = await self.db.get_rec_session(session_id)
        if not session:
            return None

        shown_ids: list[str] = session.get("shown_ids") or []
        candidate_ids: list[str] = session.get("candidate_ids") or []

        # 将已展示的电影写入 user_seen_movies
        # 需要从搜索结果中获取标题（这里简化，只记录 ID）
        seen_movies = [{"douban_movie_id": sid, "title": ""} for sid in shown_ids]
        await self.db.add_seen_movies(astrbot_uid, seen_movies)

        # 从候选池中排除已展示的
        remaining = [mid for mid in candidate_ids if mid not in set(shown_ids)]

        if not remaining:
            return None

        # 随机抽取
        count = min(self._recommend_count, len(remaining))
        new_selected_ids = random.sample(remaining, count)

        # 需要获取这些电影的信息（尝试从搜索结果重新获取）
        # 由于我们没有缓存搜索结果详情，这里用 ID 构造简化结果
        results = []
        for mid in new_selected_ids:
            results.append({
                "id": mid,
                "title": f"电影 {mid}",
                "rating": None,
                "year": None,
                "card_subtitle": "",
            })

        # 尝试获取详情补充信息
        for r in results:
            try:
                detail = await self.client.fetch_movie_detail(r["id"])
                if detail:
                    r["title"] = detail.get("title", r["title"])
                    r["rating"] = detail.get("rating")
                    r["year"] = detail.get("year")
                    r["card_subtitle"] = detail.get("card_subtitle", "")
            except Exception:
                pass

        # 更新会话
        new_shown_ids = shown_ids + new_selected_ids
        await self.db.update_rec_session_shown(session_id, new_shown_ids)

        # 获取用户偏好
        profile = await self.db.get_profile(astrbot_uid)
        genre_prefs = profile.get("genre_prefs") or [] if profile else []
        region_prefs = profile.get("region_prefs") or [] if profile else []

        # 生成推荐理由
        await self._generate_reasons(
            results, genre_prefs, region_prefs,
            persona_text, context, provider_id,
        )

        return results, session_id

    async def _generate_reasons(
        self,
        results: list[dict],
        genre_prefs: list[str],
        region_prefs: list[str],
        persona_text: str,
        context=None,
        provider_id: str = "",
    ):
        """为推荐结果生成理由（LLM 或模板回退）。"""
        if not results:
            return

        # LLM 生成推荐理由
        if context and provider_id:
            try:
                prompt = self._build_llm_reasons_prompt(
                    results, genre_prefs, region_prefs
                )
                system_prompt = persona_text if persona_text else None

                llm_resp = await context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    system_prompt=system_prompt,
                )
                if llm_resp and llm_resp.completion_text:
                    reasons = self._parse_llm_reasons(
                        llm_resp.completion_text, len(results)
                    )
                    if len(reasons) == len(results):
                        for r, reason in zip(results, reasons):
                            r["reason"] = reason
                        return
            except Exception as exc:
                logger.warning(f"LLM 推荐理由生成失败: {exc}")

        # 模板回退
        for r in results:
            r["reason"] = self._template_reason(r, genre_prefs)

    @staticmethod
    def _template_reason(movie: dict, genre_prefs: list[str]) -> str:
        """模板推荐理由。"""
        parts = []
        rating = movie.get("rating")
        if rating and rating >= 9.0:
            parts.append(f"豆瓣评分高达 {rating}")
        elif rating and rating >= 8.0:
            parts.append(f"豆瓣评分 {rating}，口碑佳作")

        subtitle = movie.get("card_subtitle", "")
        for genre in genre_prefs[:3]:
            if genre in subtitle:
                parts.append(f"匹配你喜欢的{genre}类型")
                break

        return "，".join(parts) if parts else "高分佳作推荐"
