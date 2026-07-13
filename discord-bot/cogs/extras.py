import re
import time
import asyncio
import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

NUMBER_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


class Extras(commands.Cog):
    """AFK / リマインダー / 投票(poll) / 提案(suggest) / スナイプなどの便利機能"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminder_loop.start()

        # スナイプ用の直近削除・編集メッセージキャッシュ (channel_id -> data)
        self.snipe_cache: dict[int, dict] = {}
        self.edit_snipe_cache: dict[int, dict] = {}

    def cog_unload(self):
        self.reminder_loop.cancel()

    # ---------------- AFK ----------------
    @app_commands.command(name="afk", description="AFK(離席中)状態に設定します。メンションされると自動でお知らせします")
    @app_commands.describe(reason="離席理由(任意)")
    async def afk(self, interaction: discord.Interaction, reason: str = "理由なし"):
        member = interaction.user
        await self.bot.db.set_afk(interaction.guild_id, member.id, reason, member.nick)
        try:
            if not (member.nick or "").startswith("[AFK] "):
                await member.edit(nick=f"[AFK] {member.display_name}"[:32])
        except discord.HTTPException:
            pass
        embed = discord.Embed(
            title="💤 AFKに設定しました",
            description=f"理由: {reason}",
            color=discord.Color.light_grey(),
        )
        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # AFK解除
        afk_row = await self.bot.db.get_afk(message.guild.id, message.author.id)
        if afk_row:
            await self.bot.db.remove_afk(message.guild.id, message.author.id)
            try:
                if afk_row["original_nick"] is not None:
                    await message.author.edit(nick=afk_row["original_nick"])
                elif (message.author.nick or "").startswith("[AFK] "):
                    await message.author.edit(nick=None)
            except discord.HTTPException:
                pass
            try:
                notice = await message.channel.send(f"👋 {message.author.mention} さん、おかえりなさい。AFKを解除しました。")
                await asyncio.sleep(5)
                await notice.delete()
            except discord.HTTPException:
                pass

        # メンションされた相手がAFKかチェック
        for mentioned in message.mentions:
            row = await self.bot.db.get_afk(message.guild.id, mentioned.id)
            if row:
                since = int(row["timestamp"])
                await message.channel.send(
                    f"💤 {mentioned.mention} さんは現在AFKです(<t:{since}:R>から)。理由: {row['reason']}",
                    allowed_mentions=discord.AllowedMentions.none(),
                )

    # ---------------- リマインダー ----------------
    @app_commands.command(name="remind", description="指定した分数後にこのチャンネルでリマインドします")
    @app_commands.describe(minutes="何分後に通知するか", content="リマインド内容")
    async def remind(self, interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 10080], content: str):
        remind_at = time.time() + minutes * 60
        await self.bot.db.add_reminder(interaction.guild_id, interaction.channel_id, interaction.user.id, content, remind_at)
        await interaction.response.send_message(
            f"⏰ {minutes}分後にお知らせします: {content}", ephemeral=True
        )

    @tasks.loop(seconds=20)
    async def reminder_loop(self):
        rows = await self.bot.db.get_due_reminders(time.time())
        for row in rows:
            await self.bot.db.mark_reminder_done(row["id"])
            channel = self.bot.get_channel(row["channel_id"])
            if not channel:
                continue
            embed = discord.Embed(title="⏰ リマインダー", description=row["message"], color=discord.Color.gold())
            try:
                await channel.send(content=f"<@{row['user_id']}>", embed=embed)
            except discord.HTTPException:
                pass

    @reminder_loop.before_loop
    async def before_reminder_loop(self):
        await self.bot.wait_until_ready()

    # ---------------- 投票(poll) ----------------
    @app_commands.command(name="poll", description="選択肢付きの投票を作成します(カンマ区切りで最大10個)")
    @app_commands.describe(question="質問内容", options="選択肢をカンマ区切りで入力(例: 賛成,反対,保留)")
    async def poll(self, interaction: discord.Interaction, question: str, options: str):
        choices = [o.strip() for o in options.split(",") if o.strip()][:10]
        if len(choices) < 2:
            await interaction.response.send_message("選択肢は2個以上、カンマ区切りで指定してください。", ephemeral=True)
            return

        description = "\n".join(f"{NUMBER_EMOJIS[i]} {c}" for i, c in enumerate(choices))
        embed = discord.Embed(title=f"📊 {question}", description=description, color=discord.Color.blurple())
        embed.set_footer(text=f"{interaction.user} が作成した投票")
        await interaction.response.send_message(embed=embed)
        sent = await interaction.original_response()
        for i in range(len(choices)):
            try:
                await sent.add_reaction(NUMBER_EMOJIS[i])
            except discord.HTTPException:
                pass

    # ---------------- 提案(suggest) ----------------
    suggest_group = app_commands.Group(name="suggest", description="提案システム")

    @suggest_group.command(name="setup", description="提案を送るチャンネルを設定します")
    @app_commands.describe(channel="提案が投稿されるチャンネル")
    async def suggest_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("この操作には管理権限が必要です。", ephemeral=True)
            return
        await self.bot.db.set_suggest_channel(interaction.guild_id, channel.id)
        await interaction.response.send_message(f"✅ 提案チャンネルを {channel.mention} に設定しました。", ephemeral=True)

    @suggest_group.command(name="new", description="新しい提案を投稿します")
    @app_commands.describe(content="提案内容")
    async def suggest_new(self, interaction: discord.Interaction, content: str):
        channel_id = await self.bot.db.get_suggest_channel(interaction.guild_id)
        if not channel_id:
            await interaction.response.send_message("提案チャンネルが未設定です。管理者に `/suggest setup` を依頼してください。", ephemeral=True)
            return
        channel = interaction.guild.get_channel(channel_id)
        if not channel:
            await interaction.response.send_message("提案チャンネルが見つかりませんでした。", ephemeral=True)
            return

        embed = discord.Embed(title="💡 新しい提案", description=content, color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
        embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        sent = await channel.send(embed=embed)
        await sent.add_reaction("👍")
        await sent.add_reaction("👎")
        await interaction.response.send_message(f"✅ 提案を投稿しました: {sent.jump_url}", ephemeral=True)

    # ---------------- スナイプ ----------------
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        self.snipe_cache[message.channel.id] = {
            "content": message.content,
            "author": str(message.author),
            "avatar": message.author.display_avatar.url,
            "time": time.time(),
        }

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot or before.content == after.content:
            return
        self.edit_snipe_cache[before.channel.id] = {
            "before": before.content,
            "after": after.content,
            "author": str(before.author),
            "avatar": before.author.display_avatar.url,
            "time": time.time(),
        }

    @app_commands.command(name="snipe", description="このチャンネルで直近に削除されたメッセージを表示します")
    async def snipe(self, interaction: discord.Interaction):
        data = self.snipe_cache.get(interaction.channel_id)
        if not data:
            await interaction.response.send_message("削除されたメッセージが見つかりません。", ephemeral=True)
            return
        embed = discord.Embed(description=data["content"] or "(テキストなし)", color=discord.Color.red(), timestamp=datetime.datetime.fromtimestamp(data["time"], tz=datetime.timezone.utc))
        embed.set_author(name=data["author"], icon_url=data["avatar"])
        embed.set_footer(text="削除されたメッセージ")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="editsnipe", description="このチャンネルで直近に編集されたメッセージを表示します")
    async def editsnipe(self, interaction: discord.Interaction):
        data = self.edit_snipe_cache.get(interaction.channel_id)
        if not data:
            await interaction.response.send_message("編集されたメッセージが見つかりません。", ephemeral=True)
            return
        embed = discord.Embed(color=discord.Color.orange(), timestamp=datetime.datetime.fromtimestamp(data["time"], tz=datetime.timezone.utc))
        embed.set_author(name=data["author"], icon_url=data["avatar"])
        embed.add_field(name="編集前", value=data["before"] or "(なし)", inline=False)
        embed.add_field(name="編集後", value=data["after"] or "(なし)", inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Extras(bot))
