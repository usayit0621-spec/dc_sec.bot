import subprocess
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.backup import upload_backup, restore_backup
from utils import database as dbmod
from utils.checks import is_admin

log = logging.getLogger("maintenance")


class Maintenance(commands.Cog):
    """管理者向けの運用コマンド: バックアップ、マイグレーション、リロード等"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="backup-export", description="現在の設定をバックアップチャンネルへアップロードします(管理者限定)")
    @is_admin()
    async def backup_export(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await upload_backup(self.bot)
            await interaction.followup.send("✅ バックアップを作成してアップロードしました。", ephemeral=True)
        except Exception:
            log.exception("backup-export failed")
            await interaction.followup.send("❌ バックアップ作成中にエラーが発生しました。ログを確認してください。", ephemeral=True)

    @app_commands.command(name="backup-restore", description="バックアップチャンネルから最新の設定を復元します(管理者限定)")
    @is_admin()
    async def backup_restore(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await restore_backup(self.bot)
            await interaction.followup.send("✅ バックアップから設定を復元しました。", ephemeral=True)
        except Exception:
            log.exception("backup-restore failed")
            await interaction.followup.send("❌ バックアップ復元中にエラーが発生しました。ログを確認してください。", ephemeral=True)

    @app_commands.command(name="db-migrate", description="DBスキーマを検査し、欠けているテーブルを作成します(管理者限定)")
    @is_admin()
    async def db_migrate(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            # re-run the schema script to ensure missing tables are created
            schema = dbmod.SCHEMA
            await self.bot.db.conn.executescript(schema)
            await self.bot.db.conn.commit()
            await interaction.followup.send("✅ DBマイグレーションを実行しました。欠けているテーブルを作成しました。", ephemeral=True)
        except Exception:
            log.exception("db-migrate failed")
            await interaction.followup.send("❌ DBマイグレーションに失敗しました。ログを確認してください。", ephemeral=True)

    @app_commands.command(name="version", description="Botのバージョン(コミットSHA)を表示します")
    async def version(self, interaction: discord.Interaction):
        try:
            # try to read git commit
            rev = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()
        except Exception:
            rev = "unknown"
        await interaction.response.send_message(f"commit: `{rev}`")

    @app_commands.command(name="reload-cogs", description="指定または全てのcogを再読み込みします(ボットオーナーのみ)")
    async def reload_cogs(self, interaction: discord.Interaction, cog: str = None):
        # owner-only check
        is_owner = await self.bot.is_owner(interaction.user)
        if not is_owner:
            await interaction.response.send_message("このコマンドはボットオーナーのみ実行できます。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        targets = [cog] if cog else [*self.bot.extensions.keys()]
        results = []
        for t in targets:
            try:
                # reload extension (async)
                await self.bot.reload_extension(t)
                results.append((t, True, "reloaded"))
            except Exception as e:
                log.exception("failed reload %s", t)
                results.append((t, False, str(e)))
        msg = "".join([f"{t}: {'OK' if ok else 'ERR'}\n" for t, ok, _ in results])
        await interaction.followup.send(f"```
{msg}
```", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Maintenance(bot))
