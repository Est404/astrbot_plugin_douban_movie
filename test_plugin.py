"""
AstrBot 豆瓣电影推荐插件 - 单元测试
使用 unittest + unittest.mock，不发送真实网络请求。
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# 让插件包可以被 import
# ---------------------------------------------------------------------------
PLUGIN_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PLUGIN_DIR.parent.parent.parent  # E:\AstrBot

# 确保 AstrBot 项目根目录在 sys.path 中
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 插件目录的父目录，使得 `astrbot_plugin_douban_movie` 可被作为包导入
if str(PLUGIN_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR.parent))

# 在导入插件模块之前 mock 掉 astrbot 依赖，避免实际加载 AstrBot 框架
_mock_astrbot_api = MagicMock()
_mock_astrbot_api.logger = MagicMock()
_mock_astrbot_api.AstrBotConfig = dict  # 配置就是 dict

_mock_astrbot_api_event = MagicMock()
_mock_astrbot_api_event.filter = MagicMock()

_mock_astrbot_api_star = MagicMock()
_mock_astrbot_api_star.Context = MagicMock
_mock_astrbot_api_star.Star = type("Star", (), {"__init__": lambda self, ctx: None})
_mock_astrbot_api_star.StarTools = MagicMock()

# 注册 mock 模块
sys.modules["astrbot"] = MagicMock()
sys.modules["astrbot.api"] = _mock_astrbot_api
sys.modules["astrbot.api.event"] = _mock_astrbot_api_event
sys.modules["astrbot.api.star"] = _mock_astrbot_api_star

# 现在可以安全地导入插件模块
import astrbot_plugin_douban_movie.db.database as db_mod
import astrbot_plugin_douban_movie.service.douban_client as dc_mod
import astrbot_plugin_douban_movie.service.profile as pf_mod
import astrbot_plugin_douban_movie.service.recommender as rc_mod
from astrbot_plugin_douban_movie.db.database import Database
from astrbot_plugin_douban_movie.service.douban_client import DoubanClient
from astrbot_plugin_douban_movie.service.profile import ProfileGenerator
from astrbot_plugin_douban_movie.service.recommender import Recommender

# ---------------------------------------------------------------------------
# 辅助：同步运行 async 函数
# ---------------------------------------------------------------------------
def run_async(coro):
    """在测试中同步运行异步协程。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ===========================================================================
# 测试1：插件导入与模块结构
# ===========================================================================
class TestPluginStructure(unittest.TestCase):
    """验证插件的文件结构、元数据和模块可解析性。"""

    # --- 1.1 _conf_schema.json 合法性 & 字段完整性 ---
    def test_conf_schema_valid_json(self):
        """_conf_schema.json 是合法 JSON。"""
        path = PLUGIN_DIR / "_conf_schema.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)

    def test_conf_schema_expected_fields(self):
        """_conf_schema.json 包含所有预期字段。"""
        expected_keys = {
            "sync_timeout",
            "recommend_count",
            "min_rating",
            "request_interval_min",
            "request_interval_max",
            "max_retries",
            "detail_enrich_limit",
        }
        path = PLUGIN_DIR / "_conf_schema.json"
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(set(data.keys()), expected_keys)

    # --- 1.2 metadata.yaml 包含必要字段 ---
    def test_metadata_has_required_fields(self):
        """metadata.yaml 包含 name, author, version, description, astrbot_version。"""
        path = PLUGIN_DIR / "metadata.yaml"
        content = path.read_text(encoding="utf-8")
        for field in ("name", "author", "version", "description", "astrbot_version"):
            self.assertIn(field, content, f"metadata.yaml 缺少字段: {field}")

    # --- 1.3 各 Python 模块语法正确（ast.parse） ---
    def _assert_syntax_ok(self, rel_path: str):
        full = PLUGIN_DIR / rel_path
        with open(full, encoding="utf-8") as f:
            source = f.read()
        try:
            ast.parse(source)
        except SyntaxError as e:
            self.fail(f"{rel_path} 存在语法错误: {e}")

    def test_main_py_syntax(self):
        self._assert_syntax_ok("main.py")

    def test_db_database_syntax(self):
        self._assert_syntax_ok("db/database.py")

    def test_service_douban_client_syntax(self):
        self._assert_syntax_ok("service/douban_client.py")

    def test_service_profile_syntax(self):
        self._assert_syntax_ok("service/profile.py")

    def test_service_recommender_syntax(self):
        self._assert_syntax_ok("service/recommender.py")

    # --- 1.4 模拟 AstrBot 加载插件 ---
    def test_doubanmovie_init_no_error(self):
        """使用 mock Context + config 实例化 DoubanMovie 不抛异常。"""
        with patch.object(sys.modules["astrbot.api.star"].StarTools, "get_data_dir", return_value=Path("/tmp/astrbot_test")):
            with patch("astrbot_plugin_douban_movie.main.asyncio.create_task"):
                with patch.object(Database, "init", new_callable=AsyncMock):
                    from astrbot_plugin_douban_movie.main import DoubanMovie

                    ctx = MagicMock()
                    config = {
                        "sync_timeout": 60,
                        "recommend_count": 5,
                        "min_rating": 8.0,
                        "request_interval_min": 1.0,
                        "request_interval_max": 3.0,
                        "max_retries": 3,
                    }
                    try:
                        plugin = DoubanMovie(ctx, config)
                    except Exception as exc:
                        self.fail(f"DoubanMovie.__init__ 抛出异常: {exc}")

    # --- 1.5 相对导入路径验证 ---
    def test_relative_imports(self):
        """验证 db.database, service.douban_client, service.profile, service.recommender 在包内可找到。"""
        import astrbot_plugin_douban_movie.db.database
        import astrbot_plugin_douban_movie.service.douban_client
        import astrbot_plugin_douban_movie.service.profile
        import astrbot_plugin_douban_movie.service.recommender

        self.assertTrue(hasattr(astrbot_plugin_douban_movie.db.database, "Database"))
        self.assertTrue(hasattr(astrbot_plugin_douban_movie.service.douban_client, "DoubanClient"))
        self.assertTrue(hasattr(astrbot_plugin_douban_movie.service.profile, "ProfileGenerator"))
        self.assertTrue(hasattr(astrbot_plugin_douban_movie.service.recommender, "Recommender"))


# ===========================================================================
# 测试2：配置项
# ===========================================================================
class TestConfig(unittest.TestCase):
    """验证配置 schema 的字段规范。"""

    def _load_schema(self):
        with open(PLUGIN_DIR / "_conf_schema.json", encoding="utf-8") as f:
            return json.load(f)

    # --- 2.1 每个字段都有 type 和 description ---
    def test_every_field_has_type_and_description(self):
        schema = self._load_schema()
        for key, field in schema.items():
            self.assertIn("type", field, f"字段 {key} 缺少 'type'")
            self.assertIn("description", field, f"字段 {key} 缺少 'description'")

    # --- 2.2 每个字段都有合理的 default 值 ---
    def test_every_field_has_default(self):
        schema = self._load_schema()
        for key, field in schema.items():
            self.assertIn("default", field, f"字段 {key} 缺少 'default'")

    # --- 2.3 DoubanMovie.__init__ 接受 AstrBotConfig 参数并传递给子组件 ---
    def test_init_passes_config_to_components(self):
        config = {
            "request_interval_min": 0.5,
            "request_interval_max": 1.5,
            "max_retries": 5,
            "recommend_count": 10,
            "min_rating": 7.5,
        }
        with patch.object(sys.modules["astrbot.api.star"].StarTools, "get_data_dir", return_value=Path("/tmp/astrbot_test")):
            with patch("astrbot_plugin_douban_movie.main.asyncio.create_task"):
                with patch.object(Database, "init", new_callable=AsyncMock):
                    from astrbot_plugin_douban_movie.main import DoubanMovie

                    plugin = DoubanMovie(MagicMock(), config)
                    # 验证参数传递
                    self.assertEqual(plugin.client._interval_min, 0.5)
                    self.assertEqual(plugin.client._interval_max, 1.5)
                    self.assertEqual(plugin.client._max_retries, 5)
                    self.assertEqual(plugin.recommender._recommend_count, 10)
                    self.assertEqual(plugin.recommender._min_rating, 7.5)

    # --- 2.4 配置缺失时使用 .get() 默认值不崩溃 ---
    def test_init_with_empty_config(self):
        with patch.object(sys.modules["astrbot.api.star"].StarTools, "get_data_dir", return_value=Path("/tmp/astrbot_test")):
            with patch("astrbot_plugin_douban_movie.main.asyncio.create_task"):
                with patch.object(Database, "init", new_callable=AsyncMock):
                    from astrbot_plugin_douban_movie.main import DoubanMovie

                    try:
                        plugin = DoubanMovie(MagicMock(), {})
                    except Exception as exc:
                        self.fail(f"空配置导致崩溃: {exc}")
                    # 验证默认值
                    self.assertEqual(plugin.client._interval_min, 1.0)
                    self.assertEqual(plugin.client._interval_max, 3.0)
                    self.assertEqual(plugin.client._max_retries, 3)
                    self.assertEqual(plugin.recommender._recommend_count, 5)
                    self.assertEqual(plugin.recommender._min_rating, 8.0)


# ===========================================================================
# 测试3：核心业务逻辑
# ===========================================================================

# --- 3.1 Database 模块 ---
class TestDatabase(unittest.TestCase):
    """使用内存 SQLite 测试 Database 类。"""

    def setUp(self):
        self.db = Database(":memory:")

    def tearDown(self):
        try:
            run_async(self.db.close())
        except Exception:
            pass

    def _init_db(self):
        # 对内存数据库跳过 mkdir
        async def _do():
            import sqlite3
            self.db._conn = await __import__("aiosqlite").connect(":memory:")
            self.db._conn.row_factory = sqlite3.Row
            await self.db._create_tables()
        run_async(_do())

    # -- bind_user / get_bind / unbind_user --
    def test_bind_and_get_bind(self):
        self._init_db()

        async def _test():
            await self.db.bind_user("user1", "douban_abc", "cookie123")
            result = await self.db.get_bind("user1")
            self.assertIsNotNone(result)
            self.assertEqual(result["astrbot_uid"], "user1")
            self.assertEqual(result["douban_uid"], "douban_abc")
            self.assertEqual(result["cookie"], "cookie123")

        run_async(_test())

    def test_get_bind_not_found(self):
        self._init_db()

        async def _test():
            result = await self.db.get_bind("nonexistent")
            self.assertIsNone(result)

        run_async(_test())

    def test_unbind_user(self):
        self._init_db()

        async def _test():
            await self.db.bind_user("user1", "douban_abc", "cookie123")
            await self.db.unbind_user("user1")
            result = await self.db.get_bind("user1")
            self.assertIsNone(result)

        run_async(_test())

    def test_unbind_user_also_removes_movies(self):
        self._init_db()

        async def _test():
            await self.db.bind_user("user1", "douban_abc", "cookie123")
            await self.db.upsert_movie("user1", {
                "douban_movie_id": "123",
                "title": "Test Movie",
                "status": "collect",
            })
            await self.db.commit_batch()
            await self.db.unbind_user("user1")
            ids = await self.db.get_all_collected_movie_ids("user1")
            self.assertEqual(len(ids), 0)

        run_async(_test())

    # -- upsert_movie / get_movies_by_status --
    def test_upsert_and_get_movies_by_status(self):
        self._init_db()

        async def _test():
            await self.db.upsert_movie("user1", {
                "douban_movie_id": "100",
                "title": "Movie A",
                "status": "collect",
                "user_rating": 4.0,
            })
            await self.db.upsert_movie("user1", {
                "douban_movie_id": "200",
                "title": "Movie B",
                "status": "wish",
            })
            await self.db.commit_batch()

            collected = await self.db.get_movies_by_status("user1", "collect")
            self.assertEqual(len(collected), 1)
            self.assertEqual(collected[0]["title"], "Movie A")
            self.assertEqual(collected[0]["user_rating"], 4.0)

            wished = await self.db.get_movies_by_status("user1", "wish")
            self.assertEqual(len(wished), 1)
            self.assertEqual(wished[0]["title"], "Movie B")

        run_async(_test())

    def test_upsert_replaces_existing(self):
        """INSERT OR REPLACE 应该更新已有记录。"""
        self._init_db()

        async def _test():
            await self.db.upsert_movie("user1", {
                "douban_movie_id": "100",
                "title": "Old Title",
                "status": "collect",
            })
            await self.db.commit_batch()

            await self.db.upsert_movie("user1", {
                "douban_movie_id": "100",
                "title": "New Title",
                "status": "collect",
                "user_rating": 5.0,
            })
            await self.db.commit_batch()

            movies = await self.db.get_movies_by_status("user1", "collect")
            self.assertEqual(len(movies), 1)
            self.assertEqual(movies[0]["title"], "New Title")
            self.assertEqual(movies[0]["user_rating"], 5.0)

        run_async(_test())

    # -- get_movie_count --
    def test_get_movie_count(self):
        self._init_db()

        async def _test():
            await self.db.upsert_movie("user1", {"douban_movie_id": "1", "title": "A", "status": "collect"})
            await self.db.upsert_movie("user1", {"douban_movie_id": "2", "title": "B", "status": "collect"})
            await self.db.upsert_movie("user1", {"douban_movie_id": "3", "title": "C", "status": "wish"})
            await self.db.upsert_movie("user1", {"douban_movie_id": "4", "title": "D", "status": "do"})
            await self.db.commit_batch()

            counts = await self.db.get_movie_count("user1")
            self.assertEqual(counts.get("collect"), 2)
            self.assertEqual(counts.get("wish"), 1)
            self.assertEqual(counts.get("do"), 1)

        run_async(_test())

    # -- get_all_collected_movie_ids --
    def test_get_all_collected_movie_ids(self):
        self._init_db()

        async def _test():
            await self.db.upsert_movie("user1", {"douban_movie_id": "1", "title": "A", "status": "collect"})
            await self.db.upsert_movie("user1", {"douban_movie_id": "2", "title": "B", "status": "wish"})
            await self.db.upsert_movie("user1", {"douban_movie_id": "3", "title": "C", "status": "do"})
            await self.db.commit_batch()

            ids = await self.db.get_all_collected_movie_ids("user1")
            self.assertEqual(ids, {"1", "2"})  # 只有 collect 和 wish

        run_async(_test())

    # -- update_movie_details --
    def test_update_movie_details(self):
        self._init_db()

        async def _test():
            await self.db.upsert_movie("user1", {
                "douban_movie_id": "100",
                "title": "Test",
                "status": "collect",
            })
            await self.db.commit_batch()

            await self.db.update_movie_details("100", "user1", "剧情,科幻", "美国", 2020)
            await self.db.commit_batch()

            movies = await self.db.get_movies_by_status("user1", "collect")
            self.assertEqual(len(movies), 1)
            m = movies[0]
            self.assertEqual(m["genres"], "剧情,科幻")
            self.assertEqual(m["regions"], "美国")
            self.assertEqual(m["year"], 2020)

        run_async(_test())

    # -- get_movies_without_details --
    def test_get_movies_without_details(self):
        self._init_db()

        async def _test():
            # 无 genres
            await self.db.upsert_movie("user1", {"douban_movie_id": "1", "title": "A", "status": "collect", "genres": ""})
            # 有 genres
            await self.db.upsert_movie("user1", {"douban_movie_id": "2", "title": "B", "status": "collect", "genres": "剧情"})
            await self.db.commit_batch()

            ids = await self.db.get_movies_without_details("user1", 10)
            self.assertIn("1", ids)
            self.assertNotIn("2", ids)

        run_async(_test())

    # -- update_last_sync --
    def test_update_last_sync(self):
        self._init_db()

        async def _test():
            await self.db.bind_user("user1", "d_abc", "cookie")
            await self.db.update_last_sync("user1")
            bind = await self.db.get_bind("user1")
            self.assertIsNotNone(bind["last_sync"])

        run_async(_test())


# --- 3.2 ProfileGenerator ---
class TestProfileGenerator(unittest.TestCase):
    """测试画像生成逻辑。"""

    def _make_mock_db(self, movies):
        db = MagicMock(spec=Database)
        db.get_movies_by_status = AsyncMock(return_value=movies)
        return db

    def test_generate_with_data(self):
        movies = [
            {"title": "A", "genres": "剧情,科幻", "regions": "美国,英国", "year": 2020, "user_rating": 4.0},
            {"title": "B", "genres": "剧情", "regions": "中国", "year": 2015, "user_rating": 3.0},
            {"title": "C", "genres": "科幻,动作", "regions": "美国", "year": 2010, "user_rating": 5.0},
            {"title": "D", "genres": "喜剧", "regions": "日本", "year": 2022, "user_rating": 4.0},
            {"title": "E", "genres": "剧情,喜剧", "regions": "中国,香港", "year": 2018, "user_rating": 3.5},
        ]
        db = self._make_mock_db(movies)
        gen = ProfileGenerator(db)

        result = run_async(gen.generate("user1"))

        # 验证输出包含关键部分
        self.assertIn("观影画像", result)
        self.assertIn("看过：5 部", result)
        self.assertIn("类型偏好", result)
        self.assertIn("地区偏好", result)
        self.assertIn("年代偏好", result)
        self.assertIn("评分习惯", result)
        # 剧情 应该是最热门类型（3次）
        self.assertIn("剧情", result)

    def test_generate_no_data(self):
        db = self._make_mock_db([])
        gen = ProfileGenerator(db)
        result = run_async(gen.generate("user1"))
        self.assertIn("暂无观影数据", result)

    def test_generate_rating_types(self):
        """验证评分类型标签：宽容型 / 严厉型 / 中立型。"""
        # 平均分 >= 4.0 => 宽容型
        high = [{"title": f"M{i}", "genres": "剧情", "regions": "", "year": 2020, "user_rating": 5.0} for i in range(3)]
        db_high = self._make_mock_db(high)
        result_high = run_async(ProfileGenerator(db_high).generate("u"))
        self.assertIn("宽容型", result_high)

        # 平均分 <= 2.5 => 严厉型
        low = [{"title": f"M{i}", "genres": "剧情", "regions": "", "year": 2020, "user_rating": 1.0} for i in range(3)]
        db_low = self._make_mock_db(low)
        result_low = run_async(ProfileGenerator(db_low).generate("u"))
        self.assertIn("严厉型", result_low)

        # 中间 => 中立型
        mid = [{"title": f"M{i}", "genres": "剧情", "regions": "", "year": 2020, "user_rating": 3.0} for i in range(3)]
        db_mid = self._make_mock_db(mid)
        result_mid = run_async(ProfileGenerator(db_mid).generate("u"))
        self.assertIn("中立型", result_mid)


# --- 3.3 Recommender ---
class TestRecommender(unittest.TestCase):
    """测试推荐逻辑。"""

    def _make_components(self, movies_collect, top250, watched_ids=None):
        db = MagicMock(spec=Database)
        db.get_bind = AsyncMock(return_value={"douban_uid": "d_abc"})
        db.get_all_collected_movie_ids = AsyncMock(return_value=watched_ids or set())
        db.get_movies_by_status = AsyncMock(return_value=movies_collect)

        client = MagicMock(spec=DoubanClient)
        client.fetch_top250 = AsyncMock(return_value=top250)

        return db, client

    def test_recommend_basic(self):
        """基本推荐：排除已标记，按分数排序，限制数量。"""
        collect_movies = [
            {"genres": "剧情,科幻", "regions": "美国", "user_rating": 4.0},
            {"genres": "剧情", "regions": "中国", "user_rating": 3.0},
        ]
        top250 = [
            {"douban_movie_id": "10", "title": "T1", "year": 2020, "avg_rating": 9.5, "genres": "剧情,科幻", "regions": "美国", "quote": "Great"},
            {"douban_movie_id": "20", "title": "T2", "year": 2019, "avg_rating": 8.5, "genres": "喜剧", "regions": "日本", "quote": ""},
            {"douban_movie_id": "30", "title": "T3", "year": 2018, "avg_rating": 8.0, "genres": "剧情", "regions": "中国", "quote": ""},
        ]
        db, client = self._make_components(collect_movies, top250, watched_ids={"20"})
        rec = Recommender(db, client, recommend_count=2, min_rating=8.0)

        results = run_async(rec.recommend("user1"))

        # 应该返回最多 2 条，且 "20" 被排除
        self.assertLessEqual(len(results), 2)
        ids = [r["douban_movie_id"] for r in results]
        self.assertNotIn("20", ids)
        # 第一条应该是 T1（类型匹配最多，评分最高）
        if results:
            self.assertEqual(results[0]["douban_movie_id"], "10")
            self.assertIn("reason", results[0])

    def test_recommend_with_genre_filter(self):
        """genre_filter 参数筛选。"""
        collect_movies = [
            {"genres": "剧情", "regions": "", "user_rating": 4.0},
        ]
        top250 = [
            {"douban_movie_id": "10", "title": "T1", "year": 2020, "avg_rating": 9.0, "genres": "剧情", "regions": "", "quote": ""},
            {"douban_movie_id": "20", "title": "T2", "year": 2020, "avg_rating": 9.0, "genres": "科幻", "regions": "", "quote": ""},
        ]
        db, client = self._make_components(collect_movies, top250)
        rec = Recommender(db, client, recommend_count=5, min_rating=8.0)

        results = run_async(rec.recommend("user1", "科幻"))
        for r in results:
            self.assertIn("科幻", r["genres"])

    def test_recommend_no_bind(self):
        """用户未绑定时返回空。"""
        db = MagicMock(spec=Database)
        db.get_bind = AsyncMock(return_value=None)
        client = MagicMock(spec=DoubanClient)

        rec = Recommender(db, client)
        results = run_async(rec.recommend("user1"))
        self.assertEqual(results, [])

    def test_recommend_low_rating_filtered(self):
        """低于 min_rating 的影片被过滤。"""
        collect_movies = [{"genres": "剧情", "regions": "", "user_rating": 4.0}]
        top250 = [
            {"douban_movie_id": "10", "title": "Low", "year": 2020, "avg_rating": 6.0, "genres": "剧情", "regions": "", "quote": ""},
            {"douban_movie_id": "20", "title": "High", "year": 2020, "avg_rating": 9.0, "genres": "剧情", "regions": "", "quote": ""},
        ]
        db, client = self._make_components(collect_movies, top250)
        rec = Recommender(db, client, recommend_count=5, min_rating=8.0)

        results = run_async(rec.recommend("user1"))
        ids = [r["douban_movie_id"] for r in results]
        self.assertNotIn("10", ids)
        self.assertIn("20", ids)

    def test_recommend_reason_generation(self):
        """验证推荐理由的生成逻辑。"""
        collect_movies = [{"genres": "剧情,科幻", "regions": "美国", "user_rating": 4.0}]
        top250 = [
            {"douban_movie_id": "10", "title": "Great", "year": 2020, "avg_rating": 9.5, "genres": "剧情,科幻", "regions": "美国", "quote": "经典之作"},
        ]
        db, client = self._make_components(collect_movies, top250)
        rec = Recommender(db, client, recommend_count=5, min_rating=8.0)
        results = run_async(rec.recommend("user1"))

        self.assertTrue(len(results) > 0)
        r = results[0]
        reason = r["reason"]
        # 应包含类型匹配、高评分、引用
        self.assertTrue(len(reason) > 0)


# --- 3.4 DoubanClient._parse_collection_item ---
class TestParseCollectionItem(unittest.TestCase):
    """测试 HTML 片段解析 _parse_collection_item。"""

    def _make_soup_item(self, html_fragment: str):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(f"<div class='item'>{html_fragment}</div>", "html.parser")
        return soup.select_one(".item")

    def test_parse_basic_item(self):
        item = self._make_soup_item("""
            <a href="https://movie.douban.com/subject/1234567/" title="测试电影"></a>
            <span class="rating1-t" />
            <span class="date">2024-01-15</span>
            <span class="tags">标签: 科幻 冒险</span>
        """)
        result = DoubanClient._parse_collection_item(item, "collect")
        self.assertIsNotNone(result)
        self.assertEqual(result["douban_movie_id"], "1234567")
        self.assertEqual(result["title"], "测试电影")
        self.assertEqual(result["status"], "collect")
        self.assertEqual(result["marked_at"], "2024-01-15")

    def test_parse_rating_values(self):
        """测试不同评级的解析。"""
        for rating_cls, expected_val in [("rating1-t", 1.0), ("rating2-t", 2.0), ("rating3-t", 3.0), ("rating4-t", 4.0), ("rating5-t", 5.0)]:
            item = self._make_soup_item(f"""
                <a href="https://movie.douban.com/subject/999/" title="Movie"></a>
                <span class="{rating_cls}" />
            """)
            result = DoubanClient._parse_collection_item(item, "collect")
            self.assertEqual(result["user_rating"], expected_val, f"Failed for {rating_cls}")

    def test_parse_no_rating(self):
        """没有评分元素时 user_rating 为 None。"""
        item = self._make_soup_item("""
            <a href="https://movie.douban.com/subject/999/" title="Movie"></a>
        """)
        result = DoubanClient._parse_collection_item(item, "wish")
        self.assertIsNone(result["user_rating"])

    def test_parse_no_link_returns_none(self):
        """没有链接时返回 None。"""
        item = self._make_soup_item("<span>No link here</span>")
        result = DoubanClient._parse_collection_item(item, "collect")
        self.assertIsNone(result)

    def test_parse_tags_prefix_stripped(self):
        """标签文本中的 '标签:' 前缀应被去除。"""
        item = self._make_soup_item("""
            <a href="https://movie.douban.com/subject/999/" title="Movie"></a>
            <span class="tags">标签: 喜剧 动画</span>
        """)
        result = DoubanClient._parse_collection_item(item, "collect")
        self.assertFalse(result["genres"].startswith("标签:"))
        self.assertIn("喜剧", result["genres"])


# --- 3.5 DoubanClient._parse_top250_item ---
class TestParseTop250Item(unittest.TestCase):
    """测试 Top 250 条目解析。"""

    def _make_soup_item(self, html_fragment: str):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(f"<ol class='grid_view'><li>{html_fragment}</li></ol>", "html.parser")
        return soup.select_one("ol.grid_view > li")

    def test_parse_basic_top250(self):
        item = self._make_soup_item("""
            <div class="pic">
                <a href="https://movie.douban.com/subject/1292052/">
                    <img alt="肖申克的救赎" />
                </a>
            </div>
            <div class="info">
                <div class="hd">
                    <span class="title">肖申克的救赎</span>
                </div>
                <div class="bd">
                    <p>导演: Frank Darabont&nbsp;&nbsp;&nbsp;主演: Tim Robbins
                    1994&nbsp;/&nbsp;美国&nbsp;/&nbsp;犯罪 剧情</p>
                    <div class="star">
                        <span class="rating_num">9.7</span>
                    </div>
                    <p class="quote"><span class="inq">希望让人自由。</span></p>
                </div>
            </div>
        """)
        result = DoubanClient._parse_top250_item(item)
        self.assertIsNotNone(result)
        self.assertEqual(result["douban_movie_id"], "1292052")
        self.assertEqual(result["title"], "肖申克的救赎")
        self.assertAlmostEqual(result["avg_rating"], 9.7)
        self.assertEqual(result["year"], 1994)
        self.assertEqual(result["quote"], "希望让人自由。")

    def test_parse_no_link_returns_none(self):
        item = self._make_soup_item("<div>No link</div>")
        result = DoubanClient._parse_top250_item(item)
        self.assertIsNone(result)

    def test_parse_missing_optional_fields(self):
        """缺少可选字段时不应崩溃。"""
        item = self._make_soup_item("""
            <a href="https://movie.douban.com/subject/555/">
                <img alt="Test" />
            </a>
            <span class="title">Test Movie</span>
        """)
        result = DoubanClient._parse_top250_item(item)
        self.assertIsNotNone(result)
        self.assertEqual(result["douban_movie_id"], "555")
        self.assertIsNone(result["avg_rating"])
        self.assertEqual(result["quote"], "")


if __name__ == "__main__":
    # 使用 unittest 文字发现器，输出更详细
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    # 退出码：0 全过，1 有失败
    sys.exit(0 if result.wasSuccessful() else 1)
