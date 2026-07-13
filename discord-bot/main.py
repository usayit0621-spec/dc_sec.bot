import asyncio
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from aiohttp import web

from utils.database import Database
from utils.backup import upload_backup, restore_backup

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
PORT = int(os.getenv("PORT", "10000"))  # RenderのWeb Serviceはこのポートへのヘルスチェックを要求する

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.members = True
INTENTS.guilds = True
INTENTS.voice_states = True
INTENTS.moderation = True
INTENTS.invites = True
INTENTS.presences = True  # /info user でオンライン状況・デバイス種別を取得するために必要

EXTENSIONS = [
    "cogs.sticky",
    "cogs.logging_cog",
    "cogs.bump_reminder",
    "cogs.security",
    "cogs.moderation",
    "cogs.utility",
    "cogs.presence",
    "cogs.embed_builder",
    "cogs.welcome",
    "cogs.info",
    "cogs.extras",
    "cogs.reaction_roles",
    "cogs.giveaway",
    "cogs.tickets",
    "cogs.leveling",
    "cogs.maintenance",
]


class MultiBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="mb!", intents=INTENTS, help_command=None)
        self.db = Database()
        self._restart_announced = False

    async def setup_hook(self):
        await self.db.connect()
        log.info("データベース接続完了")

        try:
            await restore_backup(self)
        except Exception:
            log.exception("バックアップ復元処理中にエラーが発生しました(新規状態のまま続行します)")

        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info(f"読み込み成功: {ext}")
            except Exception as e:
                log.exception(f"読み込み失敗: {ext} ({e})")

        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info(f"ギルド限定コマンド同期: {len(synced)} 件 (guild={GUILD_ID})")
        else:
            synced = await self.tree.sync()
            log.info(f"グローバルコマンド同期: {len(synced)} 件")

    async def on_ready(self):
        log.info(f"ログイン完了: {self.user} (ID: {self.user.id})")
        # ステータス表示は cogs/presence.py が10秒ごとにローテーションします

        if not self._restart_announced:
            self._restart_announced = True
            await self._announce_restart()

        if not self.backup_loop.is_running():
            self.backup_loop.start()

    @tasks.loop(minutes=10)
    async def backup_loop(self):
        """設定変更コマンド以外の細かな更新も定期的にバックアップチャンネルへ保存する(安全網)"""
        await upload_backup(self)

    @backup_loop.before_loop
    async def before_backup_loop(self):
        await self.wait_until_ready()

    async def _announce_restart(self):
        rows = await self.db.get_all_log_channels()
        if not rows:
            log.info("再起動アナウンス用のログチャンネルが未設定です。アナウンスをスキップします。")
            return

        embed = discord.Embed(
            title="🔄 再起動しました",
            description="Dc_Sec Botが再起動しました。",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        for row in rows:
            guild = self.get_guild(row["guild_id"]) if isinstance(row, dict) or hasattr(row, '__getitem__') else self.get_guild(row.guild_id)
            if not guild:
                continue
            channel = guild.get_channel(row["channel_id"]) if isinstance(row, dict) or hasattr(row, '__getitem__') else guild.get_channel(row.channel_id)
            if not channel:
                continue
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    async def close(self):
        if self.backup_loop.is_running():
            self.backup_loop.cancel()
        await self.db.close()
        await super().close()


bot = MultiBot()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "このコマンドを実行する権限がありません。"
    elif isinstance(error, app_commands.CommandOnCooldown):
        msg = f"クールダウン中です。あと {error.retry_after:.1f} 秒お待ちください。"
    elif isinstance(error, app_commands.BotMissingPermissions):
        msg = "Botに必要な権限がありません。ロールの権限設定を確認してください。"
    else:
        msg = "コマンドの実行中にエラーが発生しました。"
        log.exception("スラッシュコマンドエラー", exc_info=error)

    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except discord.HTTPException:
        pass


async def handle_health(request: web.Request):
    return web.json_response({"status": "ok", "bot": str(bot.user) if bot.user else "starting"})


async def start_webserver():
    """RenderのWeb Serviceはポートへの応答を要求するため、常駐する軽量HTTPサーバーを立てる"""
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/healthz", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info(f"ヘルスチェック用Webサーバーを起動しました (0.0.0.0:{PORT})")


async def main():
    if not TOKEN:
        raise RuntimeError("環境変数 DISCORD_TOKEN が設定されていません。")
    await start_webserver()
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
