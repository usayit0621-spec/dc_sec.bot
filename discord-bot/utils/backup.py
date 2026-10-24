import json
import logging
import os
import subprocess
from datetime import datetime, timezone

import discord

log = logging.getLogger("backup")

BACKUP_CHANNEL_ID = 1525916749034295508
BACKUP_FILENAME = "dc_sec_backup.json"
LOCAL_TEMP_PATH = "backup_temp.json"

# Tables to export/import. Keep this list in sync with utils/database.SCHEMA
TABLES = [
    "sticky",
    "log_config",
    "reminder_config",
    "bump_templates",
    "levels",
    "level_rewards",
    "levelup_config",
    "automod_config",
    "url_whitelist",
    "spam_strikes",
    "whitelist",
    "warnings",
    "reminders",
    "welcome_config",
    "afk",
    "reaction_roles",
    "verification_config",
    "giveaways",
    "ticket_config",
    "ticket_channels",
    "word_blacklist",
    "suggest_config",
    "bot_whitelist",
    "channel_allowed",
]


async def export_data(db) -> dict:
    """Export all configured tables into a dict and attach metadata.

    Returns a dict with keys:
      - meta: {timestamp: ISOUTC, commit: shortsha or 'unknown'}
      - tables: {table_name: [rows...]}
    """
    data = {"meta": {}, "tables": {}}

    # try to obtain current git short commit for traceability
    commit = "unknown"
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()
    except Exception:
        pass

    data["meta"] = {"timestamp": datetime.now(timezone.utc).isoformat(), "commit": commit}

    for table in TABLES:
        try:
            cur = await db.conn.execute(f"SELECT * FROM {table}")
            rows = await cur.fetchall()
            data["tables"][table] = [dict(row) for row in rows]
        except Exception:
            log.exception(f"テーブル {table} のエクスポートに失敗しました")
            data["tables"][table] = []
    return data


async def import_data(db, data: dict, overwrite: bool = False):
    """
    Import backup data into DB.

    If overwrite is False (default), performs INSERT OR REPLACE for each row (merge/restore behavior).
    If overwrite is True, truncates each table in the backup before inserting (destructive).
    """
    tables = data.get("tables") or {}
    if overwrite:
        # destructive mode: delete existing rows for tables present in the backup
        for table in tables.keys():
            if table not in TABLES:
                continue
            try:
                await db.conn.execute(f"DELETE FROM {table}")
            except Exception:
                log.exception(f"バックアップ復元前のテーブル削除に失敗しました: {table}")
        await db.conn.commit()

    for table, rows in tables.items():
        if table not in TABLES or not rows:
            continue
        for row in rows:
            cols = list(row.keys())
            placeholders = ",".join("?" for _ in cols)
            col_str = ",".join(cols)
            values = [row[c] for c in cols]
            try:
                # Use INSERT OR REPLACE to merge entries based on primary key
                await db.conn.execute(
                    f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({placeholders})",
                    values,
                )
            except Exception:
                log.exception(f"バックアップ復元中にエラー: table={table}")
    await db.conn.commit()


async def upload_backup(bot, filename: str = BACKUP_FILENAME):
    """現在の全設定を JSON にまとめてバックアップ用チャンネルにアップロードする"""
    channel = bot.get_channel(BACKUP_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(BACKUP_CHANNEL_ID)
        except discord.HTTPException:
            log.warning("バックアップチャンネル(%s)の取得に失敗しました", BACKUP_CHANNEL_ID)
            return

    try:
        data = await export_data(bot.db)
        with open(LOCAL_TEMP_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 古いバックアップメッセージを削除し、チャンネルが肥大化しないようにする
        try:
            async for old_message in channel.history(limit=20):
                if bot.user and old_message.author.id == bot.user.id and old_message.attachments:
                    await old_message.delete()
        except discord.HTTPException:
            pass

        await channel.send(
            content=f"🗄️ 設定バックアップ ({data['meta']['timestamp']} UTC) commit={data['meta'].get('commit')}",
            file=discord.File(LOCAL_TEMP_PATH, filename=filename),
        )
    except discord.HTTPException:
        log.exception("バックアップのアップロードに失敗しました")
    except Exception:
        log.exception("バックアップ作成中にエラーが発生しました")
    finally:
        if os.path.exists(LOCAL_TEMP_PATH):
            try:
                os.remove(LOCAL_TEMP_PATH)
            except OSError:
                pass


async def restore_backup(bot, *, overwrite: bool = False):
    """起動時にバックアップ用チャンネルから最新の設定ファイルを読み込み、DBへ反映する

    If overwrite=True, performs destructive restore (truncate then insert).
    """
    try:
        channel = await bot.fetch_channel(BACKUP_CHANNEL_ID)
    except discord.HTTPException:
        log.warning("バックアップチャンネル(%s)にアクセスできません。新規状態で起動します。", BACKUP_CHANNEL_ID)
        return

    try:
        async for message in channel.history(limit=50):
            for attachment in message.attachments:
                if attachment.filename.endswith(BACKUP_FILENAME):
                    raw = await attachment.read()
                    data = json.loads(raw.decode("utf-8"))
                    await import_data(bot.db, data, overwrite=overwrite)
                    log.info("バックアップチャンネルから設定を復元しました (overwrite=%s)", overwrite)
                    return
    except discord.HTTPException:
        log.exception("バックアップの取得に失敗しました")
    except Exception:
        log.exception("バックアップの復元中にエラーが発生しました")

    log.info("有効なバックアップが見つかりませんでした(初回起動の可能性があります)")
