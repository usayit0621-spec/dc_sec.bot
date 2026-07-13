import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_manage_guild


def render(template: str, member: discord.Member) -> str:
    if not template:
        return ""
    return (
        template.replace("{user}", member.mention)
        .replace("{name}", member.display_name)
        .replace("{server}", member.guild.name)
        .replace("{count}", str(member.guild.member_count))
    )


class Welcome(commands.Cog):
    """メンバー参加/退出時のメッセージ送信と自動ロール付与"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    welcome_group = app_commands.Group(name="welcome", description="参加/退出メッセージ・自動ロールの設定")

    @welcome_group.command(name="setup", description="メンバー参加時のメッセージと自動付与ロールを設定します")
    @app_commands.describe(
        channel="参加メッセージを送るチャンネル",
        message="参加メッセージ本文。{user}{name}{server}{count} が使えます",
        image_url="埋め込む画像のURL(任意)",
        autorole="参加時に自動付与するロール(任意)",
    )
    @is_manage_guild()
    async def welcome_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: str = "{user} さん、{server} へようこそ！(メンバー数: {count}人目)",
        image_url: str = None,
        autorole: discord.Role = None,
    ):
        await self.bot.db.update_welcome_config(
            interaction.guild_id,
            welcome_channel_id=channel.id,
            welcome_message=message,
            welcome_image_url=image_url,
            autorole_id=autorole.id if autorole else None,
        )
        embed = discord.Embed(title="✅ 参加メッセージを設定しました", color=discord.Color.green())
        embed.add_field(name="チャンネル", value=channel.mention, inline=True)
        embed.add_field(name="自動付与ロール", value=autorole.mention if autorole else "なし", inline=True)
        embed.add_field(name="メッセージ", value=message, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @welcome_group.command(name="leave-setup", description="メンバー退出時のメッセージを設定します")
    @app_commands.describe(channel="退出メッセージを送るチャンネル", message="退出メッセージ本文。{name}{server}{count} が使えます")
    @is_manage_guild()
    async def leave_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: str = "{name} さんが {server} から退出しました。",
    ):
        await self.bot.db.update_welcome_config(
            interaction.guild_id, leave_channel_id=channel.id, leave_message=message
        )
        await interaction.response.send_message(f"✅ 退出メッセージを {channel.mention} に設定しました。", ephemeral=True)

    @welcome_group.command(name="disable", description="参加/退出メッセージと自動ロールを無効化します")
    @is_manage_guild()
    async def welcome_disable(self, interaction: discord.Interaction):
        await self.bot.db.update_welcome_config(
            interaction.guild_id,
            welcome_channel_id=None,
            leave_channel_id=None,
            autorole_id=None,
        )
        await interaction.response.send_message("✅ 参加/退出メッセージと自動ロールを無効化しました。", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        config = await self.bot.db.get_welcome_config(member.guild.id)

        if config["autorole_id"]:
            role = member.guild.get_role(config["autorole_id"])
            if role:
                try:
                    await member.add_roles(role, reason="自動ロール付与")
                except discord.HTTPException:
                    pass

        if not config["welcome_channel_id"]:
            return
        channel = member.guild.get_channel(config["welcome_channel_id"])
        if not channel:
            return

        embed = discord.Embed(
            title="👋 ようこそ！",
            description=render(config["welcome_message"], member),
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        if config["welcome_image_url"]:
            embed.set_image(url=config["welcome_image_url"])
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        config = await self.bot.db.get_welcome_config(member.guild.id)
        if not config["leave_channel_id"]:
            return
        channel = member.guild.get_channel(config["leave_channel_id"])
        if not channel:
            return
        embed = discord.Embed(
            title="🚪 退出しました",
            description=render(config["leave_message"], member),
            color=discord.Color.dark_grey(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
