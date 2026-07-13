import datetime

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_moderator, is_manage_messages


class Moderation(commands.Cog):
    """kick/ban/timeout/warn/purge などの基本的なモデレーションコマンド"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="kick", description="メンバーをキックします")
    @app_commands.describe(member="キックするメンバー", reason="理由")
    @is_moderator()
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "理由なし"):
        await member.kick(reason=f"{interaction.user} により実行: {reason}")
        embed = discord.Embed(title="👢 キックしました", color=discord.Color.orange())
        embed.add_field(name="対象", value=str(member), inline=True)
        embed.add_field(name="理由", value=reason, inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ban", description="メンバーをBANします")
    @app_commands.describe(member="BANするメンバー", reason="理由", delete_days="遡って削除するメッセージの日数(0-7)")
    @is_moderator()
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "理由なし", delete_days: app_commands.Range[int, 0, 7] = 0):
        await member.ban(reason=f"{interaction.user} により実行: {reason}", delete_message_days=delete_days)
        embed = discord.Embed(title="🔨 BANしました", color=discord.Color.red())
        embed.add_field(name="対象", value=str(member), inline=True)
        embed.add_field(name="理由", value=reason, inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unban", description="ユーザーIDを指定してBANを解除します")
    @is_moderator()
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "理由なし"):
        try:
            user = discord.Object(id=int(user_id))
            await interaction.guild.unban(user, reason=f"{interaction.user} により実行: {reason}")
            await interaction.response.send_message(f"✅ ID `{user_id}` のBANを解除しました。")
        except (ValueError, discord.NotFound):
            await interaction.response.send_message("そのユーザーIDのBANは見つかりませんでした。", ephemeral=True)

    @app_commands.command(name="timeout", description="メンバーを一時的にタイムアウトします")
    @app_commands.describe(member="対象メンバー", minutes="タイムアウトする分数", reason="理由")
    @is_moderator()
    async def timeout_cmd(self, interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str = "理由なし"):
        until = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
        await member.timeout(until, reason=f"{interaction.user} により実行: {reason}")
        embed = discord.Embed(title="⏳ タイムアウトしました", color=discord.Color.orange())
        embed.add_field(name="対象", value=str(member), inline=True)
        embed.add_field(name="時間", value=f"{minutes}分", inline=True)
        embed.add_field(name="理由", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="untimeout", description="メンバーのタイムアウトを解除します")
    @is_moderator()
    async def untimeout_cmd(self, interaction: discord.Interaction, member: discord.Member):
        await member.timeout(None, reason=f"{interaction.user} により解除")
        await interaction.response.send_message(f"✅ {member.mention} のタイムアウトを解除しました。")

    @app_commands.command(name="warn", description="メンバーに警告を発行します")
    @is_moderator()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        await self.bot.db.add_warning(interaction.guild_id, member.id, interaction.user.id, reason)
        rows = await self.bot.db.get_warnings(interaction.guild_id, member.id)
        embed = discord.Embed(title="⚠️ 警告を発行しました", color=discord.Color.yellow())
        embed.add_field(name="対象", value=str(member), inline=True)
        embed.add_field(name="累計警告数", value=str(len(rows)), inline=True)
        embed.add_field(name="理由", value=reason, inline=False)
        await interaction.response.send_message(embed=embed)
        try:
            await member.send(f"{interaction.guild.name} で警告を受けました。理由: {reason}")
        except discord.HTTPException:
            pass

    @app_commands.command(name="warnings", description="メンバーの警告履歴を表示します")
    @is_moderator()
    async def warnings_cmd(self, interaction: discord.Interaction, member: discord.Member):
        rows = await self.bot.db.get_warnings(interaction.guild_id, member.id)
        if not rows:
            await interaction.response.send_message("このメンバーに警告履歴はありません。", ephemeral=True)
            return
        embed = discord.Embed(title=f"⚠️ {member} の警告履歴", color=discord.Color.yellow())
        for row in rows[:15]:
            dt = datetime.datetime.fromtimestamp(row["timestamp"])
            embed.add_field(
                name=f"#{row['id']} - {dt.strftime('%Y-%m-%d %H:%M')}",
                value=f"理由: {row['reason']}\n実行者: <@{row['moderator_id']}>",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clearwarnings", description="メンバーの警告履歴を全て削除します")
    @is_moderator()
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        await self.bot.db.clear_warnings(interaction.guild_id, member.id)
        await interaction.response.send_message(f"✅ {member.mention} の警告履歴を削除しました。", ephemeral=True)

    @app_commands.command(name="purge", description="指定件数のメッセージを一括削除します")
    @app_commands.describe(count="削除する件数(1-100)")
    @is_manage_messages()
    async def purge(self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=count)
        await interaction.followup.send(f"✅ {len(deleted)} 件のメッセージを削除しました。", ephemeral=True)

    @app_commands.command(name="slowmode", description="このチャンネルのスローモードを設定します")
    @app_commands.describe(seconds="秒数(0で解除)")
    @is_manage_messages()
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
        await interaction.channel.edit(slowmode_delay=seconds)
        if seconds == 0:
            await interaction.response.send_message("✅ スローモードを解除しました。")
        else:
            await interaction.response.send_message(f"✅ スローモードを {seconds} 秒に設定しました。")


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
