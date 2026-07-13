import time

import discord
from discord import app_commands
from discord.ext import commands


class Utility(commands.Cog):
    """ping / userinfo / serverinfo / avatar などの便利コマンド"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Botの応答速度を確認します")
    async def ping(self, interaction: discord.Interaction):
        start = time.perf_counter()
        await interaction.response.send_message("計測中...")
        end = time.perf_counter()
        api_latency = round(self.bot.latency * 1000)
        round_trip = round((end - start) * 1000)
        embed = discord.Embed(title="🏓 Pong!", color=discord.Color.blurple())
        embed.add_field(name="WebSocket", value=f"{api_latency}ms", inline=True)
        embed.add_field(name="応答時間", value=f"{round_trip}ms", inline=True)
        await interaction.edit_original_response(content=None, embed=embed)

    @app_commands.command(name="userinfo", description="ユーザーの情報を表示します")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        embed = discord.Embed(title=f"👤 {member}", color=member.color)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=str(member.id), inline=True)
        embed.add_field(name="ニックネーム", value=member.nick or "なし", inline=True)
        embed.add_field(name="Bot", value="はい" if member.bot else "いいえ", inline=True)
        embed.add_field(name="アカウント作成日", value=f"<t:{int(member.created_at.timestamp())}:F>", inline=False)
        if member.joined_at:
            embed.add_field(name="サーバー参加日", value=f"<t:{int(member.joined_at.timestamp())}:F>", inline=False)
        roles = [r.mention for r in member.roles if r != interaction.guild.default_role]
        embed.add_field(name=f"ロール ({len(roles)})", value=", ".join(roles) if roles else "なし", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="サーバーの情報を表示します")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = discord.Embed(title=f"🏠 {guild.name}", color=discord.Color.blurple())
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="サーバーID", value=str(guild.id), inline=True)
        embed.add_field(name="オーナー", value=str(guild.owner), inline=True)
        embed.add_field(name="メンバー数", value=str(guild.member_count), inline=True)
        embed.add_field(name="チャンネル数", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="ロール数", value=str(len(guild.roles)), inline=True)
        embed.add_field(name="作成日", value=f"<t:{int(guild.created_at.timestamp())}:F>", inline=True)
        embed.add_field(name="ブーストレベル", value=str(guild.premium_tier), inline=True)
        embed.add_field(name="ブースト数", value=str(guild.premium_subscription_count), inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="ユーザーのアバター画像を表示します")
    async def avatar(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        embed = discord.Embed(title=f"{member} のアバター", color=discord.Color.blurple())
        embed.set_image(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
