"""
Test 1: Plugin Import and Syntax Validation

Verifies that:
- All .py files are syntactically valid (via py_compile / ast.parse)
- The plugin can be imported as a package with relative imports working
- DoubanMovie.__init__ works with mock AstrBot dependencies
"""

from __future__ import annotations

import ast
import json
import py_compile
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1A: Syntax validation via py_compile
# ---------------------------------------------------------------------------

PLUGIN_PY_FILES = [
    "main.py",
    "db/__init__.py",
    "db/database.py",
    "service/__init__.py",
    "service/douban_client.py",
    "service/profile.py",
    "service/recommender.py",
]


@pytest.fixture
def plugin_dir():
    return Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("rel_path", PLUGIN_PY_FILES, ids=lambda p: p)
def test_py_compile_valid(plugin_dir, rel_path):
    """Each .py file compiles without SyntaxError via py_compile."""
    full_path = plugin_dir / rel_path
    # py_compile.compile returns the path on success, raises SyntaxError on failure
    result = py_compile.compile(str(full_path), doraise=True)
    assert result is not None


@pytest.mark.parametrize("rel_path", PLUGIN_PY_FILES, ids=lambda p: p)
def test_ast_parse_valid(plugin_dir, rel_path):
    """Each .py file parses into a valid AST."""
    full_path = plugin_dir / rel_path
    source = full_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(full_path))
    assert tree is not None


# ---------------------------------------------------------------------------
# 1B: Package import with relative imports
# ---------------------------------------------------------------------------

def test_import_db_database():
    """from .db.database import Database works when package is loaded."""
    from astrbot_plugin_douban_movie.db.database import Database
    assert Database is not None
    assert hasattr(Database, "init")
    assert hasattr(Database, "bind_user")
    # bind_user should accept exactly 2 args (astrbot_uid, douban_uid) -- no cookie
    import inspect
    sig = inspect.signature(Database.bind_user)
    params = list(sig.parameters.keys())
    assert params == ["self", "astrbot_uid", "douban_uid"], (
        f"bind_user signature changed: {params}"
    )


def test_import_service_douban_client():
    """from .service.douban_client import DoubanClient works."""
    from astrbot_plugin_douban_movie.service.douban_client import DoubanClient
    assert DoubanClient is not None
    assert hasattr(DoubanClient, "fetch_top250")
    assert hasattr(DoubanClient, "_parse_collection_item")
    assert hasattr(DoubanClient, "validate_uid")
    # _request should not have cookie parameter
    import inspect
    sig = inspect.signature(DoubanClient._request)
    params = list(sig.parameters.keys())
    assert "cookie" not in params, f"_request still has cookie param: {params}"


def test_import_service_profile():
    """from .service.profile import ProfileGenerator works."""
    from astrbot_plugin_douban_movie.service.profile import ProfileGenerator
    assert ProfileGenerator is not None
    assert hasattr(ProfileGenerator, "generate")
    assert hasattr(ProfileGenerator, "_collect_stats")
    assert hasattr(ProfileGenerator, "_format_stats_text")
    assert hasattr(ProfileGenerator, "_build_llm_prompt")


def test_import_service_recommender():
    """from .service.recommender import Recommender works."""
    from astrbot_plugin_douban_movie.service.recommender import Recommender
    assert Recommender is not None
    assert hasattr(Recommender, "recommend")
    assert hasattr(Recommender, "_build_llm_prompt")
    assert hasattr(Recommender, "_parse_llm_reasons")
    assert hasattr(Recommender, "_generate_template_reasons")


def test_relative_import_chain():
    """ProfileGenerator uses from ..db.database import Database -- verify this chain."""
    from astrbot_plugin_douban_movie.service.profile import ProfileGenerator
    from astrbot_plugin_douban_movie.db.database import Database
    # ProfileGenerator accepts a Database instance
    mock_db = MagicMock(spec=Database)
    gen = ProfileGenerator(mock_db)
    assert gen.db is mock_db


def test_recommender_relative_import_chain():
    """Recommender uses from ..db.database and from ..service.douban_client."""
    from astrbot_plugin_douban_movie.service.recommender import Recommender
    from astrbot_plugin_douban_movie.db.database import Database
    from astrbot_plugin_douban_movie.service.douban_client import DoubanClient
    mock_db = MagicMock(spec=Database)
    mock_client = MagicMock(spec=DoubanClient)
    rec = Recommender(mock_db, mock_client)
    assert rec.db is mock_db


# ---------------------------------------------------------------------------
# 1C: DoubanMovie instantiation with mock AstrBot
# ---------------------------------------------------------------------------

def test_doubanmovie_init_success():
    """DoubanMovie.__init__ succeeds with mock context and config."""
    from astrbot_plugin_douban_movie.db.database import Database
    from astrbot_plugin_douban_movie.main import DoubanMovie

    with patch.object(
        sys.modules["astrbot.api.star"].StarTools,
        "get_data_dir",
        return_value=Path(tempfile.gettempdir()) / "astrbot_test_qa",
    ):
        with patch("astrbot_plugin_douban_movie.main.asyncio.create_task"):
            with patch.object(Database, "init", new_callable=AsyncMock):
                ctx = MagicMock()
                config = {
                    "sync_timeout": 60,
                    "recommend_count": 5,
                    "min_rating": 8.0,
                    "request_interval_min": 1.0,
                    "request_interval_max": 3.0,
                    "max_retries": 3,
                    "detail_enrich_limit": 20,
                    "profile_provider_id": "",
                    "recommend_provider_id": "",
                }
                plugin = DoubanMovie(ctx, config)
                assert plugin.db is not None
                assert plugin.client is not None
                assert plugin.profile_gen is not None
                assert plugin.recommender is not None


def test_doubanmovie_init_empty_config():
    """DoubanMovie.__init__ works with an empty config dict (uses defaults)."""
    from astrbot_plugin_douban_movie.db.database import Database
    from astrbot_plugin_douban_movie.main import DoubanMovie

    with patch.object(
        sys.modules["astrbot.api.star"].StarTools,
        "get_data_dir",
        return_value=Path(tempfile.gettempdir()) / "astrbot_test_qa",
    ):
        with patch("astrbot_plugin_douban_movie.main.asyncio.create_task"):
            with patch.object(Database, "init", new_callable=AsyncMock):
                plugin = DoubanMovie(MagicMock(), {})
                assert plugin.client._interval_min == 1.0
                assert plugin.client._interval_max == 3.0
                assert plugin.client._max_retries == 3
                assert plugin.recommender._recommend_count == 5
                assert plugin.recommender._min_rating == 8.0
