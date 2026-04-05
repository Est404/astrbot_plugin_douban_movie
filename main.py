from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 将插件目录加入 sys.path，使 db / service 子包可被直接导入
sys.path.insert(0, str(Path(__file__).parent))

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from db.database import Database
from service.douban_client import DoubanClient
from service.profile import ProfileGenerator
from service.recommender import Recommender


class DoubanMovie(Star):
    def __init__(self, context: Context):
        super().__init__(context)

        data_dir = Path(__file__).parent / "data"
        data_dir.mkdir(exist_ok=True)

        self.db = Database(str(data_dir / "douban_movie.db"))
        self.client = DoubanClient()
        self.profile_gen = ProfileGenerator(self.db)
        self.recommender = Recommender(self.db, self.client)

        asyncio.create_task(self._init_db())
        logger.info("豆瓣电影推荐插件已加载")

    async def _init_db(self):
        await self.db.init()

    # ── 指令组 ─────────────────────────────────────────────

    @filter.command_group("movie")
    def movie(self):
        """豆瓣电影推荐"""
        pass

    # ── bind ───────────────────────────────────────────────

    @movie.command("bind")
    async def bind(self, event: AstrMessageEvent, cookie: str = ""):
        """绑定豆瓣账号"""
        uid = event.get_sender_id()

        if not cookie:
            yield event.plain_result(
                "使用方法：/movie bind <豆瓣Cookie>\n\n"
                "获取方式：\n"
                "1. 浏览器登录豆瓣 (douban.com)\n"
                "2. 按 F12 打开开发者工具 → Network\n"
                "3. 刷新页面，点击第一个请求\n"
                "4. 复制 Request Headers 中的 Cookie 值\n\n"
                "⚠️ 建议在私聊中使用以保护隐私"
            )
            return

        try:
            result = await self.client.validate_cookie(cookie)
            if not result:
                yield event.plain_result("❌ Cookie 验证失败，请检查是否正确。")
                return

            await self.db.bind_user(uid, result["uid"], cookie)
            name = result.get("nickname") or result["uid"]
            yield event.plain_result(f"✅ 绑定成功！豆瓣账号：{name}")
            logger.info(f"用户 {uid} 绑定豆瓣账号 {result['uid']}")
        except Exception as exc:
            logger.error(f"绑定失败: {exc}")
            yield event.plain_result("❌ 绑定过程中出错，请稍后重试。")

    # ── unbind ─────────────────────────────────────────────

    @movie.command("unbind")
    async def unbind(self, event: AstrMessageEvent):
        """解绑豆瓣账号"""
        uid = event.get_sender_id()
        try:
            bind_info = await self.db.get_bind(uid)
            if not bind_info:
                yield event.plain_result("❌ 你还没有绑定豆瓣账号。")
                return

            await self.db.unbind_user(uid)
            yield event.plain_result("✅ 已解绑豆瓣账号，片单数据已清除。")
            logger.info(f"用户 {uid} 解绑豆瓣账号")
        except Exception as exc:
            logger.error(f"解绑失败: {exc}")
            yield event.plain_result("❌ 解绑过程中出错，请稍后重试。")

    # ── status ─────────────────────────────────────────────

    @movie.command("status")
    async def status(self, event: AstrMessageEvent):
        """查看绑定状态"""
        uid = event.get_sender_id()
        try:
            bind_info = await self.db.get_bind(uid)
            if not bind_info:
                yield event.plain_result("❌ 未绑定豆瓣账号。使用 /movie bind 绑定。")
                return

            counts = await self.db.get_movie_count(uid)
            wish = counts.get("wish", 0)
            do = counts.get("do", 0)
            collect = counts.get("collect", 0)
            total = wish + do + collect
            last_sync = bind_info.get("last_sync") or "从未"

            yield event.plain_result(
                "📋 豆瓣绑定状态\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"豆瓣UID：{bind_info['douban_uid']}\n"
                f"绑定时间：{bind_info.get('bind_time', '未知')}\n"
                f"上次同步：{last_sync}\n"
                f"已同步影片：{total} 部\n"
                f"  想看 {wish} · 在看 {do} · 看过 {collect}"
            )
        except Exception as exc:
            logger.error(f"查询状态失败: {exc}")
            yield event.plain_result("❌ 查询过程中出错，请稍后重试。")

    # ── sync ───────────────────────────────────────────────

    @movie.command("sync")
    async def sync(self, event: AstrMessageEvent):
        """同步豆瓣片单"""
        uid = event.get_sender_id()
        try:
            bind_info = await self.db.get_bind(uid)
            if not bind_info:
                yield event.plain_result("❌ 请先使用 /movie bind 绑定豆瓣账号。")
                return

            yield event.plain_result("🔄 开始同步片单，请稍候...")

            last_sync = bind_info.get("last_sync")
            cookie = bind_info["cookie"]
            douban_uid = bind_info["douban_uid"]

            # 带超时的同步
            try:
                results = await asyncio.wait_for(
                    self.client.fetch_all_collections(douban_uid, cookie, last_sync),
                    timeout=60.0,
                )
            except asyncio.TimeoutError:
                await self.db.update_last_sync(uid)
                yield event.plain_result(
                    "⚠️ 同步超时（60s），已保存已获取的数据。可再次执行同步继续。"
                )
                return

            # 写入数据库
            total_new = 0
            for status_type, movies in results.items():
                for movie in movies:
                    await self.db.upsert_movie(uid, movie)
                    total_new += 1

            await self.db.commit_batch()

            # 补充详情（genres / regions / year）
            if total_new > 0:
                await self._enrich_movie_details(uid, min(total_new, 50))

            await self.db.update_last_sync(uid)

            wish = len(results["wish"])
            do = len(results["do"])
            collect = len(results["collect"])
            yield event.plain_result(
                f"✅ 同步完成！已同步 {total_new} 部影片\n"
                f"想看 {wish} · 在看 {do} · 看过 {collect}"
            )
            logger.info(f"用户 {uid} 同步了 {total_new} 部影片")
        except Exception as exc:
            logger.error(f"同步失败: {exc}")
            yield event.plain_result("❌ 同步过程中出错，请稍后重试。")

    async def _enrich_movie_details(self, uid: str, limit: int):
        """为缺少详情的影片补充类型/地区/年份。"""
        movie_ids = await self.db.get_movies_without_details(uid, limit)
        if not movie_ids:
            return

        logger.info(f"开始补充 {len(movie_ids)} 部影片详情...")
        for movie_id in movie_ids:
            detail = await self.client.fetch_movie_detail(movie_id)
            if detail:
                await self.db.update_movie_details(
                    movie_id,
                    uid,
                    detail.get("genres", ""),
                    detail.get("regions", ""),
                    detail.get("year"),
                )
        await self.db.commit_batch()

    # ── profile ────────────────────────────────────────────

    @movie.command("profile")
    async def profile(self, event: AstrMessageEvent):
        """生成观影画像"""
        uid = event.get_sender_id()
        try:
            bind_info = await self.db.get_bind(uid)
            if not bind_info:
                yield event.plain_result("❌ 请先使用 /movie bind 绑定豆瓣账号。")
                return

            counts = await self.db.get_movie_count(uid)
            if counts.get("collect", 0) == 0:
                yield event.plain_result(
                    "❌ 暂无观影数据，请先使用 /movie sync 同步片单。"
                )
                return

            text = await self.profile_gen.generate(uid)
            yield event.plain_result(text)
        except Exception as exc:
            logger.error(f"生成画像失败: {exc}")
            yield event.plain_result("❌ 生成画像过程中出错，请稍后重试。")

    # ── rec / recommend ────────────────────────────────────

    @movie.command("rec", alias={"recommend"})
    async def recommend(self, event: AstrMessageEvent, genre: str = ""):
        """推荐电影"""
        uid = event.get_sender_id()
        try:
            bind_info = await self.db.get_bind(uid)
            if not bind_info:
                yield event.plain_result("❌ 请先使用 /movie bind 绑定豆瓣账号。")
                return

            counts = await self.db.get_movie_count(uid)
            if counts.get("collect", 0) == 0:
                yield event.plain_result(
                    "❌ 请先使用 /movie sync 同步片单，以便了解你的口味。"
                )
                return

            yield event.plain_result("🔍 正在为你挑选推荐影片...")

            results = await self.recommender.recommend(uid, genre)
            if not results:
                suffix = f"（筛选：{genre}）" if genre else ""
                yield event.plain_result(f"❌ 暂无合适的推荐{suffix}。试试其他类型？")
                return

            lines = []
            if genre:
                lines.append(f"🎬 为你推荐「{genre}」：")
            else:
                lines.append("🎬 为你推荐：")
            lines.append("━━━━━━━━━━━━━━━━━━")

            for i, r in enumerate(results, 1):
                rating = f"⭐{r['avg_rating']}" if r.get("avg_rating") else ""
                year = f"({r['year']})" if r.get("year") else ""
                lines.append(f"\n{i}. {r['title']} {year} {rating}")
                if r.get("reason"):
                    lines.append(f"   💡 {r['reason']}")

            yield event.plain_result("\n".join(lines))
        except Exception as exc:
            logger.error(f"推荐失败: {exc}")
            yield event.plain_result("❌ 推荐过程中出错，请稍后重试。")

    # ── 生命周期 ───────────────────────────────────────────

    async def terminate(self):
        await self.db.close()
        logger.info("豆瓣电影推荐插件已卸载")
