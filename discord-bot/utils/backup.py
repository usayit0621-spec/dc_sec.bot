import json
import logging
import os

import discord

log = logging.getLogger("backup")

BACKUP_CHANNEL_ID = 1525916749034295508
BACKUP_FILENAME = "dc_sec_backup.json"
LOCAL_TEMP_PATH = "backup_temp.json"

# Render等の実行環境はファイルシステムが永続化されないため、
# 全設定テーブルをこのチャンネルにJSONファイルとしてアップロードし、
# 起動時に読み込むことでSQLiteの内容を復元する。
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
    data = {}
    for table in TABLES:
        try:
            cur = await db.conn.execute(f"SELECT * FROM {table}")
            rows = await cur.fetchall()
            data[table] = [dict(row) for row in rows]
        except Exception:
            log.exception(f"テーブル {table} のエクスポートに失敗しました")
            data[table] = []
    return data


async def import_data(db, data: dict):
    for table, rows in data.items():
        if table not in TABLES or not rows:
            continue
        for row in rows:
            cols = list(row.keys())
            placeholders = ",".join("?" for _ in cols)
            col_str = ",".join(cols)
            values = [row[c] for c in cols]
            try:
                await db.conn.execute(
                    f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({placeholders})",
                    values,
                )
            except Exception:
                log.exception(f"バックアップ復元中にエラー: table={table}")
    await db.conn.commit()


async def upload_backup(bot):
    """現在の全設定をJSONにまとめてバックアップ用チャンネルにアップロードする"""
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
            json.dump(data, f, ensure_ascii=False)

        # 古いバックアップメッセージを削除し、チャンネルが肥大化しないようにする
        try:
            async for old_message in channel.history(limit=10):
                if bot.user and old_message.author.id == bot.user.id and old_message.attachments:
                    await old_message.delete()
        except discord.HTTPException:
            pass

        await channel.send(
            content=f"🗄️ 設定バックアップ ({discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC)",
            file=discord.File(LOCAL_TEMP_PATH, filename=BACKUP_FILENAME),
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


async def restore_backup(bot):
    """起動時にバックアップ用チャンネルから最新の設定ファイルを読み込み、DBへ反映する"""
    try:
        channel = await bot.fetch_channel(BACKUP_CHANNEL_ID)
    except discord.HTTPException:
        log.warning("バックアップチャンネル(%s)にアクセスできません。新規状態で起動します。", BACKUP_CHANNEL_ID)
        return

    try:
        async for message in channel.history(limit=20):
            for attachment in message.attachments:
                if attachment.filename == BACKUP_FILENAME:
                    raw = await attachment.read()
                    data = json.loads(raw.decode("utf-8"))
                    await import_data(bot.db, data)
                    log.info("バックアップチャンネルから設定を復元しました")
                    return
    except discord.HTTPException:
        log.exception("バックアップの取得に失敗しました")
    except Exception:
        log.exception("バックアップの復元中にエラーが発生しました")

    log.info("有効なバックアップが見つかりませんでした(初回起動の可能性があります)")
