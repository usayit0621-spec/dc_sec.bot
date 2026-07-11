import os
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.checks import is_manage_guild

DISBOARD_BOT_ID = int(os.getenv("DISBOARD_BOT_ID", "302050872383242240"))
UP_BOT_ID = int(os.getenv("UP_BOT_ID", "761562078095867916"))

CYCLE_SECONDS = 120 * 60  # 2時間

BUMP_SUCCESS_KEYWORDS = ["表示順をアップ", "Bump done", "を上げました"]
UP_SUCCESS_KEYWORDS = ["アップしました", "Up done", "を上げました"]

BUMP_COMMAND_MENTION = "</bump:947088344167366698>"
UP_COMMAND_MENTION = "</up:1363739182672904354>"


class BumpReminder(commands.Cog):
    """Disboard等の /bump /up コマンドのクールダウンが明けたタイミングでメンション通知する機能"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.checker.start()

    def cog_unload(self):
        self.checker.cancel()

    # ---------------- setup commands ----------------
    @app_commands.command(name="bump-mantion", description="Disboardのbumpが可能になる前に通知するリマインダーを設定します")
    @app_commands.describe(min="何分前に通知するか", m="通知したいロールをメンション")
    @is_manage_guild()
    async def bump_mantion(self, interaction: discord.Interaction, min: app_commands.Range[int, 0, 119], m: discord.Role):
        await self.bot.db.set_reminder_config(interaction.guild_id, "bump", interaction.channel_id, m.id, min)
        embed = discord.Embed(
            title="✅ bumpリマインダーを設定しました",
            description=(
                f"このチャンネルで {m.mention} に、次回bump可能時刻の **{min}分前** に通知します。\n"
                f"（このサーバーで最初に <@{DISBOARD_BOT_ID}> のbumpが成功したタイミングから計測を開始します）"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="up-mantion", description="ディス速等の/upが可能になる前に通知するリマインダーを設定します")
    @app_commands.describe(min="何分前に通知するか", m="通知したいロールをメンション")
    @is_manage_guild()
    async def up_mantion(self, interaction: discord.Interaction, min: app_commands.Range[int, 0, 119], m: discord.Role):
        await self.bot.db.set_reminder_config(interaction.guild_id, "up", interaction.channel_id, m.id, min)
        embed = discord.Embed(
            title="✅ upリマインダーを設定しました",
            description=(
                f"このチャンネルで {m.mention} に、次回up可能時刻の **{min}分前** に通知します。\n"
                f"（このサーバーで最初に <@{UP_BOT_ID}> のupが成功したタイミングから計測を開始します）"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------------- detect bump/up success ----------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or not message.author.bot:
            return

        if message.author.id == DISBOARD_BOT_ID:
            await self._handle_success(message, "bump", BUMP_SUCCESS_KEYWORDS)
        elif message.author.id == UP_BOT_ID:
            await self._handle_success(message, "up", UP_SUCCESS_KEYWORDS)

    async def _handle_success(self, message: discord.Message, type_: str, keywords: list[str]):
        text = ""
        for embed in message.embeds:
            text += (embed.description or "") + (embed.title or "")
        text += message.content or ""

        if not any(k in text for k in keywords):
            return

        config = await self.bot.db.get_reminder_config(message.guild.id, type_)
        if not config:
            return

        next_time = time.time() + CYCLE_SECONDS
        await self.bot.db.set_reminder_next_time(message.guild.id, type_, next_time)

    # ---------------- background loop ----------------
    @tasks.loop(seconds=20)
    async def checker(self):
        now = time.time()
        rows = await self.bot.db.get_all_reminders()
        for row in rows:
            if row["next_time"] is None or row["notified"]:
                continue
            fire_at = row["next_time"] - row["minutes_before"] * 60
            if now >= fire_at:
                await self._notify(row)
                await self.bot.db.mark_reminder_notified(row["guild_id"], row["type"])

    @checker.before_loop
    async def before_checker(self):
        await self.bot.wait_until_ready()

    async def _notify(self, row):
        guild = self.bot.get_guild(row["guild_id"])
        if not guild:
            return
        channel = guild.get_channel(row["channel_id"])
        if not channel:
            return
        role = guild.get_role(row["role_id"])
        if not role:
            return

        mention = BUMP_COMMAND_MENTION if row["type"] == "bump" else UP_COMMAND_MENTION
        label = "bump" if row["type"] == "bump" else "up"

        embed = discord.Embed(
            title=f"⏰ もうすぐ /{label} が使用可能です",
            description=f"# {role.mention}\n{mention} が使用可能です。",
            color=discord.Color.gold(),
        )
        try:
            await channel.send(content=role.mention, embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(BumpReminder(bot))
