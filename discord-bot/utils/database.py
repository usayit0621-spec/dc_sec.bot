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
    timeout_minutes INTEGER DEFAULT 10,
    anti_alt_enabled INTEGER DEFAULT 0,
    min_account_age_hours INTEGER DEFAULT 24,
    word_filter_enabled INTEGER DEFAULT 0,
    anti_phishing_enabled INTEGER DEFAULT 1,
    locked INTEGER DEFAULT 0,
    anti_caps_enabled INTEGER DEFAULT 0,
    caps_threshold INTEGER DEFAULT 70,
    anti_emoji_enabled INTEGER DEFAULT 0,
    emoji_limit INTEGER DEFAULT 10,
    anti_duplicate_enabled INTEGER DEFAULT 1,
    owner_dm_alerts INTEGER DEFAULT 1,
    panic_mode INTEGER DEFAULT 0,
    anti_perm_escalation INTEGER DEFAULT 1,
    block_urls_enabled INTEGER DEFAULT 0,
    zalgo_filter_enabled INTEGER DEFAULT 1,
    everyone_abuse_enabled INTEGER DEFAULT 1,
    app_spam_enabled INTEGER DEFAULT 1,
    app_spam_count INTEGER DEFAULT 6,
    app_spam_seconds INTEGER DEFAULT 8,
    strike_warn_threshold INTEGER DEFAULT 9,
    strike_ban_threshold INTEGER DEFAULT 10
);

CREATE TABLE IF NOT EXISTS url_whitelist (
    guild_id INTEGER NOT NULL,
    domain TEXT NOT NULL,
    PRIMARY KEY (guild_id, domain)
);

CREATE TABLE IF NOT EXISTS spam_strikes (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    count INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
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

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    channel_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    remind_at REAL NOT NULL,
    notified INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS welcome_config (
    guild_id INTEGER PRIMARY KEY,
    welcome_channel_id INTEGER,
    welcome_message TEXT,
    welcome_image_url TEXT,
    leave_channel_id INTEGER,
    leave_message TEXT,
    autorole_id INTEGER
);

CREATE TABLE IF NOT EXISTS afk (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    reason TEXT,
    timestamp REAL NOT NULL,
    original_nick TEXT,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS reaction_roles (
    guild_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    emoji TEXT NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (message_id, emoji)
);

CREATE TABLE IF NOT EXISTS verification_config (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    role_id INTEGER,
    message_id INTEGER
);

CREATE TABLE IF NOT EXISTS giveaways (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    prize TEXT NOT NULL,
    winners_count INTEGER NOT NULL,
    host_id INTEGER,
    end_time REAL NOT NULL,
    ended INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ticket_config (
    guild_id INTEGER PRIMARY KEY,
    category_id INTEGER,
    panel_channel_id INTEGER,
    panel_message_id INTEGER,
    support_role_id INTEGER,
    ticket_counter INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ticket_channels (
    channel_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    opener_id INTEGER NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS word_blacklist (
    guild_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    PRIMARY KEY (guild_id, word)
);

CREATE TABLE IF NOT EXISTS suggest_config (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL
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

    # ---------- welcome / leave / autorole ----------
    async def get_welcome_config(self, guild_id):
        cur = await self.conn.execute("SELECT * FROM welcome_config WHERE guild_id=?", (guild_id,))
        row = await cur.fetchone()
        if row is None:
            await self.conn.execute("INSERT INTO welcome_config (guild_id) VALUES (?)", (guild_id,))
            await self.conn.commit()
            cur = await self.conn.execute("SELECT * FROM welcome_config WHERE guild_id=?", (guild_id,))
            row = await cur.fetchone()
        return row

    async def update_welcome_config(self, guild_id, **kwargs):
        await self.get_welcome_config(guild_id)
        keys = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [guild_id]
        await self.conn.execute(f"UPDATE welcome_config SET {keys} WHERE guild_id=?", values)
        await self.conn.commit()

    # ---------- afk ----------
    async def set_afk(self, guild_id, user_id, reason, original_nick):
        await self.conn.execute(
            "INSERT INTO afk (guild_id, user_id, reason, timestamp, original_nick) VALUES (?,?,?,?,?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET reason=excluded.reason, timestamp=excluded.timestamp",
            (guild_id, user_id, reason, time.time(), original_nick),
        )
        await self.conn.commit()

    async def get_afk(self, guild_id, user_id):
        cur = await self.conn.execute("SELECT * FROM afk WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        return await cur.fetchone()

    async def remove_afk(self, guild_id, user_id):
        await self.conn.execute("DELETE FROM afk WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        await self.conn.commit()

    # ---------- reminders ----------
    async def add_reminder(self, guild_id, channel_id, user_id, message, remind_at):
        await self.conn.execute(
            "INSERT INTO reminders (guild_id, channel_id, user_id, message, remind_at) VALUES (?,?,?,?,?)",
            (guild_id, channel_id, user_id, message, remind_at),
        )
        await self.conn.commit()

    async def get_due_reminders(self, now):
        cur = await self.conn.execute("SELECT * FROM reminders WHERE remind_at<=? AND notified=0", (now,))
        return await cur.fetchall()

    async def mark_reminder_done(self, reminder_id):
        await self.conn.execute("UPDATE reminders SET notified=1 WHERE id=?", (reminder_id,))
        await self.conn.commit()

    # ---------- reaction roles ----------
    async def add_reaction_role(self, guild_id, message_id, emoji, role_id):
        await self.conn.execute(
            "INSERT OR REPLACE INTO reaction_roles (guild_id, message_id, emoji, role_id) VALUES (?,?,?,?)",
            (guild_id, message_id, emoji, role_id),
        )
        await self.conn.commit()

    async def remove_reaction_role(self, message_id, emoji):
        await self.conn.execute(
            "DELETE FROM reaction_roles WHERE message_id=? AND emoji=?", (message_id, emoji)
        )
        await self.conn.commit()

    async def get_reaction_role(self, message_id, emoji):
        cur = await self.conn.execute(
            "SELECT * FROM reaction_roles WHERE message_id=? AND emoji=?", (message_id, emoji)
        )
        return await cur.fetchone()

    # ---------- verification ----------
    async def set_verification(self, guild_id, channel_id, role_id, message_id):
        await self.conn.execute(
            "INSERT INTO verification_config (guild_id, channel_id, role_id, message_id) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id, "
            "role_id=excluded.role_id, message_id=excluded.message_id",
            (guild_id, channel_id, role_id, message_id),
        )
        await self.conn.commit()

    async def get_verification(self, guild_id):
        cur = await self.conn.execute("SELECT * FROM verification_config WHERE guild_id=?", (guild_id,))
        return await cur.fetchone()

    # ---------- giveaways ----------
    async def create_giveaway(self, guild_id, channel_id, prize, winners_count, host_id, end_time):
        cur = await self.conn.execute(
            "INSERT INTO giveaways (guild_id, channel_id, prize, winners_count, host_id, end_time) "
            "VALUES (?,?,?,?,?,?)",
            (guild_id, channel_id, prize, winners_count, host_id, end_time),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def set_giveaway_message(self, giveaway_id, message_id):
        await self.conn.execute("UPDATE giveaways SET message_id=? WHERE id=?", (message_id, giveaway_id))
        await self.conn.commit()

    async def get_due_giveaways(self, now):
        cur = await self.conn.execute("SELECT * FROM giveaways WHERE end_time<=? AND ended=0", (now,))
        return await cur.fetchall()

    async def mark_giveaway_ended(self, giveaway_id):
        await self.conn.execute("UPDATE giveaways SET ended=1 WHERE id=?", (giveaway_id,))
        await self.conn.commit()

    async def get_giveaway(self, giveaway_id):
        cur = await self.conn.execute("SELECT * FROM giveaways WHERE id=?", (giveaway_id,))
        return await cur.fetchone()

    async def get_giveaway_by_message(self, message_id):
        cur = await self.conn.execute("SELECT * FROM giveaways WHERE message_id=? AND ended=0", (message_id,))
        return await cur.fetchone()

    # ---------- tickets ----------
    async def get_ticket_config(self, guild_id):
        cur = await self.conn.execute("SELECT * FROM ticket_config WHERE guild_id=?", (guild_id,))
        row = await cur.fetchone()
        if row is None:
            await self.conn.execute("INSERT INTO ticket_config (guild_id) VALUES (?)", (guild_id,))
            await self.conn.commit()
            cur = await self.conn.execute("SELECT * FROM ticket_config WHERE guild_id=?", (guild_id,))
            row = await cur.fetchone()
        return row

    async def update_ticket_config(self, guild_id, **kwargs):
        await self.get_ticket_config(guild_id)
        keys = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [guild_id]
        await self.conn.execute(f"UPDATE ticket_config SET {keys} WHERE guild_id=?", values)
        await self.conn.commit()

    async def increment_ticket_counter(self, guild_id):
        config = await self.get_ticket_config(guild_id)
        new_count = config["ticket_counter"] + 1
        await self.conn.execute("UPDATE ticket_config SET ticket_counter=? WHERE guild_id=?", (new_count, guild_id))
        await self.conn.commit()
        return new_count

    async def add_ticket_channel(self, channel_id, guild_id, opener_id):
        await self.conn.execute(
            "INSERT INTO ticket_channels (channel_id, guild_id, opener_id, created_at) VALUES (?,?,?,?)",
            (channel_id, guild_id, opener_id, time.time()),
        )
        await self.conn.commit()

    async def get_ticket_channel(self, channel_id):
        cur = await self.conn.execute("SELECT * FROM ticket_channels WHERE channel_id=?", (channel_id,))
        return await cur.fetchone()

    async def remove_ticket_channel(self, channel_id):
        await self.conn.execute("DELETE FROM ticket_channels WHERE channel_id=?", (channel_id,))
        await self.conn.commit()

    # ---------- word blacklist ----------
    async def add_blacklist_word(self, guild_id, word):
        await self.conn.execute(
            "INSERT OR IGNORE INTO word_blacklist (guild_id, word) VALUES (?,?)", (guild_id, word.lower())
        )
        await self.conn.commit()

    async def remove_blacklist_word(self, guild_id, word):
        await self.conn.execute(
            "DELETE FROM word_blacklist WHERE guild_id=? AND word=?", (guild_id, word.lower())
        )
        await self.conn.commit()

    async def get_blacklist_words(self, guild_id):
        cur = await self.conn.execute("SELECT word FROM word_blacklist WHERE guild_id=?", (guild_id,))
        rows = await cur.fetchall()
        return [r["word"] for r in rows]

    # ---------- suggest ----------
    async def set_suggest_channel(self, guild_id, channel_id):
        await self.conn.execute(
            "INSERT INTO suggest_config (guild_id, channel_id) VALUES (?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id",
            (guild_id, channel_id),
        )
        await self.conn.commit()

    async def get_suggest_channel(self, guild_id):
        cur = await self.conn.execute("SELECT channel_id FROM suggest_config WHERE guild_id=?", (guild_id,))
        row = await cur.fetchone()
        return row["channel_id"] if row else None

    # ---------- url whitelist ----------
    async def add_url_whitelist(self, guild_id, domain):
        await self.conn.execute(
            "INSERT OR IGNORE INTO url_whitelist (guild_id, domain) VALUES (?,?)", (guild_id, domain.lower())
        )
        await self.conn.commit()

    async def remove_url_whitelist(self, guild_id, domain):
        await self.conn.execute(
            "DELETE FROM url_whitelist WHERE guild_id=? AND domain=?", (guild_id, domain.lower())
        )
        await self.conn.commit()

    async def get_url_whitelist(self, guild_id):
        cur = await self.conn.execute("SELECT domain FROM url_whitelist WHERE guild_id=?", (guild_id,))
        rows = await cur.fetchall()
        return [r["domain"] for r in rows]

    # ---------- spam strikes(スパム系タイムアウトの累積回数) ----------
    async def increment_strike(self, guild_id, user_id):
        await self.conn.execute(
            "INSERT INTO spam_strikes (guild_id, user_id, count) VALUES (?,?,1) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET count = count + 1",
            (guild_id, user_id),
        )
        await self.conn.commit()
        cur = await self.conn.execute(
            "SELECT count FROM spam_strikes WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        )
        row = await cur.fetchone()
        return row["count"] if row else 0

    async def get_strikes(self, guild_id, user_id):
        cur = await self.conn.execute(
            "SELECT count FROM spam_strikes WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        )
        row = await cur.fetchone()
        return row["count"] if row else 0

    async def reset_strikes(self, guild_id, user_id):
        await self.conn.execute(
            "DELETE FROM spam_strikes WHERE guild_id=? AND user_id=?", (guild_id, user_id)
        )
        await self.conn.commit()
