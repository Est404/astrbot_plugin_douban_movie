from __future__ import annotations

from astrbot.api import logger

from ..db.database import Database


class ProfileGenerator:
    """基于已同步片单生成用户观影画像。"""

    def __init__(self, db: Database):
        self.db = db

    def _collect_stats(self, movies: list[dict]) -> dict:
        """从观影列表中聚合统计数据，返回结构化的统计摘要。"""
        total = len(movies)

        # 类型偏好
        genre_stats: dict[str, dict] = {}
        for m in movies:
            if not m.get("genres"):
                continue
            for genre in m["genres"].split(","):
                genre = genre.strip()
                if not genre:
                    continue
                if genre not in genre_stats:
                    genre_stats[genre] = {"count": 0, "ratings": []}
                genre_stats[genre]["count"] += 1
                if m.get("user_rating"):
                    genre_stats[genre]["ratings"].append(m["user_rating"])

        top_genres = sorted(
            genre_stats.items(), key=lambda x: x[1]["count"], reverse=True
        )[:5]

        # 地区偏好
        region_stats: dict[str, int] = {}
        for m in movies:
            if not m.get("regions"):
                continue
            for region in m["regions"].split(","):
                region = region.strip()
                if region:
                    region_stats[region] = region_stats.get(region, 0) + 1

        top_regions = sorted(region_stats.items(), key=lambda x: x[1], reverse=True)[:3]

        # 年代偏好
        decade_stats: dict[str, int] = {}
        for m in movies:
            if not m.get("year"):
                continue
            decade = f"{(m['year'] // 10) * 10}s"
            decade_stats[decade] = decade_stats.get(decade, 0) + 1

        top_decades = sorted(decade_stats.items(), key=lambda x: x[1], reverse=True)

        # 评分习惯
        ratings = [m["user_rating"] for m in movies if m.get("user_rating")]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0

        return {
            "total": total,
            "top_genres": top_genres,
            "top_regions": top_regions,
            "top_decades": top_decades,
            "avg_rating": avg_rating,
            "rating_count": len(ratings),
        }

    def _format_stats_text(self, stats: dict) -> str:
        """将统计摘要格式化为纯文本画像。"""
        total = stats["total"]
        top_genres = stats["top_genres"]
        top_regions = stats["top_regions"]
        top_decades = stats["top_decades"]
        avg_rating = stats["avg_rating"]

        if avg_rating >= 4.0:
            rating_type = "宽容型"
        elif avg_rating <= 2.5:
            rating_type = "严厉型"
        else:
            rating_type = "中立型"

        lines = [
            "📊 观影画像",
            "━━━━━━━━━━━━━━━━━━",
            f"🎬 看过：{total} 部",
        ]

        if top_genres:
            lines.append("\n🏷️ 类型偏好 TOP 5：")
            for i, (genre, gstats) in enumerate(top_genres, 1):
                avg = (
                    sum(gstats["ratings"]) / len(gstats["ratings"])
                    if gstats["ratings"]
                    else 0
                )
                lines.append(f"  {i}. {genre}（{gstats['count']}部，均分{avg:.1f}）")

        if top_regions:
            lines.append("\n🌍 地区偏好 TOP 3：")
            for i, (region, count) in enumerate(top_regions, 1):
                lines.append(f"  {i}. {region}（{count}部）")

        if top_decades:
            lines.append("\n📅 年代偏好：")
            for decade, count in top_decades:
                lines.append(f"  {decade}: {count}部")

        lines.append("\n⭐ 评分习惯：")
        lines.append(f"  平均打分：{avg_rating:.1f} / 5.0（{rating_type}）")

        return "\n".join(lines)

    def _build_llm_prompt(self, stats: dict) -> str:
        """将统计摘要构造为 LLM prompt。"""
        genre_lines = []
        for genre, gstats in stats["top_genres"]:
            avg = (
                sum(gstats["ratings"]) / len(gstats["ratings"])
                if gstats["ratings"]
                else 0
            )
            genre_lines.append(f"- {genre}：{gstats['count']}部，均分{avg:.1f}")

        region_lines = [
            f"- {r}：{c}部" for r, c in stats["top_regions"]
        ]

        decade_lines = [
            f"- {d}：{c}部" for d, c in stats["top_decades"]
        ]

        return (
            "你是一位专业的影评分析师。请根据以下用户的豆瓣观影统计数据，"
            "生成一段生动有趣的中文观影画像分析（200字以内）。\n\n"
            f"用户共看过 {stats['total']} 部电影，"
            f"有 {stats['rating_count']} 部打了分，平均打分 {stats['avg_rating']:.1f}/5.0。\n\n"
            "类型偏好：\n" + "\n".join(genre_lines) + "\n\n"
            "地区偏好：\n" + "\n".join(region_lines) + "\n\n"
            "年代偏好：\n" + "\n".join(decade_lines) + "\n\n"
            "请直接输出画像分析文本，不要加标题或额外格式。"
        )

    async def generate(
        self,
        astrbot_uid: str,
        context=None,
        provider_id: str = "",
    ) -> str:
        """生成用户观影画像。如果配置了 LLM provider 则使用 LLM 辅助。"""
        movies = await self.db.get_movies_by_status(astrbot_uid, "collect")
        if not movies:
            return "暂无观影数据，请先使用 /movie sync 同步片单。"

        # 数据完整性校验
        with_genres = sum(1 for m in movies if m.get("genres"))
        genre_ratio = with_genres / len(movies) if movies else 0
        if genre_ratio < 0.3:
            return (
                f"⚠️ 画像数据不充分：{len(movies)} 部影片中仅 {with_genres} 部有类型信息。\n"
                "请再次执行 /movie sync 补充影片详情后重试。"
            )

        stats = self._collect_stats(movies)

        # 尝试 LLM 辅助
        if context and provider_id:
            try:
                prompt = self._build_llm_prompt(stats)
                llm_resp = await context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                )
                if llm_resp and llm_resp.completion_text:
                    stats_text = self._format_stats_text(stats)
                    return f"{llm_resp.completion_text}\n\n{stats_text}"
            except Exception as exc:
                logger.warning(f"LLM 画像生成失败，回退到纯文本: {exc}")

        # 纯文本回退
        logger.info(f"用户 {astrbot_uid} 画像生成完成，共 {stats['total']} 部")
        return self._format_stats_text(stats)
