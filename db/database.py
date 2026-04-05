import json
import sqlite3
from pathlib import Path
from typing import Optional

import aiosqlite
from astrbot.api import logger


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        await self._create_tables()
        logger.info(f"数据库已初始化: {self.db_path}")

    async def _create_tables(self):
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_bind (
                astrbot_uid  TEXT PRIMARY KEY,
                douban_uid   TEXT NOT NULL,
                nickname     TEXT,
                bind_time    DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_profile DATETIME
            );

            CREATE TABLE IF NOT EXISTS user_profile (
                astrbot_uid      TEXT PRIMARY KEY,
                profile_text     TEXT,
                raw_stats        TEXT,
                genre_prefs      TEXT,
                region_prefs     TEXT,
                decade_prefs     TEXT,
                total_marked     INTEGER,
                updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_seen_movies (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                astrbot_uid     TEXT NOT NULL,
                douban_movie_id TEXT NOT NULL,
                title           TEXT,
                created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(astrbot_uid, douban_movie_id)
            );

            CREATE TABLE IF NOT EXISTS rec_session (
                session_id    TEXT PRIMARY KEY,
                astrbot_uid   TEXT NOT NULL,
                keyword       TEXT,
                candidate_ids TEXT,
                shown_ids     TEXT,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None

    # ── user_bind ──────────────────────────────────────────────

    async def bind_user(
        self, astrbot_uid: str, douban_uid: str, nickname: Optional[str] = None
    ):
        await self._conn.execute(
            "INSERT OR REPLACE INTO user_bind (astrbot_uid, douban_uid, nickname) "
            "VALUES (?, ?, ?)",
            (astrbot_uid, douban_uid, nickname),
        )
        await self._conn.commit()

    async def unbind_user(self, astrbot_uid: str):
        await self._conn.execute(
            "DELETE FROM user_bind WHERE astrbot_uid = ?", (astrbot_uid,)
        )
        await self._conn.execute(
            "DELETE FROM user_profile WHERE astrbot_uid = ?", (astrbot_uid,)
        )
        await self._conn.execute(
            "DELETE FROM user_seen_movies WHERE astrbot_uid = ?", (astrbot_uid,)
        )
        await self._conn.execute(
            "DELETE FROM rec_session WHERE astrbot_uid = ?", (astrbot_uid,)
        )
        await self._conn.commit()

    async def get_bind(self, astrbot_uid: str) -> Optional[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM user_bind WHERE astrbot_uid = ?", (astrbot_uid,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_last_profile(self, astrbot_uid: str):
        await self._conn.execute(
            "UPDATE user_bind SET last_profile = CURRENT_TIMESTAMP "
            "WHERE astrbot_uid = ?",
            (astrbot_uid,),
        )
        await self._conn.commit()

    # ── user_profile ───────────────────────────────────────────

    async def save_profile(
        self,
        astrbot_uid: str,
        profile_text: str,
        raw_stats: dict,
        genre_prefs: list,
        region_prefs: list,
        decade_prefs: list,
        total_marked: int,
    ):
        await self._conn.execute(
            "INSERT OR REPLACE INTO user_profile "
            "(astrbot_uid, profile_text, raw_stats, genre_prefs, region_prefs, "
            "decade_prefs, total_marked, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (
                astrbot_uid,
                profile_text,
                json.dumps(raw_stats, ensure_ascii=False),
                json.dumps(genre_prefs, ensure_ascii=False),
                json.dumps(region_prefs, ensure_ascii=False),
                json.dumps(decade_prefs, ensure_ascii=False),
                total_marked,
            ),
        )
        await self._conn.commit()

    async def get_profile(self, astrbot_uid: str) -> Optional[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM user_profile WHERE astrbot_uid = ?", (astrbot_uid,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        # Parse JSON fields
        for key in ("raw_stats", "genre_prefs", "region_prefs", "decade_prefs"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    d[key] = None
        return d

    # ── user_seen_movies ───────────────────────────────────────

    async def add_seen_movies(self, astrbot_uid: str, movies: list[dict]):
        """批量添加已看过电影记录。movies: [{douban_movie_id, title}]"""
        for m in movies:
            await self._conn.execute(
                "INSERT OR IGNORE INTO user_seen_movies "
                "(astrbot_uid, douban_movie_id, title) VALUES (?, ?, ?)",
                (astrbot_uid, m["douban_movie_id"], m.get("title", "")),
            )
        await self._conn.commit()

    async def get_seen_movie_ids(self, astrbot_uid: str) -> set[str]:
        cursor = await self._conn.execute(
            "SELECT douban_movie_id FROM user_seen_movies WHERE astrbot_uid = ?",
            (astrbot_uid,),
        )
        rows = await cursor.fetchall()
        return {r["douban_movie_id"] for r in rows}

    # ── rec_session ────────────────────────────────────────────

    async def create_rec_session(
        self,
        session_id: str,
        astrbot_uid: str,
        keyword: str,
        candidate_ids: list[str],
    ):
        await self._conn.execute(
            "INSERT OR REPLACE INTO rec_session "
            "(session_id, astrbot_uid, keyword, candidate_ids, shown_ids) "
            "VALUES (?, ?, ?, ?, '[]')",
            (
                session_id,
                astrbot_uid,
                keyword,
                json.dumps(candidate_ids),
            ),
        )
        await self._conn.commit()

    async def get_rec_session(self, session_id: str) -> Optional[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM rec_session WHERE session_id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        for key in ("candidate_ids", "shown_ids"):
            if d.get(key):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    d[key] = []
        return d

    async def update_rec_session_shown(self, session_id: str, shown_ids: list[str]):
        await self._conn.execute(
            "UPDATE rec_session SET shown_ids = ? WHERE session_id = ?",
            (json.dumps(shown_ids), session_id),
        )
        await self._conn.commit()
