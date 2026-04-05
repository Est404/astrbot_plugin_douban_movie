from __future__ import annotations

import asyncio

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.api.util import SessionController, session_waiter

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
            cookie=config.get("douban_cookie", ""),
        )
        self.profile_gen = ProfileGenerator(self.db, self.client)
        self.recommender = Recommender(
            self.db,
            self.client,
            recommend_count=config.get("recommend_count", 5),
            candidate_pool_size=config.get("candidate_pool_size", 20),
            min_rating=config.get("min_rating", 7.0),
        )

        asyncio.create_task(self._init_db())
        logger.info("豆瓣电影推荐插件已加载")

    async def _init_db(self):
        await self.db.init()

    # ── 人格注入辅助 ────────────────────────────────────────

    async def _resolve_persona_text(self, event: AstrMessageEvent) -> str:
        """获取当前会话的人格提示词。"""
        try:
            umo = event.unified_msg_origin
            cid = await self.context.conversation_manager.get_curr_conversation_id(umo)
            if not cid:
                return ""
            conv = await self.context.conversation_manager.get_conversation(
                unified_msg_origin=umo,
                conversation_id=cid,
            )
            if conv and conv.persona_id:
                persona = self.context.persona_manager.get_persona_v3_by_id(
                    conv.persona_id
                )
                if persona and persona.get("prompt"):
                    return persona["prompt"]
        except Exception as exc:
            logger.debug(f"获取人格信息失败: {exc}")
        return ""

    # ── 指令组 ─────────────────────────────────────────────

    @filter.command_group("movie")
    def movie(self):
        """豆瓣电影推荐"""
        pass

    # ── bind ───────────────────────────────────────────────

    @movie.command("bind")
    async def bind(self, event: AstrMessageEvent, douban_id: str = ""):
        """绑定豆瓣数字ID"""
        uid = event.get_sender_id()

        if not douban_id:
            yield event.plain_result(
                "使用方法：/movie bind <豆瓣数字ID或主页链接>\n\n"
                "示例：\n"
                "  /movie bind 159896279\n"
                "  /movie bind https://www.douban.com/people/159896279/\n\n"
                "数字ID 是你豆瓣个人主页 URL 中 /people/ 后面的数字。"
            )
            return

        try:
            # 提取数字 ID
            numeric_id = DoubanClient.extract_numeric_id(douban_id)
            if not numeric_id:
                yield event.plain_result(
                    "❌ 无法识别豆瓣数字ID。请输入纯数字或完整的主页链接。"
                )
                return

            # 验证
            result = await self.client.validate_douban_uid(numeric_id)
            if not result:
                if self.client.cookie_expired:
                    yield event.plain_result(
                        "❌ 豆瓣 Cookie 已失效，请联系管理员更新。"
                    )
                    return
                yield event.plain_result(
                    "❌ 无法访问该豆瓣用户数据，请检查ID是否正确。"
                )
                return

            # 绑定
            await self.db.bind_user(
                uid, numeric_id, nickname=result.get("nickname")
            )
            name = result.get("nickname") or numeric_id
            total = result.get("total_marked", 0)
            yield event.plain_result(
                f"✅ 绑定成功！\n"
                f"豆瓣昵称：{name}\n"
                f"标记数量：{total} 部"
            )
            logger.info(f"用户 {uid} 绑定豆瓣账号 {numeric_id}")
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
            yield event.plain_result("✅ 已解绑豆瓣账号，所有数据已清除。")
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
                    "❌ 未绑定豆瓣账号。使用 /movie bind <数字ID> 绑定。"
                )
                return

            douban_uid = bind_info["douban_uid"]
            nickname = bind_info.get("nickname") or douban_uid
            last_profile = bind_info.get("last_profile") or "从未"

            profile = await self.db.get_profile(uid)
            has_profile = "是" if profile else "否"

            seen_count = len(await self.db.get_seen_movie_ids(uid))

            yield event.plain_result(
                "📋 豆瓣绑定状态\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"豆瓣ID：{douban_uid}\n"
                f"昵称：{nickname}\n"
                f"绑定时间：{bind_info.get('bind_time', '未知')}\n"
                f"已生成画像：{has_profile}\n"
                f"上次画像更新：{last_profile}\n"
                f"已排除影片：{seen_count} 部"
            )
        except Exception as exc:
            logger.error(f"查询状态失败: {exc}")
            yield event.plain_result("❌ 查询过程中出错，请稍后重试。")

    # ── profile ────────────────────────────────────────────

    @movie.command("profile")
    async def profile(self, event: AstrMessageEvent):
        """生成观影画像"""
        uid = event.get_sender_id()
        try:
            provider_id = self.config.get("profile_provider_id", "")
            persona_text = await self._resolve_persona_text(event)
            context = self.context if provider_id else None

            text = await self.profile_gen.generate(
                astrbot_uid=uid,
                persona_text=persona_text,
                context=context,
                provider_id=provider_id,
            )
            yield event.plain_result(text)
        except Exception as exc:
            logger.error(f"生成画像失败: {exc}")
            yield event.plain_result("❌ 生成画像过程中出错，请稍后重试。")

    # ── rec / recommend ────────────────────────────────────

    @movie.command("rec", alias={"recommend"})
    async def recommend(self, event: AstrMessageEvent, keyword: str = ""):
        """推荐电影"""
        uid = event.get_sender_id()
        try:
            bind_info = await self.db.get_bind(uid)
            if not bind_info:
                yield event.plain_result(
                    "❌ 请先使用 /movie bind 绑定豆瓣账号。"
                )
                return

            profile = await self.db.get_profile(uid)
            if not profile:
                yield event.plain_result(
                    "❌ 请先使用 /movie profile 生成观影画像。"
                )
                return

            yield event.plain_result("🔍 正在为你搜索并挑选推荐影片...")

            provider_id = self.config.get("recommend_provider_id", "")
            persona_text = await self._resolve_persona_text(event)
            context = self.context if provider_id else None

            results, session_id = await self.recommender.search_and_recommend(
                astrbot_uid=uid,
                user_description=keyword,
                persona_text=persona_text,
                context=context,
                provider_id=provider_id,
            )

            if not results:
                suffix = f"（关键词：{keyword}）" if keyword else ""
                yield event.plain_result(f"❌ 暂无合适的推荐{suffix}。试试其他关键词？")
                return

            # 格式化推荐结果
            output = self._format_recommendations(results, keyword)
            output += "\n\n💡 回复「看过了」重新推荐"

            yield event.plain_result(output)

            # 等待用户反馈
            @session_waiter(timeout=120)
            async def feedback_waiter(
                controller: SessionController, fb_event: AstrMessageEvent
            ):
                msg = fb_event.message_str.strip()
                if "看过了" not in msg:
                    controller.stop()
                    return

                # 重新推荐
                new_results = await self.recommender.re_recommend(
                    session_id=session_id,
                    astrbot_uid=uid,
                    persona_text=persona_text,
                    context=context,
                    provider_id=provider_id,
                )

                if not new_results:
                    await fb_event.send(
                        fb_event.plain_result(
                            "😔 候选影片已耗尽，请更换关键词或稍后再试。"
                        )
                    )
                    controller.stop()
                    return

                new_output = self._format_recommendations(new_results[0], keyword)
                new_output += "\n\n💡 回复「看过了」重新推荐"
                await fb_event.send(fb_event.plain_result(new_output))

                # 更新 session_id（re_recommend 返回同一个）
                controller.keep(timeout=120, reset_timeout=True)

            try:
                await feedback_waiter(event)
            except TimeoutError:
                pass
            finally:
                event.stop_event()

        except Exception as exc:
            logger.error(f"推荐失败: {exc}")
            yield event.plain_result("❌ 推荐过程中出错，请稍后重试。")

    @staticmethod
    def _format_recommendations(results: list[dict], keyword: str = "") -> str:
        """格式化推荐结果为文本。"""
        lines = []
        if keyword:
            lines.append(f"🎬 为你推荐「{keyword}」：")
        else:
            lines.append("🎬 为你推荐：")
        lines.append("━━━━━━━━━━━━━━━━━━")

        for i, r in enumerate(results, 1):
            rating = f"⭐{r['rating']}" if r.get("rating") else ""
            year = f"({r['year']})" if r.get("year") else ""
            lines.append(f"\n{i}. 《{r['title']}》{year} {rating}")
            if r.get("reason"):
                lines.append(f"   💡 {r['reason']}")

        return "\n".join(lines)

    # ── 生命周期 ───────────────────────────────────────────

    async def terminate(self):
        await self.db.close()
        logger.info("豆瓣电影推荐插件已卸载")
