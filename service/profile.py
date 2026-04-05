from __future__ import annotations

from typing import Optional

from astrbot.api import logger

from ..db.database import Database
from ..service.douban_client import DoubanClient


class ProfileGenerator:
    """基于豆瓣 collection_stats API 生成用户观影画像。"""

    def __init__(self, db: Database, client: DoubanClient):
        self.db = db
        self.client = client

    def _extract_prefs_from_stats(self, stats: dict) -> dict:
        """从 collection_stats API 响应中提取偏好数据。"""
        # 类型偏好 — 从 recent_subjects 的 genres 统计
        genre_counts: dict[str, int] = {}
        region_counts: dict[str, int] = {}
        decade_counts: dict[str, int] = {}

        for subj in stats.get("recent_subjects", []):
            # genres
            for g in subj.get("genres", []):
                name = g.get("name", "") if isinstance(g, dict) else str(g)
                if name:
                    genre_counts[name] = genre_counts.get(name, 0) + 1

            # 从 card_subtitle 提取地区和年代
            card = subj.get("card_subtitle", "")
            parts = [p.strip() for p in card.split(" / ")]

            year = subj.get("year")
            if year:
                decade = f"{(int(year) // 10) * 10}s"
                decade_counts[decade] = decade_counts.get(decade, 0) + 1

            # 地区（card_subtitle 中通常是 第二部分）
            if len(parts) >= 2:
                region = parts[1].strip()
                if region:
                    region_counts[region] = region_counts.get(region, 0) + 1

        # 排序取 Top
        top_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        top_regions = sorted(region_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        top_decades = sorted(decade_counts.items(), key=lambda x: x[1], reverse=True)

        # 总标记数
        total_marked = 0
        for year_data in stats.get("years", []):
            total_marked += year_data.get("value", 0)

        return {
            "total_marked": total_marked,
            "genre_prefs": top_genres,
            "region_prefs": top_regions,
            "decade_prefs": top_decades,
        }

    def _format_profile_from_stats(
        self,
        prefs: dict,
        nickname: str = "",
    ) -> str:
        """将统计数据格式化为纯文本画像（LLM 不可用时的回退）。"""
        total = prefs["total_marked"]
        name = nickname or "你"

        lines = [
            f"🎬 {name} 的观影画像",
            "",
            f"📊 观影量：{total} 部标记",
        ]

        genre_prefs = prefs.get("genre_prefs", [])
        if genre_prefs:
            genre_parts = [
                f"{g} ({c})" for g, c in genre_prefs[:5]
            ]
            lines.append(f"🎭 类型偏好：{' | '.join(genre_parts)}")

        region_prefs = prefs.get("region_prefs", [])
        if region_prefs:
            region_parts = [f"{r} ({c})" for r, c in region_prefs[:3]]
            lines.append(f"🌍 地区偏好：{' | '.join(region_parts)}")

        decade_prefs = prefs.get("decade_prefs", [])
        if decade_prefs:
            decade_parts = [f"{d} ({c})" for d, c in decade_prefs]
            lines.append(f"📅 年代偏好：{' | '.join(decade_parts)}")

        return "\n".join(lines)

    def _build_llm_prompt(self, prefs: dict, nickname: str = "") -> str:
        """构造 LLM prompt 用于画像生成。"""
        name = nickname or "该用户"

        genre_lines = [f"- {g}：{c}部" for g, c in prefs.get("genre_prefs", [])]
        region_lines = [f"- {r}：{c}部" for r, c in prefs.get("region_prefs", [])]
        decade_lines = [f"- {d}：{c}部" for d, c in prefs.get("decade_prefs", [])]

        return (
            f"请根据以下豆瓣用户「{name}」的观影统计数据，"
            "生成一段生动有趣的中文观影画像分析（200字以内）。\n\n"
            f"用户共标记 {prefs['total_marked']} 部影视。\n\n"
            "类型偏好：\n" + "\n".join(genre_lines) + "\n\n"
            "地区偏好：\n" + "\n".join(region_lines) + "\n\n"
            "年代偏好：\n" + "\n".join(decade_lines) + "\n\n"
            "请直接输出画像分析文本，不要加标题或额外格式。"
        )

    async def generate(
        self,
        astrbot_uid: str,
        persona_text: str = "",
        context=None,
        provider_id: str = "",
    ) -> str:
        """生成用户观影画像。

        Args:
            astrbot_uid: AstrBot 用户 ID
            persona_text: 人格提示词（注入到 LLM system prompt）
            context: AstrBot Context（用于调用 llm_generate）
            provider_id: LLM provider ID

        Returns:
            格式化的画像文本
        """
        # 检查缓存
        cached = await self.db.get_profile(astrbot_uid)
        if cached and cached.get("profile_text"):
            # 检查是否新鲜（24h 内）
            from datetime import datetime, timedelta, timezone
            updated_str = cached.get("updated_at")
            if updated_str:
                try:
                    updated = datetime.fromisoformat(updated_str)
                    if datetime.now(timezone.utc) - updated.replace(tzinfo=timezone.utc) < timedelta(hours=24):
                        logger.info(f"用户 {astrbot_uid} 使用缓存的画像数据")
                        return cached["profile_text"]
                except (ValueError, TypeError):
                    pass

        # 获取绑定信息
        bind_info = await self.db.get_bind(astrbot_uid)
        if not bind_info:
            return "❌ 请先使用 /movie bind 绑定豆瓣账号。"

        douban_uid = bind_info["douban_uid"]
        nickname = bind_info.get("nickname") or ""

        # 调用 API
        stats = await self.client.fetch_collection_stats(douban_uid)
        if not stats:
            if self.client.cookie_expired:
                return "❌ 豆瓣 Cookie 已失效，请联系管理员更新。"
            return "❌ 获取观影数据失败，请稍后重试。"

        # 提取偏好
        prefs = self._extract_prefs_from_stats(stats)

        # 保存偏好数据到 DB（不管 LLM 是否成功都保存）
        genre_list = [g for g, _ in prefs["genre_prefs"]]
        region_list = [r for r, _ in prefs["region_prefs"]]
        decade_list = [d for d, _ in prefs["decade_prefs"]]

        # 尝试 LLM 辅助
        profile_text = None
        if context and provider_id:
            try:
                prompt = self._build_llm_prompt(prefs, nickname)
                system_prompt = persona_text if persona_text else None

                llm_resp = await context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    system_prompt=system_prompt,
                )
                if llm_resp and llm_resp.completion_text:
                    # LLM 分析 + 统计数据
                    formatted = self._format_profile_from_stats(prefs, nickname)
                    profile_text = f"{llm_resp.completion_text}\n\n{formatted}"
            except Exception as exc:
                logger.warning(f"LLM 画像生成失败，回退到纯文本: {exc}")

        # 纯文本回退
        if not profile_text:
            profile_text = self._format_profile_from_stats(prefs, nickname)

        # 缓存
        await self.db.save_profile(
            astrbot_uid=astrbot_uid,
            profile_text=profile_text,
            raw_stats=stats,
            genre_prefs=genre_list,
            region_prefs=region_list,
            decade_prefs=decade_list,
            total_marked=prefs["total_marked"],
        )
        await self.db.update_last_profile(astrbot_uid)

        logger.info(f"用户 {astrbot_uid} 画像生成完成")
        return profile_text
