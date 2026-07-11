import aiosqlite
import time

DB_PATH = "bot.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sticky (
    channel_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    message_id INTEGER,
    content TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS log_config (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS reminder_config (
    guild_id INTEGER NOT NULL,
    type TEXT NOT NULL,           -- 'bump' or 'up'
    channel_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    minutes_before INTEGER NOT NULL,
    next_time REAL,               -- unixtime: 次にコマンドが使用可能になる時刻
    notified INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, type)
);

CREATE TABLE IF NOT EXISTS automod_config (
    guild_id INTEGER PRIMARY KEY,
    anti_mention_enabled INTEGER DEFAULT 1,
    mention_limit INTEGER DEFAULT 5,
    anti_invite_enabled INTEGER DEFAULT 0,
    anti_spam_enabled INTEGER DEFAULT 1,
    spam_count INTEGER DEFAULT 5,
    spam_seconds INTEGER DEFAULT 5,
    anti_raid_enabled INTEGER DEFAULT 1,
    raid_join_count INTEGER DEFAULT 10,
    raid_seconds INTEGER DEFAULT 10,
    anti_nuke_enabled INTEGER DEFAULT 1,
    nuke_threshold INTEGER DEFAULT 3,
    timeout_minutes INTEGER DEFAULT 10
);

CREATE TABLE IF NOT EXISTS whitelist (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    reason TEXT,
    timestamp REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    # ---------- sticky ----------
    async def set_sticky(self, channel_id, guild_id, message_id, content):
        await self.conn.execute(
            "INSERT INTO sticky (channel_id, guild_id, message_id, content) VALUES (?,?,?,?) "
            "ON CONFLICT(channel_id) DO UPDATE SET message_id=excluded.message_id, content=excluded.content",
            (channel_id, guild_id, message_id, content),
        )
        await self.conn.commit()

    async def update_sticky_message_id(self, channel_id, message_id):
        await self.conn.execute(
            "UPDATE sticky SET message_id=? WHERE channel_id=?", (message_id, channel_id)
        )
        await self.conn.commit()

    async def get_sticky(self, channel_id):
        cur = await self.conn.execute("SELECT * FROM sticky WHERE channel_id=?", (channel_id,))
        return await cur.fetchone()

    async def remove_sticky(self, channel_id):
        await self.conn.execute("DELETE FROM sticky WHERE channel_id=?", (channel_id,))
        await self.conn.commit()

    async def get_all_sticky(self):
        cur = await self.conn.execute("SELECT * FROM sticky")
        return await cur.fetchall()

    # ---------- log ----------
    async def set_log_channel(self, guild_id, channel_id):
        await self.conn.execute(
            "INSERT INTO log_config (guild_id, channel_id) VALUES (?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id",
            (guild_id, channel_id),
        )
        await self.conn.commit()

    async def get_log_channel(self, guild_id):
        cur = await self.conn.execute("SELECT channel_id FROM log_config WHERE guild_id=?", (guild_id,))
        row = await cur.fetchone()
        return row["channel_id"] if row else None

    async def get_all_log_channels(self):
        cur = await self.conn.execute("SELECT * FROM log_config")
        return await cur.fetchall()

    # ---------- reminder ----------
    async def set_reminder_config(self, guild_id, type_, channel_id, role_id, minutes_before):
        await self.conn.execute(
            "INSERT INTO reminder_config (guild_id, type, channel_id, role_id, minutes_before, next_time, notified) "
            "VALUES (?,?,?,?,?,NULL,0) "
            "ON CONFLICT(guild_id, type) DO UPDATE SET channel_id=excluded.channel_id, "
            "role_id=excluded.role_id, minutes_before=excluded.minutes_before",
            (guild_id, type_, channel_id, role_id, minutes_before),
        )
        await self.conn.commit()

    async def set_reminder_next_time(self, guild_id, type_, next_time):
        await self.conn.execute(
            "UPDATE reminder_config SET next_time=?, notified=0 WHERE guild_id=? AND type=?",
            (next_time, guild_id, type_),
        )
        await self.conn.commit()

    async def mark_reminder_notified(self, guild_id, type_):
        await self.conn.execute(
            "UPDATE reminder_config SET notified=1 WHERE guild_id=? AND type=?", (guild_id, type_)
        )
        await self.conn.commit()

    async def get_reminder_config(self, guild_id, type_):
        cur = await self.conn.execute(
            "SELECT * FROM reminder_config WHERE guild_id=? AND type=?", (guild_id, type_)
        )
        return await cur.fetchone()

    async def get_all_reminders(self):
        cur = await self.conn.execute("SELECT * FROM reminder_config")
        return await cur.fetchall()

    # ---------- automod ----------
    async def get_automod(self, guild_id):
        cur = await self.conn.execute("SELECT * FROM automod_config WHERE guild_id=?", (guild_id,))
        row = await cur.fetchone()
        if row is None:
            await self.conn.execute("INSERT INTO automod_config (guild_id) VALUES (?)", (guild_id,))
            await self.conn.commit()
            cur = await self.conn.execute("SELECT * FROM automod_config WHERE guild_id=?", (guild_id,))
            row = await cur.fetchone()
        return row

    async def update_automod(self, guild_id, **kwargs):
        await self.get_automod(guild_id)
        keys = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [guild_id]
        await self.conn.execute(f"UPDATE automod_config SET {keys} WHERE guild_id=?", values)
        await self.conn.commit()

    # ---------- whitelist ----------
    async def add_whitelist(self, guild_id, user_id):
        await self.conn.execute(
            "INSERT OR IGNORE INTO whitelist (guild_id, user_id) VALUES (?,?)", (guild_id, user_id)
        )
        await self.conn.commit()

    async def remove_whitelist(self, guild_id, user_id):
        await self.conn.execute(
            "DELETE FROM whitelist WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        )
        await self.conn.commit()

    async def is_whitelisted(self, guild_id, user_id):
        cur = await self.conn.execute(
            "SELECT 1 FROM whitelist WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        )
        return await cur.fetchone() is not None

    # ---------- warnings ----------
    async def add_warning(self, guild_id, user_id, moderator_id, reason):
        await self.conn.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, timestamp) VALUES (?,?,?,?,?)",
            (guild_id, user_id, moderator_id, reason, time.time()),
        )
        await self.conn.commit()

    async def get_warnings(self, guild_id, user_id):
        cur = await self.conn.execute(
            "SELECT * FROM warnings WHERE guild_id=? AND user_id=? ORDER BY timestamp DESC",
            (guild_id, user_id),
        )
        return await cur.fetchall()

    async def clear_warnings(self, guild_id, user_id):
        await self.conn.execute(
            "DELETE FROM warnings WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        )
        await self.conn.commit()
