from __future__ import annotations

from astrbot.api import logger

from ..db.database import Database


class ProfileGenerator:
    """基于已同步片单生成用户观影画像。"""

    def __init__(self, db: Database):
        self.db = db

    async def generate(self, astrbot_uid: str) -> str:
        movies = await self.db.get_movies_by_status(astrbot_uid, "collect")
        if not movies:
            return "暂无观影数据，请先使用 /movie sync 同步片单。"

        total = len(movies)

        # ── 类型偏好 ─────────────────────────────────────
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

        # ── 地区偏好 ─────────────────────────────────────
        region_stats: dict[str, int] = {}
        for m in movies:
            if not m.get("regions"):
                continue
            for region in m["regions"].split(","):
                region = region.strip()
                if region:
                    region_stats[region] = region_stats.get(region, 0) + 1

        top_regions = sorted(region_stats.items(), key=lambda x: x[1], reverse=True)[:3]

        # ── 年代偏好 ─────────────────────────────────────
        decade_stats: dict[str, int] = {}
        for m in movies:
            if not m.get("year"):
                continue
            decade = f"{(m['year'] // 10) * 10}s"
            decade_stats[decade] = decade_stats.get(decade, 0) + 1

        top_decades = sorted(decade_stats.items(), key=lambda x: x[1], reverse=True)

        # ── 评分习惯 ─────────────────────────────────────
        ratings = [m["user_rating"] for m in movies if m.get("user_rating")]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0

        if avg_rating >= 4.0:
            rating_type = "宽容型"
        elif avg_rating <= 2.5:
            rating_type = "严厉型"
        else:
            rating_type = "中立型"

        # ── 拼装输出 ─────────────────────────────────────
        lines = [
            "📊 观影画像",
            "━━━━━━━━━━━━━━━━━━",
            f"🎬 看过：{total} 部",
        ]

        if top_genres:
            lines.append("\n🏷️ 类型偏好 TOP 5：")
            for i, (genre, stats) in enumerate(top_genres, 1):
                avg = (
                    sum(stats["ratings"]) / len(stats["ratings"])
                    if stats["ratings"]
                    else 0
                )
                lines.append(f"  {i}. {genre}（{stats['count']}部，均分{avg:.1f}）")

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

        logger.info(f"用户 {astrbot_uid} 画像生成完成，共 {total} 部")
        return "\n".join(lines)
