import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_manage_messages

DEBOUNCE_SECONDS = 2.0


class Sticky(commands.Cog):
    """/stick で指定したメッセージをチャンネル下部に固定し続ける機能(プレーンテキスト送信)"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cache: dict[int, dict] = {}  # channel_id -> {message_id, content}
        self.pending: set[int] = set()

    async def cog_load(self):
        rows = await self.bot.db.get_all_sticky()
        for row in rows:
            self.cache[row["channel_id"]] = {
                "message_id": row["message_id"],
                "content": row["content"],
                "guild_id": row["guild_id"],
            }

    @app_commands.command(name="stick", description="指定したメッセージをこのチャンネルの下部にそのまま固定します")
    @app_commands.describe(msg="固定したいメッセージの内容")
    @is_manage_messages()
    async def stick(self, interaction: discord.Interaction, msg: str):
        channel = interaction.channel
        await interaction.response.defer(ephemeral=True)

        old = self.cache.get(channel.id)
        if old:
            try:
                old_msg = await channel.fetch_message(old["message_id"])
                await old_msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass

        sent = await channel.send(msg)
        await self.bot.db.set_sticky(channel.id, interaction.guild_id, sent.id, msg)
        self.cache[channel.id] = {"message_id": sent.id, "content": msg, "guild_id": interaction.guild_id}

        await interaction.followup.send("✅ スティックメッセージを設定しました。", ephemeral=True)

    @app_commands.command(name="unstick", description="このチャンネルのスティックメッセージを解除します")
    @is_manage_messages()
    async def unstick(self, interaction: discord.Interaction):
        channel = interaction.channel
        data = self.cache.pop(channel.id, None)
        await self.bot.db.remove_sticky(channel.id)

        if data:
            try:
                old_msg = await channel.fetch_message(data["message_id"])
                await old_msg.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            await interaction.response.send_message("✅ スティックメッセージを解除しました。", ephemeral=True)
        else:
            await interaction.response.send_message("このチャンネルにはスティックメッセージが設定されていません。", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return

        channel_id = message.channel.id
        data = self.cache.get(channel_id)
        if not data:
            return
        if message.id == data["message_id"]:
            return
        if channel_id in self.pending:
            return

        self.pending.add(channel_id)
        try:
            await asyncio.sleep(DEBOUNCE_SECONDS)
            await self._repost(message.channel, channel_id)
        finally:
            self.pending.discard(channel_id)

    async def _repost(self, channel: discord.abc.Messageable, channel_id: int):
        data = self.cache.get(channel_id)
        if not data:
            return
        try:
            old_msg = await channel.fetch_message(data["message_id"])
            await old_msg.delete()
        except (discord.NotFound, discord.HTTPException):
            pass

        try:
            sent = await channel.send(data["content"])
        except discord.HTTPException:
            return

        data["message_id"] = sent.id
        await self.bot.db.update_sticky_message_id(channel_id, sent.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Sticky(bot))
