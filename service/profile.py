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

    # ── 数据提取 ──────────────────────────────────────────────

    def _extract_prefs_from_stats(self, stats: dict) -> dict:
        """从 collection_stats API 完整响应中提取画像数据。

        直接使用 API 返回的顶层统计字段（genres, countries, years, directors, actors），
        不再依赖 recent_subjects 的小样本统计。
        """
        total = stats.get("total_collections", 0)

        # 类型偏好 — API 直接返回 genres 数组 [{name, value}]
        genre_raw = stats.get("genres", [])
        genre_prefs = []
        for g in genre_raw[:6]:
            name = g.get("name", "")
            value = g.get("value", 0)
            percent = round(value / total * 100) if total > 0 else 0
            genre_prefs.append({"name": name, "value": value, "percent": percent})

        # 地区偏好 — API 直接返回 countries 数组
        country_raw = stats.get("countries", [])
        country_prefs = []
        for c in country_raw[:5]:
            name = c.get("name", "")
            value = c.get("value", 0)
            percent = round(value / total * 100) if total > 0 else 0
            country_prefs.append({"name": name, "value": value, "percent": percent})

        # 年代偏好 — API 直接返回 years 数组
        decade_prefs = []
        for y in stats.get("years", []):
            name = y.get("name", "")
            value = y.get("value", 0)
            percent = round(value / total * 100) if total > 0 else 0
            decade_prefs.append({"name": name, "value": value, "percent": percent})

        # 年度标记分布
        collect_years = [
            {"name": y.get("name", ""), "value": y.get("value", 0)}
            for y in stats.get("collect_years", [])
        ]

        # 最爱导演
        top_directors = []
        for d in stats.get("directors", [])[:3]:
            known_for = []
            for m in d.get("known_for", [])[:2]:
                known_for.append(m.get("title", ""))
            top_directors.append({
                "name": d.get("name", ""),
                "known_for": known_for,
            })

        # 最爱演员
        top_actors = []
        for a in stats.get("actors", [])[:3]:
            known_for = []
            for m in a.get("known_for", [])[:2]:
                known_for.append(m.get("title", ""))
            top_actors.append({
                "name": a.get("name", ""),
                "known_for": known_for,
            })

        # 最近在看
        recent_watched = []
        for s in stats.get("recent_subjects", [])[:5]:
            rating_info = s.get("rating", {})
            rating_val = rating_info.get("value") if isinstance(rating_info, dict) else None
            recent_watched.append({
                "title": s.get("title", ""),
                "year": s.get("year", ""),
                "type": s.get("type", ""),
                "rating": rating_val,
            })

        return {
            "nickname": (stats.get("user") or {}).get("name", ""),
            "total_marked": total,
            "total_hours": stats.get("total_spent", 0),
            "total_cinema": stats.get("total_cenima", 0),
            "total_comments": stats.get("total_comment", 0),
            "total_reviews": stats.get("total_review", 0),
            "weekly_avg": stats.get("weekly_avg", 0),
            "genre_prefs": genre_prefs,
            "country_prefs": country_prefs,
            "decade_prefs": decade_prefs,
            "collect_years": collect_years,
            "top_directors": top_directors,
            "top_actors": top_actors,
            "recent_watched": recent_watched,
        }

    # ── 纯文本画像（回退） ────────────────────────────────────

    def _format_profile_from_stats(self, prefs: dict, nickname: str = "") -> str:
        """将统计数据格式化为纯文本画像（LLM 不可用时的回退）。"""
        name = nickname or prefs.get("nickname") or "你"
        total = prefs["total_marked"]
        hours = prefs["total_hours"]
        cinema = prefs["total_cinema"]

        lines = [
            f"🎬 {name} 的观影画像",
            "",
            f"📊 观影量：{total} 部标记",
            f"⏱ 累计观影：约 {hours:.0f} 小时" + (f" | 🏢 影院打卡 {cinema} 次" if cinema else ""),
        ]

        genre_prefs = prefs.get("genre_prefs", [])
        if genre_prefs:
            parts = [f"{g['name']} ({g['percent']}%)" for g in genre_prefs[:5]]
            lines.append(f"🎭 类型偏好：{' | '.join(parts)}")

        country_prefs = prefs.get("country_prefs", [])
        if country_prefs:
            parts = [f"{c['name']} ({c['percent']}%)" for c in country_prefs[:5]]
            lines.append(f"🌍 地区偏好：{' | '.join(parts)}")

        decade_prefs = prefs.get("decade_prefs", [])
        if decade_prefs:
            parts = [f"{d['name']} ({d['percent']}%)" for d in decade_prefs]
            lines.append(f"📅 年代偏好：{' | '.join(parts)}")

        top_directors = prefs.get("top_directors", [])
        if top_directors:
            names = [d["name"] for d in top_directors]
            lines.append(f"🎯 最爱导演：{'、'.join(names)}")

        top_actors = prefs.get("top_actors", [])
        if top_actors:
            names = [a["name"] for a in top_actors]
            lines.append(f"🌟 最爱演员：{'、'.join(names)}")

        recent = prefs.get("recent_watched", [])
        if recent:
            parts = []
            for r in recent:
                rating_str = f" ⭐{r['rating']}" if r.get("rating") else ""
                parts.append(f"{r['title']} ({r['year']}){rating_str}")
            lines.append(f"📌 最近在看：{' | '.join(parts)}")

        return "\n".join(lines)

    # ── LLM prompt ────────────────────────────────────────────

    def _build_llm_prompt(self, prefs: dict, nickname: str = "") -> str:
        """构造 LLM prompt 用于画像生成。"""
        name = nickname or prefs.get("nickname") or "该用户"

        # 序列化画像数据
        data_lines = [
            f"用户共标记 {prefs['total_marked']} 部影视，"
            f"累计观影约 {prefs['total_hours']:.0f} 小时"
            + (f"，影院打卡 {prefs['total_cinema']} 次" if prefs["total_cinema"] else "")
            + "。",
        ]

        genre_prefs = prefs.get("genre_prefs", [])
        if genre_prefs:
            parts = [f"{g['name']} ({g['percent']}%)" for g in genre_prefs[:5]]
            data_lines.append(f"类型偏好：{' | '.join(parts)}")

        country_prefs = prefs.get("country_prefs", [])
        if country_prefs:
            parts = [f"{c['name']} ({c['percent']}%)" for c in country_prefs[:5]]
            data_lines.append(f"地区偏好：{' | '.join(parts)}")

        decade_prefs = prefs.get("decade_prefs", [])
        if decade_prefs:
            parts = [f"{d['name']} ({d['percent']}%)" for d in decade_prefs]
            data_lines.append(f"年代偏好：{' | '.join(parts)}")

        top_directors = prefs.get("top_directors", [])
        if top_directors:
            director_strs = []
            for d in top_directors:
                known = "、".join(d.get("known_for", [])[:2])
                director_strs.append(f"{d['name']}（代表作：{known}）" if known else d["name"])
            data_lines.append(f"最爱导演：{' | '.join(director_strs)}")

        top_actors = prefs.get("top_actors", [])
        if top_actors:
            actor_strs = []
            for a in top_actors:
                known = "、".join(a.get("known_for", [])[:2])
                actor_strs.append(f"{a['name']}（代表作：{known}）" if known else a["name"])
            data_lines.append(f"最爱演员：{' | '.join(actor_strs)}")

        recent = prefs.get("recent_watched", [])
        if recent:
            parts = []
            for r in recent:
                rating_str = f" ⭐{r['rating']}" if r.get("rating") else ""
                parts.append(f"{r['title']} ({r['year']}){rating_str}")
            data_lines.append(f"最近在看：{' | '.join(parts)}")

        # 找观影高峰年
        collect_years = prefs.get("collect_years", [])
        peak_year = ""
        if collect_years:
            peak = max(collect_years, key=lambda x: x.get("value", 0))
            if peak.get("value", 0) > 0:
                peak_year = f"\n额外洞察：{peak['name']}年是观影高峰期，看片量是一年{peak['value']}部。"

        data_text = "\n".join(data_lines)

        return (
            f"你是一位观影分析师，正在为用户「{name}」生成观影画像。\n"
            "请根据以下数据，用简洁生动的语言生成一份观影画像报告。\n\n"
            "要求：\n"
            "- 使用第二人称\"你\"来称呼用户\n"
            "- 不要简单罗列数据，要有洞察和总结\n"
            "- 最后用一句话概括这位用户的观影品味\n\n"
            f"用户数据：\n{data_text}\n"
            f"{peak_year}\n\n"
            "请直接输出画像分析文本，不要加标题或额外格式。"
        )

    # ── 主生成方法 ────────────────────────────────────────────

    async def generate(
        self,
        astrbot_uid: str,
        persona_text: str = "",
        context=None,
        provider_id: str = "",
    ) -> str:
        """生成用户观影画像。"""
        # 检查缓存
        cached = await self.db.get_profile(astrbot_uid)
        if cached and cached.get("profile_text"):
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

        # 提取偏好（使用完整 API 数据）
        prefs = self._extract_prefs_from_stats(stats)

        # 保存偏好数据到 DB
        genre_list = [g["name"] for g in prefs["genre_prefs"]]
        region_list = [c["name"] for c in prefs["country_prefs"]]
        decade_list = [d["name"] for d in prefs["decade_prefs"]]

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
