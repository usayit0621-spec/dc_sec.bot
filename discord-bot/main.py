import asyncio
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from utils.database import Database

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.members = True
INTENTS.guilds = True
INTENTS.voice_states = True
INTENTS.moderation = True
INTENTS.invites = True

EXTENSIONS = [
    "cogs.sticky",
    "cogs.logging_cog",
    "cogs.bump_reminder",
    "cogs.security",
    "cogs.moderation",
    "cogs.utility",
    "cogs.presence",
]


class MultiBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="mb!", intents=INTENTS, help_command=None)
        self.db = Database()

    async def setup_hook(self):
        await self.db.connect()
        log.info("データベース接続完了")

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

    async def close(self):
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


async def main():
    if not TOKEN:
        raise RuntimeError("環境変数 DISCORD_TOKEN が設定されていません。")
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
