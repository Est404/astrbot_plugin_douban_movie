import sqlite3
from pathlib import Path

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
                bind_time    DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_sync    DATETIME
            );

            CREATE TABLE IF NOT EXISTS movie_collection (
                douban_movie_id  TEXT,
                astrbot_uid      TEXT,
                title            TEXT,
                user_rating      REAL,
                genres           TEXT,
                regions          TEXT,
                year             INTEGER,
                status           TEXT,
                marked_at        DATETIME,
                fetched_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (douban_movie_id, astrbot_uid)
            );
            """
        )
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None

    # ── user_bind ──────────────────────────────────────────────

    async def bind_user(self, astrbot_uid: str, douban_uid: str):
        await self._conn.execute(
            "INSERT OR REPLACE INTO user_bind (astrbot_uid, douban_uid) "
            "VALUES (?, ?)",
            (astrbot_uid, douban_uid),
        )
        await self._conn.commit()

    async def unbind_user(self, astrbot_uid: str):
        await self._conn.execute(
            "DELETE FROM user_bind WHERE astrbot_uid = ?", (astrbot_uid,)
        )
        await self._conn.execute(
            "DELETE FROM movie_collection WHERE astrbot_uid = ?", (astrbot_uid,)
        )
        await self._conn.commit()

    async def get_bind(self, astrbot_uid: str) -> dict | None:
        cursor = await self._conn.execute(
            "SELECT * FROM user_bind WHERE astrbot_uid = ?", (astrbot_uid,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_last_sync(self, astrbot_uid: str):
        await self._conn.execute(
            "UPDATE user_bind SET last_sync = CURRENT_TIMESTAMP "
            "WHERE astrbot_uid = ?",
            (astrbot_uid,),
        )
        await self._conn.commit()

    # ── movie_collection ───────────────────────────────────────

    async def upsert_movie(self, astrbot_uid: str, movie: dict):
        await self._conn.execute(
            "INSERT OR REPLACE INTO movie_collection "
            "(douban_movie_id, astrbot_uid, title, user_rating, genres, regions, "
            "year, status, marked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                movie["douban_movie_id"],
                astrbot_uid,
                movie.get("title", ""),
                movie.get("user_rating"),
                movie.get("genres", ""),
                movie.get("regions", ""),
                movie.get("year"),
                movie["status"],
                movie.get("marked_at"),
            ),
        )

    async def commit_batch(self):
        await self._conn.commit()

    async def get_movies_by_status(self, astrbot_uid: str, status: str) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM movie_collection WHERE astrbot_uid = ? AND status = ?",
            (astrbot_uid, status),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_all_collected_movie_ids(self, astrbot_uid: str) -> set[str]:
        cursor = await self._conn.execute(
            "SELECT douban_movie_id FROM movie_collection "
            "WHERE astrbot_uid = ? AND status IN ('collect', 'wish')",
            (astrbot_uid,),
        )
        rows = await cursor.fetchall()
        return {r["douban_movie_id"] for r in rows}

    async def get_movie_count(self, astrbot_uid: str) -> dict[str, int]:
        cursor = await self._conn.execute(
            "SELECT status, COUNT(*) as cnt FROM movie_collection "
            "WHERE astrbot_uid = ? GROUP BY status",
            (astrbot_uid,),
        )
        rows = await cursor.fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    async def get_movies_without_details(
        self, astrbot_uid: str, limit: int = 50
    ) -> list[str]:
        cursor = await self._conn.execute(
            "SELECT douban_movie_id FROM movie_collection "
            "WHERE astrbot_uid = ? AND (genres IS NULL OR genres = '' OR genres = ' ')",
            (astrbot_uid,),
        )
        rows = await cursor.fetchall()
        return [r["douban_movie_id"] for r in rows[:limit]]

    async def update_movie_details(
        self,
        douban_movie_id: str,
        astrbot_uid: str,
        genres: str,
        regions: str,
        year: int | None,
    ):
        await self._conn.execute(
            "UPDATE movie_collection SET genres = ?, regions = ?, year = ? "
            "WHERE douban_movie_id = ? AND astrbot_uid = ?",
            (genres, regions, year, douban_movie_id, astrbot_uid),
        )
