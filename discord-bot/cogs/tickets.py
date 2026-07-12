import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_manage_guild


class TicketPanelView(discord.ui.View):
    """パネルメッセージに常設するチケット作成ボタン"""

    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="🎫 チケットを開く", style=discord.ButtonStyle.primary, custom_id="ticket_open_button")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        config = await self.bot.db.get_ticket_config(guild.id)
        if not config or not config["category_id"]:
            await interaction.response.send_message("チケットシステムが設定されていません。管理者にお問い合わせください。", ephemeral=True)
            return

        category = guild.get_channel(config["category_id"])
        support_role = guild.get_role(config["support_role_id"]) if config["support_role_id"] else None

        number = await self.bot.db.increment_ticket_counter(guild.id)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        channel = await guild.create_text_channel(
            name=f"ticket-{number:04d}",
            category=category,
            overwrites=overwrites,
            reason=f"{interaction.user} がチケットを開きました",
        )
        await self.bot.db.add_ticket_channel(channel.id, guild.id, interaction.user.id)

        embed = discord.Embed(
            title="🎫 サポートチケット",
            description=f"{interaction.user.mention} さん、お問い合わせありがとうございます。\n担当者が対応するまでこちらでお待ちください。",
            color=discord.Color.blurple(),
        )
        await channel.send(content=support_role.mention if support_role else None, embed=embed, view=TicketCloseView(self.bot))
        await interaction.response.send_message(f"✅ チケットを作成しました: {channel.mention}", ephemeral=True)


class TicketCloseView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="🔒 チケットを閉じる", style=discord.ButtonStyle.danger, custom_id="ticket_close_button")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await self.bot.db.get_ticket_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message("このチャンネルはチケットではありません。", ephemeral=True)
            return
        await interaction.response.send_message("🔒 5秒後にこのチケットを閉じます。")
        await self.bot.db.remove_ticket_channel(interaction.channel_id)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"{interaction.user} によりチケットが閉じられました")
        except discord.HTTPException:
            pass


class Tickets(commands.Cog):
    """ボタン一つでサポート用個別チャンネルを作成するチケットシステム"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(TicketPanelView(bot))
        self.bot.add_view(TicketCloseView(bot))

    ticket_group = app_commands.Group(name="ticket", description="チケットシステムの設定")

    @ticket_group.command(name="setup", description="チケットシステムを設定します")
    @app_commands.describe(
        category="チケットチャンネルを作成するカテゴリ",
        panel_channel="チケット作成パネルを設置するチャンネル",
        support_role="対応する運営ロール(任意)",
    )
    @is_manage_guild()
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
        panel_channel: discord.TextChannel,
        support_role: discord.Role = None,
    ):
        await self.bot.db.update_ticket_config(
            interaction.guild_id,
            category_id=category.id,
            panel_channel_id=panel_channel.id,
            support_role_id=support_role.id if support_role else None,
        )

        embed = discord.Embed(
            title="🎫 サポートチケット",
            description="下のボタンを押すとサポート用の個別チャンネルが作成されます。",
            color=discord.Color.blurple(),
        )
        sent = await panel_channel.send(embed=embed, view=TicketPanelView(self.bot))
        await self.bot.db.update_ticket_config(interaction.guild_id, panel_message_id=sent.id)

        await interaction.response.send_message(f"✅ チケットパネルを {panel_channel.mention} に設置しました。", ephemeral=True)

    @ticket_group.command(name="close", description="現在のチケットチャンネルを閉じます")
    async def ticket_close(self, interaction: discord.Interaction):
        ticket = await self.bot.db.get_ticket_channel(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message("このチャンネルはチケットではありません。", ephemeral=True)
            return
        await interaction.response.send_message("🔒 このチケットを閉じます。")
        await self.bot.db.remove_ticket_channel(interaction.channel_id)
        try:
            await interaction.channel.delete(reason=f"{interaction.user} によりチケットが閉じられました")
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
