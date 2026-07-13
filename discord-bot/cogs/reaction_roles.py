import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_manage_guild


class ReactionRoles(commands.Cog):
    """特定メッセージへのリアクションでロールを自動付与/剥奪する機能"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    rr_group = app_commands.Group(name="reactionrole", description="リアクションロールの設定")

    @rr_group.command(name="add", description="指定メッセージに絵文字リアクションでロールを付与する設定を追加します")
    @app_commands.describe(message_id="対象メッセージのID(メッセージを右クリック→IDをコピー)", emoji="使用する絵文字", role="付与するロール")
    @is_manage_guild()
    async def rr_add(self, interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("メッセージIDは数字で入力してください。", ephemeral=True)
            return

        target_message = None
        for channel in interaction.guild.text_channels:
            try:
                target_message = await channel.fetch_message(mid)
                break
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue

        if target_message is None:
            await interaction.response.send_message("指定したメッセージが見つかりませんでした。", ephemeral=True)
            return

        try:
            await target_message.add_reaction(emoji)
        except discord.HTTPException:
            await interaction.response.send_message("その絵文字はリアクションとして使用できません。", ephemeral=True)
            return

        await self.bot.db.add_reaction_role(interaction.guild_id, mid, emoji, role.id)
        await interaction.response.send_message(
            f"✅ メッセージ `{mid}` の {emoji} リアクションで {role.mention} を付与するよう設定しました。", ephemeral=True
        )

    @rr_group.command(name="remove", description="リアクションロールの設定を削除します")
    @app_commands.describe(message_id="対象メッセージのID", emoji="対象の絵文字")
    @is_manage_guild()
    async def rr_remove(self, interaction: discord.Interaction, message_id: str, emoji: str):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("メッセージIDは数字で入力してください。", ephemeral=True)
            return
        await self.bot.db.remove_reaction_role(mid, emoji)
        await interaction.response.send_message("✅ リアクションロールの設定を削除しました。", ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.member is None or payload.member.bot:
            return
        row = await self.bot.db.get_reaction_role(payload.message_id, str(payload.emoji))
        if not row:
            return
        role = payload.member.guild.get_role(row["role_id"])
        if role:
            try:
                await payload.member.add_roles(role, reason="リアクションロール")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        row = await self.bot.db.get_reaction_role(payload.message_id, str(payload.emoji))
        if not row:
            return
        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return
        role = guild.get_role(row["role_id"])
        if role:
            try:
                await member.remove_roles(role, reason="リアクションロール解除")
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactionRoles(bot))
