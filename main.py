from __future__ import annotations

import asyncio

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

from .db.database import Database
from .service.douban_client import DoubanClient
from .service.profile import ProfileGenerator
from .service.recommender import Recommender


class DoubanMovie(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        data_dir = StarTools.get_data_dir()

        self.config = config
        self.db = Database(str(data_dir / "douban_movie.db"))
        self.client = DoubanClient(
            interval_min=config.get("request_interval_min", 1.0),
            interval_max=config.get("request_interval_max", 3.0),
            max_retries=config.get("max_retries", 3),
        )
        self.profile_gen = ProfileGenerator(self.db)
        self.recommender = Recommender(
            self.db,
            self.client,
            recommend_count=config.get("recommend_count", 5),
            min_rating=config.get("min_rating", 8.0),
        )

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
    async def bind(self, event: AstrMessageEvent, douban_id: str = ""):
        """绑定豆瓣主页ID"""
        uid = event.get_sender_id()

        if not douban_id:
            yield event.plain_result(
                "使用方法：/movie bind <豆瓣主页ID>\n\n"
                "示例：/movie bind E-st2000\n\n"
                "主页ID 是你豆瓣个人主页 URL 中 /people/ 后面的部分。\n"
                "例如 https://www.douban.com/people/E-st2000/ 中的 E-st2000"
            )
            return

        try:
            result = await self.client.validate_uid(douban_id)
            if not result:
                yield event.plain_result(
                    "❌ 无法访问该豆瓣主页，请检查ID是否正确。"
                )
                return

            await self.db.bind_user(uid, douban_id)
            name = result.get("nickname") or douban_id
            yield event.plain_result(f"✅ 绑定成功！豆瓣账号：{name}")
            logger.info(f"用户 {uid} 绑定豆瓣账号 {douban_id}")
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
                yield event.plain_result(
                    "❌ 未绑定豆瓣账号。使用 /movie bind <主页ID> 绑定。"
                )
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
                f"豆瓣ID：{bind_info['douban_uid']}\n"
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
                yield event.plain_result(
                    "❌ 请先使用 /movie bind 绑定豆瓣账号。"
                )
                return

            yield event.plain_result("🔄 开始同步片单，请稍候...")

            douban_uid = bind_info["douban_uid"]
            last_sync = bind_info.get("last_sync")
            sync_timeout = float(self.config.get("sync_timeout", 60))

            # 逐页抓取 + 即时写入，超时也能保留已获取的数据
            counts = {"wish": 0, "do": 0, "collect": 0}
            timed_out = False

            try:
                async with asyncio.timeout(sync_timeout):
                    for status_type in ("wish", "do", "collect"):
                        start = 0
                        while True:
                            await self.client._delay()
                            movies, has_more = (
                                await self.client.fetch_collection_page(
                                    douban_uid, status_type, start
                                )
                            )
                            if not movies:
                                break

                            # 增量过滤：跳过上次同步之前标记的
                            if last_sync:
                                new_movies = []
                                for m in movies:
                                    if m.get("marked_at") and m["marked_at"] > last_sync:
                                        new_movies.append(m)
                                    else:
                                        has_more = False
                                        break
                                movies = new_movies

                            # 即时写入
                            for movie in movies:
                                await self.db.upsert_movie(uid, movie)
                            await self.db.commit_batch()
                            counts[status_type] += len(movies)

                            if not has_more:
                                break
                            start += 15
            except asyncio.TimeoutError:
                timed_out = True
                logger.warning(f"用户 {uid} 同步超时，已保存部分数据")

            total_new = sum(counts.values())

            # 补充详情（genres / regions / year）
            enrich_limit = self.config.get("detail_enrich_limit", 50)
            if total_new > 0:
                await self._enrich_movie_details(uid, enrich_limit)

            await self.db.update_last_sync(uid)

            wish, do, collect = counts["wish"], counts["do"], counts["collect"]
            msg = f"✅ 同步完成！已同步 {total_new} 部影片\n"
            msg += f"想看 {wish} · 在看 {do} · 看过 {collect}"
            if timed_out:
                msg += f"\n\n⚠️ 部分片单因超时未完成，可再次执行同步继续。"
            yield event.plain_result(msg)
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
                yield event.plain_result(
                    "❌ 请先使用 /movie bind 绑定豆瓣账号。"
                )
                return

            counts = await self.db.get_movie_count(uid)
            if counts.get("collect", 0) == 0:
                yield event.plain_result(
                    "❌ 暂无观影数据，请先使用 /movie sync 同步片单。"
                )
                return

            # 如果配置了 LLM provider 则使用 LLM 辅助
            provider_id = self.config.get("profile_provider_id", "")
            context = self.context if provider_id else None

            text = await self.profile_gen.generate(uid, context, provider_id)
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
                yield event.plain_result(
                    "❌ 请先使用 /movie bind 绑定豆瓣账号。"
                )
                return

            counts = await self.db.get_movie_count(uid)
            if counts.get("collect", 0) == 0:
                yield event.plain_result(
                    "❌ 请先使用 /movie sync 同步片单，以便了解你的口味。"
                )
                return

            yield event.plain_result("🔍 正在为你挑选推荐影片...")

            # 如果配置了 LLM provider 则使用 LLM 生成理由
            provider_id = self.config.get("recommend_provider_id", "")
            context = self.context if provider_id else None

            results = await self.recommender.recommend(uid, genre, context, provider_id)
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
